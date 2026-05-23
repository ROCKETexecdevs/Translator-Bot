import discord
import hashlib
import os
import asyncio
from google import genai
import logging

# Set up logging for translator
logger = logging.getLogger("KingBot.Translator")

# Local helper to reconstruct cache keys properly


def get_cache_key(text: str, language: str) -> str:
    normalized_string = f"{text.strip().lower()}_{language.lower()}"
    return hashlib.md5(normalized_string.encode()).hexdigest()


async def translate_content(
    text: str, target_locale: discord.Locale, bot=None, guild_id=None
) -> str:
    """
    Translates the given text to the target locale.
    Skips Translation if locale is English.
    Returns original text on any error (graceful degradation).
    """
    if not text or not isinstance(text, str):
        return text if isinstance(text, str) else ""

    # Handle standard English locales efficiently
    if target_locale in [
        discord.Locale.american_english,
        discord.Locale.british_english,
    ]:
        return text

    if bot is None or not hasattr(bot, "db"):
        return text

    try:
        cache = bot.db
        target_language = target_locale.value

        # Validate language code
        if not target_language or not isinstance(target_language, str):
            return text

        cache_key = get_cache_key(text, target_language)

        # Try to get cached translation
        try:
            cached_translation = await cache.get(cache_key)
            if cached_translation:
                return cached_translation
        except Exception as e:
            logger.debug(f"Cache retrieval error: {e}")

        # Fetch exclusion keywords from Postgres
        exclusion_list = []
        try:
            exclusion_list = await cache.smembers("translator_exclusion_keywords")
        except Exception as e:
            logger.debug(f"Failed to fetch exclusion keywords: {e}")

        exclusion_str = ""
        if exclusion_list:
            words = ", ".join([f"'{w}'" for w in exclusion_list])
            exclusion_str = f" CRITICAL INSTRUCTION: Do NOT translate or alter these specific keywords under any circumstances: {words}."

        prompt = f'Translate the text enclosed in <text_to_translate> tags to {target_language}. Be strict about literal and accurate translations. Do not use overly conversational slang if the original text is standard. Keep exact formatting/emojis, and output ONLY the raw translation with no preamble.{exclusion_str}\n\n<text_to_translate>\n{text}\n</text_to_translate>'

        # Quota check
        if guild_id:
            try:
                from cogs.utils.tiers import increment_translation_usage

                allowed, current_usage = await increment_translation_usage(
                    bot, guild_id, len(text)
                )
                if not allowed:
                    # Return original if quota exceeded
                    return text
            except Exception as e:
                logger.debug(f"Quota check error: {e}")

        try:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                logger.warning(
                    "GEMINI_API_KEY not configured - translator falling back to original text"
                )
                return text

            def translate_text_sync():
                """Synchronous translation call with timeout protection."""
                try:
                    client = genai.Client(api_key=api_key)
                    response = client.models.generate_content(
                        model="gemini-2.5-flash-lite", contents=prompt
                    )
                    return (
                        response.text
                        if response and hasattr(response, "text")
                        else None
                    )
                except Exception as inner_e:
                    logger.error(f"Gemini API error: {inner_e}")
                    raise

            # Run with timeout (15 seconds)
            translation = await asyncio.wait_for(
                asyncio.to_thread(translate_text_sync), timeout=15
            )

            if not translation or not isinstance(translation, str):
                return text

            translation = translation.strip()

            # Save to cache with 24h expiry
            try:
                await cache.setex(cache_key, 86400, translation)
            except Exception as e:
                logger.debug(f"Cache save error: {e}")

            return translation

        except asyncio.TimeoutError:
            logger.warning(f"Translation timeout for language {target_language}")
            return text
        except Exception as e:
            logger.error(f"Translation error for {target_language}: {e}")
            return text  # Graceful fallback to original text

    except Exception as e:
        logger.error(f"Unexpected error in translate_content: {e}")
        return text
