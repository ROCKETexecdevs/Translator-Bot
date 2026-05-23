from cogs.utils.translator import translate_content
import discord
from discord.ext import commands
from google import genai
from cogs.utils.postgres_cache import PostgresCache
import asyncio
import aio_pika
import socket
import sys
import os
import fnmatch
from dotenv import load_dotenv

load_dotenv()

# Runtime allowlist: keep only translation + admin suite cogs.
ALLOWED_COG_EXTENSIONS = {
    "cogs.admin",
    "cogs.global_chat",
    "cogs.moderation",
    "cogs.quick_translator",
}

# --- SINGLE INSTANCE LOCK ---


def enforce_single_instance():
    global _lock_socket
    lock_port = int(os.getenv("BOT_LOCK_PORT", "17690"))
    _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock_socket.bind(("127.0.0.1", lock_port))
    except socket.error:
        print(
            f"❌ Another instance is already using lock port {lock_port}. Exiting to prevent ghost instances."
        )
        sys.exit(1)


enforce_single_instance()

# --- DISCORD SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.voice_states = True


class UniversalContext(commands.Context):
    async def send(self, content=None, **kwargs):
        # Grab the locale if it was invoked via slash command
        target_locale = (
            self.interaction.locale
            if self.interaction
            else discord.Locale.american_english
        )

        # Defer interaction if we need to translate to prevent timeouts!
        if self.interaction and not self.interaction.response.is_done():
            if target_locale not in [discord.Locale.american_english, discord.Locale.british_english]:
                try:
                    await self.interaction.response.defer(ephemeral=kwargs.get("ephemeral", False))
                except discord.HTTPException:
                    pass

        tasks = []

        guild_id = self.guild.id if hasattr(self, "guild") and self.guild else None
        # 1. Translate string content
        if content:
            tasks.append(
                translate_content(
                    content, target_locale, bot=self.bot, guild_id=guild_id
                )
            )

        # 2. Translate Embeds
        embeds = kwargs.get("embeds", [])
        embed = kwargs.get("embed")
        if embed:
            embeds.append(embed)

        for e in embeds:
            if e.title:
                tasks.append(
                    translate_content(
                        e.title, target_locale, bot=self.bot, guild_id=guild_id
                    )
                )
            if e.description:
                tasks.append(
                    translate_content(
                        e.description, target_locale, bot=self.bot, guild_id=guild_id
                    )
                )
            # Support field translations as well
            for field in e.fields:
                if field.name:
                    tasks.append(
                        translate_content(
                            field.name, target_locale, bot=self.bot, guild_id=guild_id
                        )
                    )
                if field.value:
                    tasks.append(
                        translate_content(
                            field.value, target_locale, bot=self.bot, guild_id=guild_id
                        )
                    )

        # Execute all translations concurrently
        results = await asyncio.gather(*tasks) if tasks else []

        # Unpack results back into the objects
        res_idx = 0
        if content:
            content = results[res_idx]
            res_idx += 1

        for e in embeds:
            if e.title:
                e.title = results[res_idx]
                res_idx += 1
            if e.description:
                e.description = results[res_idx]
                res_idx += 1
            for index, set_field in enumerate(e.fields):
                new_name = set_field.name
                new_value = set_field.value
                if set_field.name:
                    new_name = results[res_idx]
                    res_idx += 1
                if set_field.value:
                    new_value = results[res_idx]
                    res_idx += 1
                e.set_field_at(
                    index, name=new_name, value=new_value, inline=set_field.inline
                )

        if embed and "embed" in kwargs:
            kwargs["embed"] = embeds[0]
        elif embeds:
            kwargs["embeds"] = embeds

        # 3. Pass the translated data to the original send method
        return await super().send(content, **kwargs)


class InMemoryCache:
    def __init__(self):
        self.kv = {}
        self.hash_kv = {}
        self.set_kv = {}
        self.zset_kv = {}

    async def init_db(self):
        return None

    async def close(self):
        return None

    async def get(self, key):
        return self.kv.get(key)

    async def set(self, key, value):
        self.kv[key] = str(value)

    async def setex(self, name, time, value):
        await self.set(name, value)

    async def delete(self, key):
        self.kv.pop(key, None)
        self.hash_kv.pop(key, None)
        self.set_kv.pop(key, None)
        self.zset_kv.pop(key, None)

    async def incr(self, key, amount=1):
        try:
            current = int(self.kv.get(key, "0"))
        except (TypeError, ValueError):
            current = 0
        new_val = current + amount
        self.kv[key] = str(new_val)
        return new_val

    async def hset(self, name, key, value):
        self.hash_kv.setdefault(name, {})[str(key)] = str(value)

    async def hget(self, name, key):
        return self.hash_kv.get(name, {}).get(str(key))

    async def hexists(self, name, key):
        return str(key) in self.hash_kv.get(name, {})

    async def hdel(self, name, key):
        h = self.hash_kv.get(name, {})
        if str(key) in h:
            del h[str(key)]
            return True
        return False

    async def hgetall(self, name):
        return dict(self.hash_kv.get(name, {}))

    async def sadd(self, name, *values):
        s = self.set_kv.setdefault(name, set())
        before = len(s)
        for value in values:
            s.add(str(value))
        return len(s) - before

    async def srem(self, name, *values):
        s = self.set_kv.get(name, set())
        removed = 0
        for value in values:
            v = str(value)
            if v in s:
                s.remove(v)
                removed += 1
        return removed

    async def smembers(self, name):
        return set(self.set_kv.get(name, set()))

    async def sismember(self, name, value):
        return str(value) in self.set_kv.get(name, set())

    async def zscore(self, name, member):
        return self.zset_kv.get(name, {}).get(str(member))

    async def zrevrank(self, name, member):
        z = self.zset_kv.get(name, {})
        ordered = sorted(z.items(), key=lambda x: (x[1], x[0]), reverse=True)
        target = str(member)
        for idx, (m, _score) in enumerate(ordered):
            if m == target:
                return idx
        return None

    async def zincrby(self, name, amount, member):
        z = self.zset_kv.setdefault(name, {})
        m = str(member)
        z[m] = float(z.get(m, 0.0)) + float(amount)
        return z[m]

    async def zrevrange(self, name, start, end, withscores=False):
        z = self.zset_kv.get(name, {})
        ordered = sorted(z.items(), key=lambda x: (x[1], x[0]), reverse=True)
        selected = ordered[start:] if end == -1 else ordered[start : end + 1]
        if withscores:
            return selected
        return [m for m, _score in selected]

    async def keys(self, pattern="*"):
        all_keys = set(self.kv.keys())
        all_keys.update(self.hash_kv.keys())
        all_keys.update(self.set_kv.keys())
        all_keys.update(self.zset_kv.keys())
        return [k for k in all_keys if fnmatch.fnmatch(k, pattern)]


class MyBot(commands.AutoShardedBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.allowed_cog_extensions = set(ALLOWED_COG_EXTENSIONS)

    async def get_context(self, message, *, cls=UniversalContext):
        return await super().get_context(message, cls=cls)

    async def setup_hook(self):
        # Establish persistent RabbitMQ connection for producers and consumers
        try:
            self.mq_connection = await aio_pika.connect_robust(RABBITMQ_URL)
            self.mq_channel = await self.mq_connection.channel()
            print("✅ Established persistent RabbitMQ connection.")
        except Exception as e:
            print(f"❌ Failed to establish persistent RabbitMQ connection: {e}")
            self.mq_connection = None
            self.mq_channel = None

        # Store database cache natively
        self.db = cache
        try:
            await self.db.init_db()
            print("✅ Initialized Postgres database pool.")
        except Exception as e:
            print(f"⚠️ Postgres unavailable, falling back to in-memory cache: {e}")
            self.db = InMemoryCache()
            await self.db.init_db()

        # Load only explicitly allowed cogs.
        for extension in sorted(self.allowed_cog_extensions):
            try:
                await self.load_extension(extension)
                print(f"✅ Loaded extension: {extension}")
            except Exception as e:
                print(f"❌ Failed to load extension {extension}. Error: {e}")

        try:
            synced = await self.tree.sync()
            print(f"✅ Synced {len(synced)} App Commands globally.")
        except Exception as e:
            print(f"❌ Failed to sync App Commands: {e}")

    async def close(self):
        if hasattr(self, "mq_connection") and self.mq_connection:
            try:
                await self.mq_connection.close()
                print("🛑 Closed RabbitMQ connection.")
            except Exception as e:
                print(f"⚠️ Error closing RabbitMQ connection: {e}")

        if hasattr(self, "db") and self.db:
            try:
                await self.db.close()
                print("🛑 Closed Postgres Database.")
            except Exception as e:
                print(f"⚠️ Error closing Postgres Database: {e}")
        await super().close()


# Disable default help command so we can create a custom !bothelp / !help
# AutoSharding and zero chunking handles massive scaling footprint.
bot = MyBot(
    command_prefix="!",
    intents=intents,
    help_command=None,
    chunk_guilds_at_startup=False,
)

# --- NEW GEMINI SDK SETUP (2026) ---
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
bot.gemini_client = client

# --- DATABASE CONNECTIONS ---
cache = PostgresCache()
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
RABBITMQ_URL = f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}/"


@bot.check
async def global_admin_toggle_check(ctx):
    if not ctx.guild:
        return True

    cmd_name = ctx.command.name if ctx.command else None
    
    # Core admin commands must always remain accessible to prevent lockouts
    core_admin_commands = ["toggle_command", "toggle_cog", "control_panel", "restart", "reload", "sync", "toggle_invisible"]
    if cmd_name in core_admin_commands:
        return True

    if cmd_name:
        try:
            is_disabled = await bot.db.get(f"cmd_disabled:{ctx.guild.id}:{cmd_name}")
            if is_disabled:
                raise commands.CheckFailure(
                    f"❌ The `{cmd_name}` command has been **disabled** on this server by an Administrator."
                )
        except Exception as e:
            # If DB goes down, default to allowing the command
            print(f"⚠️ Postgres connection failed during toggle check: {e}")
    return True


@bot.event
async def on_ready():
    # Run one-time guild sync on startup and log exact command counts by guild.
    if not getattr(bot, "_guild_sync_done", False):
        for guild in bot.guilds:
            try:
                bot.tree.copy_global_to(guild=guild)
                guild_synced = await bot.tree.sync(guild=guild)
                print(
                    f"✅ Guild Sync | {guild.name} ({guild.id}) -> {len(guild_synced)} commands"
                )
            except Exception as e:
                print(f"❌ Guild Sync Failed | {guild.name} ({guild.id}) -> {e}")
        bot._guild_sync_done = True

    try:
        is_invisible = await bot.db.get("kingbot_global_invisible")
        if is_invisible == "1":
            await bot.change_presence(status=discord.Status.invisible)
            print("👻 Initialized globally as INVISIBLE")
        else:
            await bot.change_presence(status=discord.Status.online)
    except Exception as e:
        print(f"⚠️ Failed to load global presence: {e}")

    print(f"✅ Logged in as {bot.user}")


# Removed obsolete !setname command (Now handled by OnboardingView above)

if __name__ == "__main__":
    token = (os.getenv("DISCORD_TOKEN") or "").strip()

    # Accept accidental "Bot <token>" format from copied auth headers.
    if token.lower().startswith("bot "):
        token = token[4:].strip()

    if not token:
        raise RuntimeError("DISCORD_TOKEN is missing or empty in environment/.env")

    bot.run(token)
