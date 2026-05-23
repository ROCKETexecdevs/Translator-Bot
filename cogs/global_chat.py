import discord
from discord.ext import commands
import asyncio
import aio_pika
import json
import hashlib
from collections import deque
from google import genai
import os

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
RABBITMQ_URL = f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}/"
QUEUE_NAME = "kingbot_tasks_v2"  # Updated to allow x-max-priority


class GlobalChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.chat_history = deque(maxlen=5)
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.translation_task = None

    async def cog_load(self):
        self.translation_task = asyncio.create_task(self.process_translation_queue())

    def cog_unload(self):
        if self.translation_task:
            self.translation_task.cancel()

    def get_cache_key(self, text, language):
        normalized_string = f"{text.strip().lower()}_{language.lower()}"
        return hashlib.md5(normalized_string.encode()).hexdigest()

    async def process_translation_queue(self):
        await asyncio.sleep(10)
        try:
            if not getattr(self.bot, "mq_connection", None):
                print("❌ Cannot start consumer: bot.mq_connection is missing.")
                return

            channel = await self.bot.mq_connection.channel()
            await channel.set_qos(prefetch_count=10)
            queue = await channel.declare_queue(
                QUEUE_NAME, durable=True, arguments={"x-max-priority": 10}
            )

            print("🐇 Consumer Online: Watching ALL channels...")

            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    try:
                        async with message.process(requeue=True):
                            task = json.loads(message.body.decode())

                            user_id = int(task["user_id"])
                            target_language = task["target_language"]
                            content = task["content"]
                            author_name = task["author_name"]
                            channel_name = task["channel_name"]
                            guild_name = task.get("guild_name", "Unknown Server")
                            context_str = task["context_str"]

                            # Use global bot cache
                            cache = self.bot.db
                            cache_key = self.get_cache_key(content, target_language)
                            cached_translation = await cache.get(cache_key)

                            if cached_translation:
                                translation = cached_translation
                                # Fast path for cache hits
                                await asyncio.sleep(0.1)
                            else:
                                # Fetch exclusion keywords from Database synchronously using cached copy
                                # The database client we use might be strictly async, so let's handle it carefully
                                try:
                                    exclusion_list = await cache.smembers(
                                        "translator_exclusion_keywords"
                                    )
                                except Exception:
                                    exclusion_list = []

                                exclusion_str = ""
                                if exclusion_list:
                                    words = ", ".join(
                                        [f"'{w}'" for w in exclusion_list]
                                    )
                                    exclusion_str = f" CRITICAL INSTRUCTION: Do NOT translate or alter these specific keywords under any circumstances: {words}."

                                prompt = f"Context: {context_str}\nProvide a strictly literal and accurate translation to {target_language} while sounding natural. Do not use overly conversational slang if the original text is standard (e.g., translate 'hello' as 'hello', not 'sup'). Maintain gamer slang ONLY if originally present. CRITICAL INSTRUCTION: If the original text is already primarily in {target_language}, output EXACTLY 'SAME_LANGUAGE_DETECTED' and nothing else. Otherwise, output ONLY the translation: \"{content}\"{exclusion_str}"

                                # Increment Usage & Get Routing Model
                                guild_id = task.get("guild_id")
                                current_usage = 0
                                if guild_id:
                                    from cogs.utils.tiers import (
                                        increment_translation_usage,
                                    )

                                    allowed, current_usage = (
                                        await increment_translation_usage(
                                            self.bot, guild_id, len(content)
                                        )
                                    )

                                def fetch_global_translation():
                                    from cogs.utils.translator_algo import (
                                        decide_translation_route,
                                        perform_google_translate_fallback,
                                    )

                                    model_choice = decide_translation_route(
                                        content, current_usage
                                    )

                                    if model_choice == "googletrans":
                                        return perform_google_translate_fallback(
                                            content, target_language
                                        )

                                    response = self.client.models.generate_content(
                                        model=model_choice, contents=prompt
                                    )
                                    return response.text.strip()

                                translation = await asyncio.get_running_loop().run_in_executor(
                                    None, fetch_global_translation
                                )
                                await cache.setex(cache_key, 86400, translation)

                            if "SAME_LANGUAGE_DETECTED" in translation:
                                print(
                                    f"Skipping DM for user {user_id}: language is already {target_language}"
                                )
                                continue

                            user = self.bot.get_user(
                                user_id
                            ) or await self.bot.fetch_user(user_id)
                            if user:
                                # Translate channel name with cache
                                chan_cache_key = (
                                    f"trans_chan:{channel_name}:{target_language}"
                                )
                                translated_channel = await cache.get(chan_cache_key)
                                if not translated_channel:

                                    def fetch_chan_translation():
                                        resp = self.client.models.generate_content(
                                            model="gemini-2.5-flash",
                                            contents=f"Translate this Discord channel name to {target_language}. Output ONLY the translated name precisely, no extra punctuation: {channel_name}",
                                        )
                                        return resp.text.strip()

                                    try:
                                        translated_channel = (
                                            await asyncio.get_running_loop().run_in_executor(
                                                None, fetch_chan_translation
                                            )
                                        )
                                        if translated_channel:
                                            # Cache for 1 week (604800 seconds)
                                            await cache.setex(
                                                chan_cache_key,
                                                604800,
                                                translated_channel,
                                            )
                                        else:
                                            translated_channel = channel_name
                                    except Exception:
                                        translated_channel = channel_name

                                print(
                                    f"Attempting to DM {user.display_name} ({user_id}) translation of {author_name}'s message"
                                )
                                try:
                                    await user.send(
                                        f"**({guild_name}) [{channel_name} | {translated_channel}] {author_name}:** {translation}"
                                    )
                                    print(
                                        f"Successfully sent DM to {user.display_name}"
                                    )
                                except discord.Forbidden:
                                    print(
                                        f"Failed to DM {user.display_name}: Forbidden (DMs disabled)"
                                    )

                    except Exception as e:
                        err_str = str(e)
                        print(f"❌ Consumer Error: {err_str}")
                        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                            print(
                                "⏳ Gemini Quota exceeded. Queue paused for 60 seconds..."
                            )
                            await asyncio.sleep(60)
                        else:
                            # Prevent tight crash loop on other errors
                            await asyncio.sleep(5)
        except Exception as e:
            print(f"❌ Failed to start RabbitMQ consumer loop: {e}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return

        context_str = (
            "\n".join(list(self.chat_history)) if self.chat_history else "None"
        )

        if not getattr(self.bot, "mq_channel", None):
            return

        try:
            # Prevent queueing empty/system messages
            if not message.content.strip():
                return

            cache = self.bot.db

            # Check if auto translator is disabled for this server
            if await cache.get(f"auto_translator_disabled:{message.guild.id}") == "1":
                return

            # Check if this channel is allowlisted for translations
            is_allowed = await cache.sismember(
                f"translation_channels:{message.guild.id}", str(message.channel.id)
            )
            if not is_allowed:
                return

            subs = await cache.hgetall(f"translator_subs:{message.guild.id}")
            if not subs:
                return

            try:
                opt_outs = await cache.smembers(
                    f"auto_translate_optout:{message.guild.id}"
                )
                opt_outs = {
                    opt_out.decode() if isinstance(opt_out, bytes) else str(opt_out)
                    for opt_out in opt_outs
                }
            except Exception:
                opt_outs = set()

            # Debug log to verify producer is running
            print(
                f"Producer found {len(subs)} translation subs for channel {message.channel.name}"
            )
            for uid_str, target_language in subs.items():
                if uid_str in opt_outs:
                    continue

                user_id = int(uid_str)
                if message.author.id == user_id:
                    continue

                payload = {
                    "user_id": user_id,
                    "guild_id": message.guild.id,
                    "target_language": target_language,
                    "content": message.content,
                    "author_name": message.author.display_name,
                    "channel_name": message.channel.name,
                    "guild_name": message.guild.name,
                    "context_str": context_str,
                }

                # Fetch guild tier to determine message routing priority
                from cogs.utils.tiers import get_guild_tier, Tier

                tier = await get_guild_tier(self.bot, message.guild.id)
                priority = 10 if tier >= Tier.ELITE else 0

                # Publish using the persistent global connection
                await self.bot.mq_channel.default_exchange.publish(
                    aio_pika.Message(
                        body=json.dumps(payload).encode(), priority=priority
                    ),
                    routing_key=QUEUE_NAME,
                )
        except Exception as e:
            print(f"❌ Producer Error: {e}")

        self.chat_history.append(
            f"{message.author.display_name} (#{message.channel.name}): {message.content}"
        )


async def setup(bot):
    await bot.add_cog(GlobalChat(bot))
