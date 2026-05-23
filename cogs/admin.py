import discord
from discord.ext import commands
import sys
import datetime
from cogs.utils.views import TranslatedView


class AdminConfirmView(TranslatedView):
    def __init__(self, ctx, action_name: str, callback_coro):
        super().__init__(timeout=30.0)
        self.ctx = ctx
        self.action_name = action_name
        self.callback_coro = callback_coro

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if interaction.user != self.ctx.author:
            return await self.send_translated(
                interaction, content="You cannot confirm this action.", ephemeral=True
            )
        for child in self.children:
            child.disabled = True
        try:
            await interaction.response.edit_message(
                content=f"Confirmed {self.action_name}.", view=self
            )
        except discord.HTTPException:
            pass
        self.stop()
        await self.callback_coro()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await self.send_translated(
                interaction, content="You cannot cancel this action.", ephemeral=True
            )
        for child in self.children:
            child.disabled = True
        try:
            await interaction.response.edit_message(
                content=f"Cancelled {self.action_name}.", view=self
            )
        except discord.HTTPException:
            pass
        self.stop()


# --- Modals for the Admin Suite ---


class ModActionModal(discord.ui.Modal):
    user_id = discord.ui.TextInput(
        label="Target User ID", placeholder="e.g. 123456789012345678", required=True
    )
    reason = discord.ui.TextInput(
        label="Reason (Optional)", style=discord.TextStyle.paragraph, required=False
    )

    def __init__(self, bot, action_type):
        action_map = {
            "mod_kick": "Kick User",
            "mod_ban": "Ban User",
            "mod_unmute": "Remove Time-out",
        }
        super().__init__(title=action_map.get(action_type, "Action"))
        self.bot = bot
        self.action_type = action_type

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            target_id = int(self.user_id.value.strip())
            member = interaction.guild.get_member(target_id)
            if not member:
                # If banning, we can ban by fetch_user. Otherwise we need them in guild.
                if self.action_type == "mod_ban":
                    user = await self.bot.fetch_user(target_id)
                    await interaction.guild.ban(user, reason=self.reason.value)
                    return await interaction.followup.send(
                        f"✅ Banned **{user.name}**."
                    )
                return await interaction.followup.send(
                    "❌ Error: Could not find user in the server via that ID."
                )

            if self.action_type == "mod_kick":
                await member.kick(reason=self.reason.value)
                await interaction.followup.send(f"✅ Kicked **{member.display_name}**.")
            elif self.action_type == "mod_ban":
                await member.ban(reason=self.reason.value)
                await interaction.followup.send(f"✅ Banned **{member.display_name}**.")
            elif self.action_type == "mod_unmute":
                await member.timeout(None, reason="Unmuted via Mod Panel")
                await interaction.followup.send(
                    f"🔊 Removed time-out from **{member.display_name}**."
                )
        except ValueError:
            await interaction.followup.send("❌ User ID must be a number.")
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Permission Denied. My role is likely underneath theirs."
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")


class MuteModal(discord.ui.Modal, title="Time-out User"):
    user_id = discord.ui.TextInput(label="Target User ID", required=True)
    minutes = discord.ui.TextInput(
        label="Duration (Minutes)", placeholder="e.g. 60", required=True
    )
    reason = discord.ui.TextInput(label="Reason (Optional)", required=False)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            member = interaction.guild.get_member(int(self.user_id.value.strip()))
            if not member:
                return await interaction.followup.send(
                    "❌ Target user not found in the server."
                )
            duration = datetime.timedelta(minutes=int(self.minutes.value.strip()))
            await member.timeout(duration, reason=self.reason.value)
            await interaction.followup.send(
                f"🔇 Timed out **{member.display_name}** for {self.minutes.value} mins."
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Permission Denied.")
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")


class ForceNameModal(discord.ui.Modal, title="Force Update Nickname"):
    user_id = discord.ui.TextInput(label="Target User ID", required=True)
    new_name = discord.ui.TextInput(label="New Nickname", required=True, max_length=32)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            member = interaction.guild.get_member(int(self.user_id.value.strip()))
            if not member:
                return await interaction.followup.send(
                    "❌ Target user not found in the server."
                )
            await member.edit(nick=self.new_name.value.strip())
            await interaction.followup.send(
                f"🏷️ Nickname for the user updated to **{self.new_name.value}**."
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Permission Denied to change nickname.")


class PurgeModal(discord.ui.Modal, title="Purge Messages"):
    amount = discord.ui.TextInput(
        label="Number of Messages (1-500)", placeholder="e.g. 50", required=True
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            count = int(self.amount.value.strip())
            if count < 1 or count > 500:
                return await interaction.followup.send("❌ Must be between 1 and 500.")
            deleted = await interaction.channel.purge(limit=count)
            await interaction.followup.send(
                f"🧹 Purged **{len(deleted)}** messages from the channel."
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")


# --- Admin View Dashboard ---


class AdminSuiteView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.select(
        placeholder="🔨 Select Moderation Action...",
        options=[
            discord.SelectOption(label="Kick User", value="mod_kick", emoji="👢"),
            discord.SelectOption(label="Ban User", value="mod_ban", emoji="🔨"),
            discord.SelectOption(label="Time-out User", value="mod_mute", emoji="🔇"),
            discord.SelectOption(
                label="Remove Time-out", value="mod_unmute", emoji="🔊"
            ),
            discord.SelectOption(
                label="Force Nickname", value="mod_forcename", emoji="🏷️"
            ),
        ],
        custom_id="admin_mod_select",
        row=0,
    )
    async def mod_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "❌ Admin strictly required.", ephemeral=True
            )

        val = select.values[0]
        if val in ["mod_kick", "mod_ban", "mod_unmute"]:
            await interaction.response.send_modal(ModActionModal(self.bot, val))
        elif val == "mod_mute":
            await interaction.response.send_modal(MuteModal(self.bot))
        elif val == "mod_forcename":
            await interaction.response.send_modal(ForceNameModal(self.bot))

    @discord.ui.select(
        placeholder="🛡️ Select Channel Action...",
        options=[
            discord.SelectOption(
                label="Purge Messages", value="chan_purge", emoji="🧹"
            ),
            discord.SelectOption(label="Lock Channel", value="chan_lock", emoji="🔒"),
            discord.SelectOption(
                label="Unlock Channel", value="chan_unlock", emoji="🔓"
            ),
        ],
        custom_id="admin_chan_select",
        row=1,
    )
    async def chan_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "❌ Admin strictly required.", ephemeral=True
            )

        val = select.values[0]
        if val == "chan_purge":
            await interaction.response.send_modal(PurgeModal(self.bot))
        elif val == "chan_lock":
            try:
                await interaction.channel.set_permissions(
                    interaction.guild.default_role, send_messages=False
                )
                await interaction.response.send_message(
                    "🔒 **Channel Locked.** @everyone can no longer text.",
                    ephemeral=False,
                )
            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ Missing Permissions.", ephemeral=True
                )
        elif val == "chan_unlock":
            try:
                await interaction.channel.set_permissions(
                    interaction.guild.default_role, send_messages=None
                )
                await interaction.response.send_message(
                    "🔓 **Channel Unlocked.**", ephemeral=False
                )
            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ Missing Permissions.", ephemeral=True
                )

    @discord.ui.button(
        label="Restart Bot",
        style=discord.ButtonStyle.danger,
        emoji="🔄",
        row=2,
        custom_id="admin_btn_restart",
    )
    async def restart_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not interaction.user.guild_permissions.administrator:
            return
        await interaction.response.send_message(
            "🔄 Force Restarting Engine...", ephemeral=False
        )
        sys.exit(0)

    @discord.ui.button(
        label="Sync Global",
        style=discord.ButtonStyle.primary,
        emoji="♻️",
        row=2,
        custom_id="admin_btn_sync",
    )
    async def sync_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not interaction.user.guild_permissions.administrator:
            return
        await interaction.response.defer(ephemeral=True)
        synced = await self.bot.tree.sync(guild=interaction.guild)
        self.bot.tree.copy_global_to(guild=interaction.guild)
        synced = await self.bot.tree.sync(guild=interaction.guild)
        await interaction.followup.send(
            f"✅ Fast-Synced **{len(synced)}** app commands natively bypassing global cache."
        )

    @discord.ui.button(
        label="Toggle Invisible",
        style=discord.ButtonStyle.secondary,
        emoji="👻",
        row=2,
        custom_id="admin_btn_invis",
    )
    async def invis_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not interaction.user.guild_permissions.administrator:
            return
        is_invisible = await self.bot.db.get("kingbot_global_invisible")
        if is_invisible == "1":
            await self.bot.db.delete("kingbot_global_invisible")
            await self.bot.change_presence(status=discord.Status.online)
            await interaction.response.send_message(
                "👁️ KingBot is now globally visible.", ephemeral=False
            )
        else:
            await self.bot.db.set("kingbot_global_invisible", "1")
            await self.bot.change_presence(status=discord.Status.invisible)
            await interaction.response.send_message(
                "👻 KingBot is now historically cloaked across all shards.",
                ephemeral=False,
            )


# --- Engine Cog ---


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _is_allowed_extension(self, extension: str) -> bool:
        allowed = getattr(self.bot, "allowed_cog_extensions", set())
        return f"cogs.{extension}" in allowed

    @commands.hybrid_command(name="control_panel", aliases=["admin_suite", "cpanel"])
    @commands.has_permissions(administrator=True)
    async def control_panel(self, ctx):
        """Summons the Master Admin Control Panel."""
        embed = discord.Embed(
            title="⚙️ KingBot Master Control Panel",
            description="Utilize the dropdowns to effortlessly moderate users and police the channel, or use the execution buttons to hot-swap infrastructure.\n\n"
            "*(All legacy text commands are still actively supported).* ",
            color=discord.Color.dark_red(),
        )
        embed.set_footer(
            text="Requires High Administrator Clearance. Interactions logged securely."
        )
        await ctx.send(embed=embed, view=AdminSuiteView(self.bot))

    @commands.hybrid_command(name="restart", aliases=["reboot"], hidden=True)
    @commands.has_permissions(administrator=True)
    async def restart_bot(self, ctx):
        async def do_restart():
            await ctx.send("🔄 Restarting bot...")
            sys.exit(0)

        view = AdminConfirmView(ctx, "bot restart", do_restart)
        await ctx.send("Are you sure you want to restart the bot?", view=view)

    @commands.hybrid_command(name="reload", hidden=True)
    @commands.has_permissions(administrator=True)
    async def reload_cog(self, ctx, extension: str):
        if not self._is_allowed_extension(extension):
            return await ctx.send(
                f"❌ `cogs.{extension}` is outside the allowed Translator/Admin suite."
            )

        async def do_reload():
            try:
                await self.bot.reload_extension(f"cogs.{extension}")
                await ctx.send(f"✅ Successfully reloaded `cogs.{extension}`")
            except Exception as e:
                await ctx.send(f"❌ Failed to reload `cogs.{extension}`: {e}")

        view = AdminConfirmView(ctx, f"reload of cogs.{extension}", do_reload)
        await ctx.send(
            f"Are you sure you want to reload `cogs.{extension}`?", view=view
        )

    @commands.hybrid_command(name="load", hidden=True)
    @commands.has_permissions(administrator=True)
    async def load_cog(self, ctx, extension: str):
        if not self._is_allowed_extension(extension):
            return await ctx.send(
                f"❌ `cogs.{extension}` is outside the allowed Translator/Admin suite."
            )

        async def do_load():
            try:
                await self.bot.load_extension(f"cogs.{extension}")
                await ctx.send(f"✅ Successfully loaded `cogs.{extension}`")
            except Exception as e:
                import traceback
                error_trace = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                await ctx.send(f"❌ Failed to load `cogs.{extension}`: {e}\n```py\n{error_trace[:1900]}\n```")

        view = AdminConfirmView(ctx, f"load of cogs.{extension}", do_load)
        await ctx.send(
            f"Are you sure you want to load `cogs.{extension}`?", view=view
        )

    @commands.hybrid_command(name="sync", hidden=True)
    @commands.has_permissions(administrator=True)
    async def sync(self, ctx, spec: str = "*"):
        """Syncs the slash command tree.
        Syntax: !sync, !sync ~, !sync *, !sync ^
        Default uses * to copy globals into this guild and sync immediately.
        """
        try:
            if spec == "~":
                synced = await self.bot.tree.sync(guild=ctx.guild)
            elif spec == "*":
                self.bot.tree.copy_global_to(guild=ctx.guild)
                synced = await self.bot.tree.sync(guild=ctx.guild)
            elif spec == "^":
                self.bot.tree.clear_commands(guild=ctx.guild)
                await self.bot.tree.sync(guild=ctx.guild)
                synced = []
            else:
                synced = await self.bot.tree.sync()
            await ctx.send(
                f"✅ Synced {len(synced)} commands {'globally' if spec not in {'~', '*', '^'} else 'to the current guild' }."
            )
        except Exception as e:
            await ctx.send(f"❌ Failed to sync commands: {e}")

    @commands.hybrid_command(name="toggle_command", aliases=["toggle"])
    @commands.has_permissions(administrator=True)
    async def toggle_command(self, ctx, command_name: str = None):
        """Toggles any bot command to be Admin-only. Type '!toggle list' to see all disabled commands."""
        if not command_name:
            return await ctx.send(
                "❌ Usage: `!toggle <CommandName>` or `!toggle list`."
            )

        if command_name.lower() == "list":
            pattern = f"cmd_disabled:{ctx.guild.id}:*"
            keys = await self.bot.db.keys(pattern)
            if not keys:
                return await ctx.send(
                    "✅ There are currently no commands/cogs disabled in this server."
                )
            disabled_cmds = [
                f"`!{key.split(':')[2]}`" for key in keys if len(key.split(":")) >= 3
            ]
            embed = discord.Embed(
                title="🚫 Disabled Commands",
                description="\n".join(disabled_cmds),
                color=discord.Color.red(),
            )
            return await ctx.send(embed=embed)

        cmd = self.bot.get_command(command_name)
        if not cmd:
            return await ctx.send(
                f"❌ Could not find a command named `{command_name}`."
            )

        key = f"cmd_disabled:{ctx.guild.id}:{cmd.name}"
        is_disabled = await self.bot.db.get(key)
        if is_disabled:
            await self.bot.db.delete(key)
            await ctx.send(f"✅ **ENABLED**: The `{cmd.name}` command is now active and available.")
        else:
            await self.bot.db.set(key, "1")
            await ctx.send(f"🚫 **DISABLED**: The `{cmd.name}` command has been completely disabled on this server.")

    @commands.hybrid_command(name="toggle_cog", aliases=["togglecog"])
    @commands.has_permissions(administrator=True)
    async def toggle_cog(self, ctx, cog_name: str = None):
        """Toggles an entire cog on or off for this server."""
        if not cog_name:
            return await ctx.send("❌ Usage: `!togglecog <CogName>`")
        target_cog = next(
            (c for n, c in self.bot.cogs.items() if n.lower() == cog_name.lower()), None
        )
        if not target_cog:
            return await ctx.send(f"❌ Could not find module `{cog_name}`.")
        cmds = target_cog.get_commands()
        if not cmds:
            return await ctx.send("⚠️ No toggleable commands.")

        is_disabled = await self.bot.db.get(
            f"cmd_disabled:{ctx.guild.id}:{cmds[0].name}"
        )
        if is_disabled:
            for cmd in cmds:
                await self.bot.db.delete(f"cmd_disabled:{ctx.guild.id}:{cmd.name}")
            await self.bot.db.delete(
                f"cog_disabled:{ctx.guild.id}:{target_cog.qualified_name}"
            )
            await ctx.send(f"✅ **ENABLED**: The `{target_cog.qualified_name}` module is now active and available.")
        else:
            for cmd in cmds:
                await self.bot.db.set(f"cmd_disabled:{ctx.guild.id}:{cmd.name}", "1")
            await self.bot.db.set(
                f"cog_disabled:{ctx.guild.id}:{target_cog.qualified_name}", "1"
            )
            await ctx.send(f"🚫 **DISABLED**: The `{target_cog.qualified_name}` module has been completely disabled on this server.")

    @commands.hybrid_command(
        name="toggle_invisible", aliases=["invisible"], hidden=True
    )
    @commands.has_permissions(administrator=True)
    async def toggle_invisible(self, ctx):
        is_invisible = await self.bot.db.get("kingbot_global_invisible")
        if is_invisible == "1":
            await self.bot.db.delete("kingbot_global_invisible")
            await self.bot.change_presence(status=discord.Status.online)
            await ctx.send("👁️ **KingBot is now ONLINE globally.**")
        else:
            await self.bot.db.set("kingbot_global_invisible", "1")
            await self.bot.change_presence(status=discord.Status.invisible)
            await ctx.send("👻 **KingBot is now INVISIBLE globally.**")


async def setup(bot):
    await bot.add_cog(Admin(bot))
