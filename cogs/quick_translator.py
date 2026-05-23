import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncio
from google import genai
import logging

logger = logging.getLogger("KingBot.QuickTranslator")

# Constants
MAX_TRANSLATION_LENGTH = 5000
API_TIMEOUT = 15


class TranslateModal(discord.ui.Modal, title="Translate Message"):
    language = discord.ui.TextInput(
        label="Target Language",
        placeholder="e.g., English, Spanish, Japanese...",
        required=True,
        max_length=50,
    )

    def __init__(self, message_to_translate: discord.Message, bot):
        super().__init__()
        self.message_to_translate = message_to_translate
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        target = self.language.value.strip()
        import re
        text = self.message_to_translate.content.strip()
        text = re.sub(r"^🌍\s*(?:\*\*)?[A-Za-z]+(?:\*\*)?:\s*", "", text).strip()

        # Input validation
        if not text:
            return await interaction.followup.send(
                "❌ Cannot translate empty message.", ephemeral=True
            )

        if len(text) > MAX_TRANSLATION_LENGTH:
            return await interaction.followup.send(
                f"❌ Message too long (max {MAX_TRANSLATION_LENGTH} characters).",
                ephemeral=True,
            )

        if not target:
            return await interaction.followup.send(
                "❌ Please specify a language.", ephemeral=True
            )

        try:
            exclusion_list = await self.bot.db.smembers("translator_exclusion_keywords")
        except Exception as e:
            logger.debug(f"Failed to fetch exclusion list: {e}")
            exclusion_list = []

        exclusion_str = ""
        if exclusion_list:
            words = ", ".join([f"'{w}'" for w in exclusion_list])
            exclusion_str = f" CRITICAL INSTRUCTION: Do NOT translate or alter these specific keywords under any circumstances: {words}."

        prompt = f"Translate the text enclosed in <text_to_translate> tags to {target}. Be strict about literal and accurate translations. Do not use overly conversational slang if the original text is standard (e.g., translate 'hello' as 'hello', not 'sup'). Maintain gamer slang ONLY if originally present, use minimal AI flourish, and output ONLY the raw translation without preamble.{exclusion_str}\n\n<text_to_translate>\n{text}\n</text_to_translate>"

        current_usage = 0

        try:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY environment variable is not set")

            def translate_text():
                from cogs.utils.translator_algo import (
                    decide_translation_route,
                    perform_google_translate_fallback,
                    perform_gemini_translation,
                    validate_translation_input,
                )

                # Validate input
                is_valid, error_msg = validate_translation_input(text, target)
                if not is_valid:
                    raise ValueError(error_msg or "Invalid translation input")

                model_choice = decide_translation_route(text, current_usage)

                if model_choice == "googletrans":
                    result = perform_google_translate_fallback(text, target)
                    if not result:
                        raise ValueError(
                            "Google Translate service temporarily unavailable. Please try again in a moment."
                        )
                    return result

                client = genai.Client(api_key=api_key)
                return perform_gemini_translation(
                    client, model_choice, prompt, text, target
                )

            translation = await asyncio.wait_for(
                asyncio.to_thread(translate_text), timeout=API_TIMEOUT
            )

            if not translation or not isinstance(translation, str):
                raise ValueError("Empty response from translation service")

            translation = translation.strip()
            if not translation:
                raise ValueError("Translation resulted in empty text")

            # Save language to the per-server synced background translation engine
            try:
                if interaction.guild_id:
                    await self.bot.db.hset(
                        f"translator_subs:{interaction.guild_id}",
                        str(interaction.user.id),
                        target,
                    )
            except Exception as e:
                logger.debug(f"Failed to sync per-server setting: {e}")

            embed = discord.Embed(
                title=f"🌍 Translated to {target.capitalize()}",
                description=translation,
                color=discord.Color.green(),
            )
            embed.set_author(
                name=self.message_to_translate.author.display_name,
                icon_url=(
                    self.message_to_translate.author.display_avatar.url
                    if self.message_to_translate.author.display_avatar
                    else None
                ),
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        except asyncio.TimeoutError:
            logger.warning("Translation request timed out")
            await interaction.followup.send(
                "⏳ Translation timed out. Service may be temporarily slow. Please try again.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Translation error in modal: {e}", exc_info=True)
            error_msg = str(e)

            # Handle specific error cases
            if "403" in error_msg or "PERMISSION_DENIED" in error_msg:
                await interaction.followup.send(
                    "❌ Translation failed - API key issue. Check your GEMINI_API_KEY configuration.",
                    ephemeral=True,
                )
            elif (
                "503" in error_msg
                or "service unavailable" in error_msg.lower()
                or "temporarily unavailable" in error_msg.lower()
            ):
                await interaction.followup.send(
                    "⏳ Translation service is temporarily unavailable (503). Please try again in a few seconds.",
                    ephemeral=True,
                )
            elif "quota" in error_msg.lower() or "rate limit" in error_msg.lower():
                await interaction.followup.send(
                    "⚠️ Translation quota exceeded. Please try again later.",
                    ephemeral=True,
                )
            elif "invalid" in error_msg.lower():
                await interaction.followup.send(f"❌ {error_msg}", ephemeral=True)
            else:
                await interaction.followup.send(
                    f"❌ Translation failed. Please try again. ({error_msg[:40]})",
                    ephemeral=True,
                )


class TransChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(
            channel_types=[discord.ChannelType.text],
            placeholder="Select translation channels...",
            min_values=0,
            max_values=25,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Clear existing config
        await self.bot.db.delete(f"translation_channels:{interaction.guild_id}")

        if not self.values:
            await interaction.followup.send(
                "📴 Cleared all translation channels. Auto-translation is disabled.",
                ephemeral=True,
            )
            return

        # Add new selections
        for channel in self.values:
            await self.bot.db.sadd(
                f"translation_channels:{interaction.guild_id}", str(channel.id)
            )

        mentions = [c.mention for c in self.values]
        await interaction.followup.send(
            "✅ Auto-translation is now enabled in:\n" + "\n".join(mentions),
            ephemeral=True,
        )


class TransConfigView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.add_item(TransChannelSelect(bot))


class QuickTranslator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ctx_menu = app_commands.ContextMenu(
            name="Translate to...",
            callback=self.translate_context_menu,
        )

    async def translate_context_menu(
        self, interaction: discord.Interaction, message: discord.Message
    ):
        # Always ask for language in DMs
        if interaction.guild_id is None:
            return await interaction.response.send_modal(
                TranslateModal(message, self.bot)
            )

        # Check if user has a per-server preference
        preferred_lang = None
        try:
            preferred_lang = await self.bot.db.hget(
                f"translator_subs:{interaction.guild_id}", str(interaction.user.id)
            )
            logger.debug(
                f"Retrieved preferred_lang for {interaction.user.id}: {preferred_lang}"
            )
        except Exception as e:
            logger.error(f"Failed to retrieve preferred_lang: {e}")

        if preferred_lang and preferred_lang.strip():  # Ensure not empty
            await interaction.response.defer(ephemeral=True)
            target = preferred_lang.strip()  # Clean whitespace
            import re
            text = message.content.strip()
            text = re.sub(r"^🌍\s*(?:\*\*)?[A-Za-z]+(?:\*\*)?:\s*", "", text).strip()
            logger.info(
                f"Using preferred language '{target}' for user {interaction.user.id}"
            )

            try:
                exclusion_list = await self.bot.db.smembers(
                    "translator_exclusion_keywords"
                )
            except Exception:
                exclusion_list = []
            exclusion_str = ""
            if exclusion_list:
                words = ", ".join([f"'{w}'" for w in exclusion_list])
                exclusion_str = f" CRITICAL INSTRUCTION: Do NOT translate or alter these specific keywords under any circumstances: {words}."

            prompt = f"Translate the text enclosed in <text_to_translate> tags to {target}. Be strict about literal and accurate translations. Do not use overly conversational slang if the original text is standard (e.g., translate 'hello' as 'hello', not 'sup'). Maintain gamer slang ONLY if originally present, use minimal AI flourish, and output ONLY the raw translation without preamble.{exclusion_str}\n\n<text_to_translate>\n{text}\n</text_to_translate>"

            current_usage = 0

            try:
                api_key = os.getenv("GEMINI_API_KEY")
                if not api_key:
                    raise ValueError("GEMINI_API_KEY not configured")

                def translate_text():
                    from cogs.utils.translator_algo import (
                        decide_translation_route,
                        perform_google_translate_fallback,
                        perform_gemini_translation,
                    )

                    model_choice = decide_translation_route(text, current_usage)

                    if model_choice == "googletrans":
                        result = perform_google_translate_fallback(text, target)
                        if not result:
                            raise ValueError(
                                "Google Translate service temporarily unavailable. Please try again in a moment."
                            )
                        return result

                    client = genai.Client(api_key=api_key)
                    return perform_gemini_translation(
                        client, model_choice, prompt, text, target
                    )

                translation = await asyncio.to_thread(translate_text)
                if not translation:
                    raise ValueError("Empty response from translation service")
                translation = translation.strip()

                embed = discord.Embed(
                    title=f"🌍 Translated to {target.capitalize()}",
                    description=translation,
                    color=discord.Color.green(),
                )
                embed.set_author(
                    name=message.author.display_name,
                    icon_url=(
                        message.author.display_avatar.url
                        if message.author.display_avatar
                        else None
                    ),
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception as e:
                import traceback

                traceback.print_exc()
                error_msg = str(e)

                # Handle specific error cases
                if "403" in error_msg or "PERMISSION_DENIED" in error_msg:
                    await interaction.followup.send(
                        "❌ Translation failed - API key issue. Check your GEMINI_API_KEY and ensure it has proper access.",
                        ephemeral=True,
                    )
                elif (
                    "503" in error_msg
                    or "service unavailable" in error_msg.lower()
                    or "temporarily unavailable" in error_msg.lower()
                ):
                    await interaction.followup.send(
                        "⏳ Translation service is temporarily unavailable (503). Please try again in a few seconds.",
                        ephemeral=True,
                    )
                elif "quota" in error_msg.lower() or "rate limit" in error_msg.lower():
                    await interaction.followup.send(
                        "⚠️ Translation quota exceeded. Please try again later.",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        f"❌ Translation failed. Please try again. ({error_msg[:40]})",
                        ephemeral=True,
                    )
        else:
            # Fallback: Open a modal to ask for language
            await interaction.response.send_modal(TranslateModal(message, self.bot))

    async def cog_load(self):
        from cogs.utils.ui import PersistentLanguageView

        self.bot.add_view(PersistentLanguageView(self.bot))
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    @commands.hybrid_command(
        aliases=["qt"],
        description="Instantly translates the provided text into the target language.",
    )
    @app_commands.describe(
        target_language="The language to translate into",
        text_to_translate="The text you want to translate",
    )
    async def qtranslate(
        self, ctx, target_language: str = None, *, text_to_translate: str = None
    ):
        """Instantly translates the provided text into the target language."""
        if not target_language or not text_to_translate:
            return await ctx.send(
                "❌ Usage: `!qtranslate <Language> <Text...>`\nExample: `!qtranslate Spanish That clutch was insane!`"
            )

        from cogs.utils.ui import LANGUAGES

        valid_langs = {}
        for key, data in LANGUAGES.items():
            if key == "Off":
                continue
            valid_langs[key.lower()] = key
            if "code" in data:
                valid_langs[data["code"].lower()] = key

        if target_language.lower() not in valid_langs:
            return await ctx.send(
                f'❌ "{target_language}" isn\'t a valid translation choice, unless you speak Elvish or Klingon! Please stick to Earth languages.'
            )
        target_language = valid_langs[target_language.lower()]

        # Indicate the bot is "typing" while it fetches the API
        async with ctx.typing():
            try:
                try:
                    exclusion_list = await self.bot.db.smembers(
                        "translator_exclusion_keywords"
                    )
                except Exception:
                    exclusion_list = []
                exclusion_str = ""
                if exclusion_list:
                    words = ", ".join([f"'{w}'" for w in exclusion_list])
                    exclusion_str = f" CRITICAL INSTRUCTION: Do NOT translate or alter these specific keywords under any circumstances: {words}."

                prompt = f"Translate the text enclosed in <text_to_translate> tags to {target_language}. Be strict about literal and accurate translations. Do not use overly conversational slang if the original text is standard (e.g., translate 'hello' as 'hello', not 'sup'). Maintain gamer slang ONLY if originally present, use minimal AI flourish, and output ONLY the raw translation without preamble.{exclusion_str}\n\n<text_to_translate>\n{text_to_translate}\n</text_to_translate>"

                current_usage = 0

                try:
                    api_key = os.getenv("GEMINI_API_KEY")
                    if not api_key:
                        raise ValueError(
                            "GEMINI_API_KEY environment variable is not set"
                        )

                    def translate_text():
                        from cogs.utils.translator_algo import (
                            decide_translation_route,
                            perform_google_translate_fallback,
                            perform_gemini_translation,
                        )

                        model_choice = decide_translation_route(
                            text_to_translate, current_usage
                        )

                        if model_choice == "googletrans":
                            result = perform_google_translate_fallback(
                                text_to_translate, target_language
                            )
                            if not result:
                                raise ValueError(
                                    "Google Translate service temporarily unavailable. Please try again in a moment."
                                )
                            return result

                        client = genai.Client(api_key=api_key)
                        return perform_gemini_translation(
                            client,
                            model_choice,
                            prompt,
                            text_to_translate,
                            target_language,
                        )

                    translation = await asyncio.to_thread(translate_text)
                    if not translation:
                        raise ValueError("Empty response from translation service")
                    translation = translation.strip()
                except Exception as api_err:
                    import traceback

                    traceback.print_exc()
                    raise api_err

                await ctx.send(f"🌍 **{target_language.capitalize()}:** {translation}")

            except Exception as e:
                import traceback

                traceback.print_exc()
                error_msg = str(e)

                # Handle specific error cases
                if "403" in error_msg or "PERMISSION_DENIED" in error_msg:
                    await ctx.send(
                        "❌ Translation failed - API key issue. Check your GEMINI_API_KEY and ensure it has proper access."
                    )
                elif (
                    "503" in error_msg
                    or "service unavailable" in error_msg.lower()
                    or "temporarily unavailable" in error_msg.lower()
                ):
                    await ctx.send(
                        "⏳ Translation service is temporarily unavailable (503). Please try again in a few seconds."
                    )
                elif "quota" in error_msg.lower() or "rate limit" in error_msg.lower():
                    await ctx.send(
                        "⚠️ Translation quota exceeded. Please try again later."
                    )
                else:
                    await ctx.send(
                        f"❌ Quick Translation failed. Please try again later. ({error_msg[:50]})"
                    )

    @commands.hybrid_command()
    async def translate(self, ctx, *, target: str = None):
        """Configure background auto-translation into your DMs via dropdown or language code."""
        from cogs.utils.ui import LanguageDropdown, LANGUAGES

        member = None
        language = None

        if target:
            if target.lower() == "off":
                language = "Off"
            else:
                try:
                    member_converter = commands.MemberConverter()
                    member = await member_converter.convert(ctx, target.split()[0])
                except commands.MemberNotFound:
                    # Not a member, try resolving as a language
                    valid_langs = {}
                    for key, data in LANGUAGES.items():
                        if key == "Off":
                            continue
                        valid_langs[key.lower()] = key
                        if "code" in data:
                            valid_langs[data["code"].lower()] = key

                    if target.lower() in valid_langs:
                        language = valid_langs[target.lower()]
                    else:
                        return await ctx.send(
                            f"❌ Could not find member or language '{target}'."
                        )

        if member and member.id != ctx.author.id:
            if not ctx.author.guild_permissions.administrator:
                return await ctx.send(
                    "❌ You need Administrator permissions to configure translations for another user."
                )
            target_id = member.id
            embed = discord.Embed(
                title=f"🌍 Configure Translation for {member.display_name}",
                description=f"Select the preferred language for {member.mention}.",
                color=discord.Color.blue(),
            )
        else:
            target_id = ctx.author.id
            if language:
                if language == "Off":
                    try:
                        await self.bot.db.sadd(
                            f"auto_translate_optout:{ctx.guild.id}", str(target_id)
                        )
                    except Exception:
                        pass
                    return await ctx.send(
                        "✅ Background auto-translation has been **disabled** for you. (On-demand UI translations will still use your last chosen language)"
                    )
                else:
                    try:
                        await self.bot.db.srem(
                            f"auto_translate_optout:{ctx.guild.id}", str(target_id)
                        )
                        await self.bot.db.hset(
                            f"translator_subs:{ctx.guild.id}", str(target_id), language
                        )
                    except Exception:
                        pass
                    return await ctx.send(
                        f"✅ Your background auto-translation language has been set to **{language}**.\nMessages in translation channels will be direct messaged to you in {language}."
                    )

            embed = discord.Embed(
                title="🌍 Translation Setup",
                description="Select your preferred language from the dropdown below to receive auto-translated DMs.\nNote: You can also use this dropdown to disable auto-translations.",
                color=discord.Color.blue(),
            )

        view = discord.ui.View()
        # Ephemeral view doesn't necessarily need a custom id, but we supply suffix to be safe.
        view.add_item(LanguageDropdown(self.bot, target_user_id=target_id))

        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command()
    @commands.has_permissions(administrator=True)
    async def spawntranslator(self, ctx):
        """Spawns a persistent dropdown menu for users to self-assign their translation language."""
        from cogs.utils.ui import PersistentLanguageView

        embed = discord.Embed(
            title="🌍 Auto-Translation Setup",
            description="Select your preferred language from the dropdown below or disable auto-translations altogether.\n\nWhenever someone sends a message in a supported channel, it will be automatically translated and sent directly to your DMs!",
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed, view=PersistentLanguageView(self.bot))

    @commands.hybrid_command()
    @commands.has_permissions(administrator=True)
    async def addtranschannel(self, ctx, channel: discord.TextChannel = None):
        """Allow auto-translations in a specific channel."""
        if not channel:
            return await ctx.send("❌ Usage: `!addtranschannel #channel`")
        await self.bot.db.sadd(f"translation_channels:{ctx.guild.id}", str(channel.id))
        await ctx.send(
            f"✅ Auto-translation has been **enabled** for {channel.mention}."
        )

    @commands.hybrid_command()
    @commands.has_permissions(administrator=True)
    async def removetranschannel(self, ctx, channel: discord.TextChannel = None):
        """Disallow auto-translations in a specific channel."""
        if not channel:
            return await ctx.send("❌ Usage: `!removetranschannel #channel`")
        deleted = await self.bot.db.srem(
            f"translation_channels:{ctx.guild.id}", str(channel.id)
        )
        if deleted:
            await ctx.send(
                f"✅ Auto-translation has been **disabled** for {channel.mention}."
            )
        else:
            await ctx.send(
                f"⚠️ {channel.mention} is not currently in the translation allowlist."
            )

    @commands.hybrid_command()
    @commands.has_permissions(administrator=True)
    async def transconfig(self, ctx):
        """Interactive dropdown menu to configure translation allowlisted channels."""
        current_channels = await self.bot.db.smembers(
            f"translation_channels:{ctx.guild.id}"
        )
        desc = "Use the dropdown menu below to select which text channels should allow auto-translation! Unselecting channels implicitly removes them."
        if current_channels:
            mentions = [f"<#{c}>" for c in current_channels]
            desc += "\n\n**Currently Active Channels:**\n" + "\n".join(mentions)

        embed = discord.Embed(
            title="🌍 Translation Channel Configuration",
            description=desc,
            color=discord.Color.blue(),
        )
        await ctx.send(embed=embed, view=TransConfigView(self.bot))

    @commands.hybrid_command(aliases=["toggleauto", "autotoggle"])
    @commands.has_permissions(administrator=True)
    async def toggle_auto_translator(self, ctx):
        """Admin command to toggle the Auto-Translator on or off for this server."""
        disabled = await self.bot.db.get(f"auto_translator_disabled:{ctx.guild.id}")
        if disabled == "1":
            await self.bot.db.delete(f"auto_translator_disabled:{ctx.guild.id}")
            await ctx.send(
                "✅ The Background Auto-Translator is now **ENABLED** for this server."
            )
        else:
            await self.bot.db.set(f"auto_translator_disabled:{ctx.guild.id}", "1")
            await ctx.send(
                "🚫 The Background Auto-Translator is now **DISABLED** for this server."
            )


async def setup(bot):
    await bot.add_cog(QuickTranslator(bot))
