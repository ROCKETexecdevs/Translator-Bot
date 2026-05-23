import discord
import re

LANGUAGES = {
    "English": {"native": "English", "code": "EN", "emoji": "🇺🇸"},
    "Spanish": {"native": "Español", "code": "ES", "emoji": "🇪🇸"},
    "French": {"native": "Français", "code": "FR", "emoji": "🇫🇷"},
    "German": {"native": "Deutsch", "code": "DE", "emoji": "🇩🇪"},
    "Italian": {"native": "Italiano", "code": "IT", "emoji": "🇮🇹"},
    "Portuguese": {"native": "Português", "code": "PT", "emoji": "🇵🇹"},
    "Russian": {"native": "Русский", "code": "RU", "emoji": "🇷🇺"},
    "Japanese": {"native": "日本語", "code": "JA", "emoji": "🇯🇵"},
    "Korean": {"native": "한국어", "code": "KO", "emoji": "🇰🇷"},
    "Chinese Simplified": {"native": "简体中文", "code": "ZH", "emoji": "🇨🇳"},
    "Chinese Traditional": {"native": "繁體中文", "code": "TW", "emoji": "🇹🇼"},
    "Cantonese": {"native": "粵語", "code": "YUE", "emoji": "🇭🇰"},
    "Arabic": {"native": "العربية", "code": "AR", "emoji": "🇸🇦"},
    "Hindi": {"native": "हिन्दी", "code": "HI", "emoji": "🇮🇳"},
    "Turkish": {"native": "Türkçe", "code": "TR", "emoji": "🇹🇷"},
    "Dutch": {"native": "Nederlands", "code": "NL", "emoji": "🇳🇱"},
    "Polish": {"native": "Polski", "code": "PL", "emoji": "🇵🇱"},
    "Indonesian": {"native": "Bahasa Indonesia", "code": "ID", "emoji": "🇮🇩"},
    "Vietnamese": {"native": "Tiếng Việt", "code": "VI", "emoji": "🇻🇳"},
    "Thai": {"native": "ไทย", "code": "TH", "emoji": "🇹🇭"},
    "Tagalog": {"native": "Tagalog", "code": "TL", "emoji": "🇵🇭"},
    "Swedish": {"native": "Svenska", "code": "SV", "emoji": "🇸🇪"},
    "Ukrainian": {"native": "Українська", "code": "UK", "emoji": "🇺🇦"},
    "Greek": {"native": "Ελληνικά", "code": "EL", "emoji": "🇬🇷"},
    "Romanian": {"native": "Română", "code": "RO", "emoji": "🇷🇴"},
    "Off": {"native": "Disable auto-translations", "code": "", "emoji": "❌"},
}


class LanguageDropdown(discord.ui.Select):
    def __init__(self, bot, target_user_id: int = None, custom_id_suffix: str = ""):
        self.bot = bot
        self.target_user_id = target_user_id

        options = []
        for eng_name, data in LANGUAGES.items():
            desc = eng_name if eng_name != "Off" else "Turn off translations"
            options.append(
                discord.SelectOption(
                    label=data["native"],
                    value=eng_name,
                    description=desc,
                    emoji=data["emoji"],
                )
            )

        custom_id = "language_dropdown"
        if custom_id_suffix:
            custom_id = f"language_dropdown:{custom_id_suffix}"

        super().__init__(
            placeholder="Select your preferred language...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
            custom_id=custom_id,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # If this dropdown was spawned for a specific target user, ensure only they or the admin who spawned it can click it.
        # Actually, if target_user_id is set, it means the admin wants to change THAT user's language.
        # So we restrict interaction to the person who triggered the command (the admin).

        target_id = self.target_user_id if self.target_user_id else interaction.user.id

        if self.target_user_id:
            target_member = interaction.guild.get_member(target_id)
            if not target_member and interaction.guild:
                try:
                    target_member = await interaction.guild.fetch_member(target_id)
                except discord.HTTPException:
                    target_member = None
        else:
            target_member = interaction.user

        if not target_member:
            return await interaction.followup.send(
                "⚠️ The user to update could not be found in this server.",
                ephemeral=True,
            )

        selected_lang = self.values[0]

        if selected_lang == "Off":
            try:
                await self.bot.db.sadd(
                    f"auto_translate_optout:{interaction.guild_id}", str(target_id)
                )
            except Exception as e:
                print(e)
            await interaction.followup.send(
                f"📴 Background auto-translations disabled for {target_member.mention}. (On-demand UI translations will still use your last chosen language)",
                ephemeral=True,
            )
        else:
            try:
                await self.bot.db.srem(
                    f"auto_translate_optout:{interaction.guild_id}", str(target_id)
                )
                await self.bot.db.hset(
                    f"translator_subs:{interaction.guild_id}",
                    str(target_id),
                    selected_lang,
                )
            except Exception as e:
                print(e)

            # Update Nickname with Language Signifier
            lang_code = LANGUAGES[selected_lang]["code"]
            current_nick = target_member.display_name

            # Remove existing signifier like ' | EN' or ' (EN)'
            clean_nick = re.sub(r"\s*\|\s*[A-Z]{2}$", "", current_nick)
            clean_nick = re.sub(r"\s*\([A-Z]{2}\)$", "", clean_nick)

            new_nick = f"{clean_nick} | {lang_code}"

            # Ensure it's under 32 chars
            if len(new_nick) > 32:
                # Truncate clean_nick so the whole thing fits
                clean_nick = clean_nick[: 32 - len(f" | {lang_code}")]
                new_nick = f"{clean_nick} | {lang_code}"

            try:
                await target_member.edit(
                    nick=new_nick, reason="Language Setting Update"
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    f"✅ Language set to **{LANGUAGES[selected_lang]['native']}** for {target_member.mention}! (Could not update nickname due to permissions.)",
                    ephemeral=True,
                )
                return

            await interaction.followup.send(
                f"✅ Language set to **{LANGUAGES[selected_lang]['native']}** for {target_member.mention}!",
                ephemeral=True,
            )


class PersistentLanguageView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.add_item(LanguageDropdown(bot, custom_id_suffix="persistent"))
