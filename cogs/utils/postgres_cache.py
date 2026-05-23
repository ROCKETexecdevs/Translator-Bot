import asyncpg
import os


class PostgresCache:
    def __init__(self, dsn=None):
        # Default fallback to translation_postgres locally
        self.dsn = dsn or os.getenv(
            "DATABASE_URL",
            "postgresql://kingbotuser:kingbotdbpass@localhost:5432/kingbotdb",
        )
        self.pool = None

    async def init_db(self):
        self.pool = await asyncpg.create_pool(dsn=self.dsn, min_size=5, max_size=50)

        async with self.pool.acquire() as conn:
            # Strings
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # Hashes (Dicts)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS hash_kv (
                    hash TEXT,
                    key TEXT,
                    value TEXT,
                    PRIMARY KEY (hash, key)
                )
            """)

            # Sets
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS set_kv (
                    set_name TEXT,
                    value TEXT,
                    PRIMARY KEY (set_name, value)
                )
            """)

            # Sorted Sets
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS zset_kv (
                    zset_name TEXT,
                    member TEXT,
                    score REAL,
                    PRIMARY KEY (zset_name, member)
                )
            """)

    async def close(self):
        if self.pool:
            await self.pool.close()

    # --- STRINGS ---
    async def get(self, key):
        val = await self.pool.fetchval("SELECT value FROM kv WHERE key = $1", key)
        return val

    async def set(self, key, value):
        await self.pool.execute(
            """
            INSERT INTO kv (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
            key,
            str(value),
        )

    async def setex(self, name, time, value):
        # Fallback dummy TTL behavior, treating it as a standard set
        await self.set(name, value)

    async def delete(self, key):
        await self.pool.execute("DELETE FROM kv WHERE key = $1", key)
        await self.pool.execute("DELETE FROM hash_kv WHERE hash = $1", key)
        await self.pool.execute("DELETE FROM set_kv WHERE set_name = $1", key)
        await self.pool.execute("DELETE FROM zset_kv WHERE zset_name = $1", key)

    async def incr(self, key, amount=1):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                val = await conn.fetchval(
                    "SELECT value FROM kv WHERE key = $1 FOR UPDATE", key
                )
                if val is None:
                    new_val = amount
                else:
                    try:
                        new_val = int(val) + amount
                    except ValueError:
                        new_val = amount
                await conn.execute(
                    """
                      INSERT INTO kv (key, value) VALUES ($1, $2)
                      ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                  """,
                    key,
                    str(new_val),
                )
                return new_val

    # --- HASHES ---
    async def hset(self, name, key, value):
        await self.pool.execute(
            """
            INSERT INTO hash_kv (hash, key, value) VALUES ($1, $2, $3)
            ON CONFLICT (hash, key) DO UPDATE SET value = EXCLUDED.value
        """,
            name,
            str(key),
            str(value),
        )

    async def hget(self, name, key):
        return await self.pool.fetchval(
            "SELECT value FROM hash_kv WHERE hash = $1 AND key = $2", name, str(key)
        )

    async def hexists(self, name, key):
        val = await self.pool.fetchval(
            "SELECT 1 FROM hash_kv WHERE hash = $1 AND key = $2", name, str(key)
        )
        return val is not None

    async def hdel(self, name, key):
        status = await self.pool.execute(
            "DELETE FROM hash_kv WHERE hash = $1 AND key = $2", name, str(key)
        )
        return status != "DELETE 0"

    async def hgetall(self, name):
        rows = await self.pool.fetch(
            "SELECT key, value FROM hash_kv WHERE hash = $1", name
        )
        return {row["key"]: row["value"] for row in rows}

    # --- SETS ---
    async def sadd(self, name, *values):
        count = 0
        for value in values:
            status = await self.pool.execute(
                """
                INSERT INTO set_kv (set_name, value) VALUES ($1, $2)
                ON CONFLICT (set_name, value) DO NOTHING
            """,
                name,
                str(value),
            )
            if status == "INSERT 0 1":
                count += 1
        return count

    async def srem(self, name, *values):
        count = 0
        for value in values:
            status = await self.pool.execute(
                "DELETE FROM set_kv WHERE set_name = $1 AND value = $2",
                name,
                str(value),
            )
            if status != "DELETE 0":
                count += 1
        return count

    async def smembers(self, name):
        rows = await self.pool.fetch(
            "SELECT value FROM set_kv WHERE set_name = $1", name
        )
        return set(row["value"] for row in rows)

    async def sismember(self, name, value):
        val = await self.pool.fetchval(
            "SELECT 1 FROM set_kv WHERE set_name = $1 AND value = $2", name, str(value)
        )
        return val is not None

    # --- SORTED SETS ---
    async def zscore(self, name, member):
        return await self.pool.fetchval(
            "SELECT score FROM zset_kv WHERE zset_name = $1 AND member = $2",
            name,
            str(member),
        )

    async def zrevrank(self, name, member):
        query = """
            SELECT rank FROM (
                SELECT member, row_number() OVER (ORDER BY score DESC, member DESC) - 1 as rank
                FROM zset_kv
                WHERE zset_name = $1
            ) ranked
            WHERE member = $2
        """
        return await self.pool.fetchval(query, name, str(member))

    async def zincrby(self, name, amount, member):
        member_str = str(member)
        query = """
            INSERT INTO zset_kv (zset_name, member, score) 
            VALUES ($1, $2, $3)
            ON CONFLICT (zset_name, member) DO UPDATE 
            SET score = zset_kv.score + EXCLUDED.score
            RETURNING score
        """
        new_score = await self.pool.fetchval(query, name, member_str, float(amount))
        return new_score

    async def zrevrange(self, name, start, end, withscores=False):
        limit = end - start + 1 if end != -1 else 9999999
        offset = start
        rows = await self.pool.fetch(
            """
            SELECT member, score FROM zset_kv 
            WHERE zset_name = $1 
            ORDER BY score DESC 
            LIMIT $2 OFFSET $3
        """,
            name,
            limit,
            offset,
        )

        if withscores:
            return [(row["member"], row["score"]) for row in rows]
        else:
            return [row["member"] for row in rows]
