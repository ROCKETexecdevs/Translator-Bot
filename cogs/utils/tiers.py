import discord
from discord.ext import commands
from discord import app_commands
import time

UPSELL_URL = "https://yourwebsite.com/kingbot-premium"

# Tier Mapping


class Tier:
    FREE = 1
    PREMIUM = 2
    ELITE = 3


TRANSLATION_LIMITS = {Tier.FREE: 5000, Tier.PREMIUM: 1500000, Tier.ELITE: float("inf")}


class PremiumRequiredError(commands.CheckFailure):
    def __init__(self, required_tier: int):
        self.required_tier = required_tier


class AppPremiumRequiredError(app_commands.CheckFailure):
    def __init__(self, required_tier: int):
        self.required_tier = required_tier


async def get_guild_tier(bot, guild_id: int) -> int:
    """Fetch the guild's tier from database cache/postgres."""
    if not hasattr(bot, "db") or bot.db is None:
        return Tier.FREE

    val = await bot.db.get(f"guild_tier:{guild_id}")
    if val:
        try:
            return int(val)
        except ValueError:
            return Tier.FREE
    return Tier.FREE


async def increment_translation_usage(bot, guild_id: int, char_count: int) -> bool:
    """
    Increments translation quota and checks against the current tier limit.
    Returns (True/False if allowed, current_usage as int).
    """
    if not hasattr(bot, "db") or bot.db is None:
        return True, 0  # Fail-open if DB down

    tier = await get_guild_tier(bot, guild_id)
    limit = TRANSLATION_LIMITS.get(tier, 5000)

    if limit == float("inf"):
        pass  # We still track usage rather than early returning here

    key = f"trans_chars:{guild_id}"

    # We increment directly.
    current_usage = await bot.db.incr(key, amount=char_count)
    if isinstance(current_usage, bytes):
        current_usage = int(current_usage)

    # If this is the very first time we are incrementing this cycle (or the key just reset), it will equal char_count.
    # In a fully robust Postgres environment via our PostgresCache wrapper, to set an expiry cleanly we can do an async wrapper:
    # However, since `incr` in PostgresCache doesn't set TTL, we can handle the 30-day reset manually by storing a timestamp.
    timestamp_key = f"trans_chars_reset:{guild_id}"
    reset_timestamp = await bot.db.get(timestamp_key)

    current_time = int(time.time())
    if not reset_timestamp:
        # First usage, set reset time to 30 days from now
        await bot.db.set(timestamp_key, str(current_time + 2592000))
    else:
        try:
            if current_time > int(reset_timestamp):
                # Cycle complete, reset tokens
                await bot.db.set(key, str(char_count))
                await bot.db.set(timestamp_key, str(current_time + 2592000))
                current_usage = char_count
        except ValueError:
            pass

    allowed = True
    if limit != float("inf") and current_usage > limit:
        allowed = False

    return allowed, current_usage


def build_premium_embed(required_tier: int) -> discord.Embed:
    tier_map = {1: "Community", 2: "Premium", 3: "Elite"}
    embed = discord.Embed(
        title="🔒 Premium Feature Locked",
        description=f"This feature is exclusively available for guilds operating on **Tier {required_tier}: {tier_map.get(required_tier, 'Unknown')}** or higher.\n\n[Click here to upgrade your server!]({UPSELL_URL})",
        color=discord.Color.brand_red(),
    )
    embed.set_footer(text="Thank you for supporting KingBot's infrastructure!")
    return embed


def requires_tier(tier: int):
    """Decorator to enforce prefix commands."""

    async def predicate(ctx):
        if not ctx.guild:
            # Allow DM usage natively for free? Or block? Assume true for safety.
            return True
        current_tier = await get_guild_tier(ctx.bot, ctx.guild.id)
        if current_tier < tier:
            raise PremiumRequiredError(tier)
        return True

    return commands.check(predicate)


def app_requires_tier(tier: int):
    """Decorator to enforce app slash commands."""

    async def predicate(interaction: discord.Interaction):
        if not interaction.guild_id:
            return True
        current_tier = await get_guild_tier(interaction.client, interaction.guild_id)
        if current_tier < tier:
            raise AppPremiumRequiredError(tier)
        return True

    return app_commands.check(predicate)
