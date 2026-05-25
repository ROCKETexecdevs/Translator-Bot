import discord
from discord.ext import commands
from discord import app_commands
from cogs.utils.views import TranslatedView
from types import SimpleNamespace

# Friendly metadata for the bot's cogs
COG_METADATA = {
    "QuickTranslator": {
        "name": "Translation Engine",
        "emoji": "🌍",
        "desc": "Commands for auto-translating server messages, configuring language channels, and self-assigning language roles."
    },
    "Moderation": {
        "name": "Moderation Tools",
        "emoji": "🛡️",
        "desc": "Server policing commands: timeout/mute, kick, ban, purge chat, lock channels, and manage user nicknames."
    },
    "Admin": {
        "name": "Administration & Core",
        "emoji": "⚙️",
        "desc": "High-clearance suite for toggling commands/cogs on the fly, hot-reloading extensions, and global command syncing."
    },
    "GlobalChat": {
        "name": "Global Chat",
        "emoji": "💬",
        "desc": "Synchronize text channels across different Discord servers seamlessly."
    }
}


def get_command_permissions(command):
    perms = []
    for check in command.checks:
        name = check.__qualname__
        if "has_permissions" in name:
            try:
                closure = check.__closure__
                if closure:
                    for cell in closure:
                        contents = cell.cell_contents
                        if isinstance(contents, dict):
                            for perm, val in contents.items():
                                if val:
                                    perms.append(perm.replace("_", " ").title())
            except Exception:
                pass
        elif "is_owner" in name:
            perms.append("Bot Owner Only")
            
    if not perms:
        return "Everyone"
    return ", ".join(perms)


def get_main_embed(bot, ctx):
    embed = discord.Embed(
        title="🌍 Translator-Bot Help Center",
        description=(
            "Welcome to the Translation & Moderation help center. "
            "This bot supports hybrid command execution—you can run commands as slash commands (e.g., `/qtranslate`) "
            "or prefix commands (e.g., `!qtranslate`).\n\n"
            "Select a category from the dropdown menu below to view specific commands."
        ),
        color=0x7a2dec
    )
    if bot.user and bot.user.display_avatar:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
        
    embed.add_field(
        name="💡 Quick Tip",
        value="To view detailed help for a specific command, use `/help command:<name>` or `!help <name>`.",
        inline=False
    )
    
    # List categories dynamically
    categories_text = ""
    for cog_name, cog in bot.cogs.items():
        if cog_name == "Help":
            continue
            
        # Check visible commands
        visible_cmds = []
        for cmd in cog.get_commands():
            if cmd.hidden and not ctx.author.guild_permissions.administrator:
                continue
            visible_cmds.append(cmd)
            
        if not visible_cmds:
            continue
            
        meta = COG_METADATA.get(cog_name, {
            "name": cog_name,
            "emoji": "📁",
            "desc": cog.__doc__ or f"Commands from {cog_name}."
        })
        
        categories_text += f"{meta['emoji']} **{meta['name']}** ({len(visible_cmds)} commands)\n*{meta['desc']}*\n\n"
        
    if categories_text:
        embed.add_field(name="📌 Available Modules", value=categories_text, inline=False)
        
    embed.set_footer(text="Select a category dropdown to navigate.")
    return embed


async def get_cog_embed(bot, cog, ctx):
    meta = COG_METADATA.get(cog.qualified_name, {
        "name": cog.qualified_name,
        "emoji": "📁",
        "desc": cog.__doc__ or f"Commands from {cog.qualified_name}."
    })
    
    embed = discord.Embed(
        title=f"{meta['emoji']} {meta['name']}",
        description=meta['desc'],
        color=0x7a2dec
    )
    
    visible_cmds = []
    for cmd in cog.get_commands():
        if cmd.hidden and not ctx.author.guild_permissions.administrator:
            continue
        visible_cmds.append(cmd)
        
    for cmd in visible_cmds:
        disabled_label = ""
        if ctx.guild:
            try:
                is_disabled = await bot.db.get(f"cmd_disabled:{ctx.guild.id}:{cmd.name}")
                if is_disabled == "1":
                    disabled_label = " 🚫 *[DISABLED on this server]*"
            except Exception:
                pass
                
        aliases = f" | Aliases: `{(', '.join(cmd.aliases))}`" if cmd.aliases else ""
        signature = f" {cmd.signature}" if cmd.signature else ""
        perms = get_command_permissions(cmd)
        
        doc = cmd.help or cmd.description or "No description provided."
        if len(doc) > 150:
            doc = doc[:147] + "..."
            
        field_value = (
            f"**Usage:** `!{cmd.qualified_name}{signature}` or `/{cmd.qualified_name}`\n"
            f"**Clearance:** `{perms}`{disabled_label}\n"
            f"*{doc}*"
        )
        
        name_str = f"/{cmd.qualified_name}"
        if cmd.aliases:
            name_str += f" (or !{cmd.aliases[0]})"
            
        embed.add_field(
            name=f"🔹 {name_str}",
            value=field_value,
            inline=False
        )
        
    embed.set_footer(text=f"Total: {len(visible_cmds)} commands | Select dropdown to switch.")
    return embed


async def get_command_embed(bot, command, ctx):
    embed = discord.Embed(
        title=f"🔍 Command: /{command.qualified_name}",
        color=0x7a2dec
    )
    
    doc = command.help or command.description or "No description provided."
    embed.description = doc
    
    prefix_syntax = f"`!{command.qualified_name} {command.signature}`" if command.signature else f"`!{command.qualified_name}`"
    slash_syntax = f"`/{command.qualified_name}`"
    
    embed.add_field(name="⌨️ Prefix Syntax", value=prefix_syntax, inline=True)
    embed.add_field(name="⚡ Slash Syntax", value=slash_syntax, inline=True)
    
    if command.aliases:
        embed.add_field(name="🏷️ Aliases", value=", ".join([f"`!{a}`" for a in command.aliases]), inline=False)
        
    perms = get_command_permissions(command)
    embed.add_field(name="🔒 Clearance Required", value=f"`{perms}`", inline=True)
    
    if ctx.guild:
        try:
            is_disabled = await bot.db.get(f"cmd_disabled:{ctx.guild.id}:{command.name}")
            status = "🚫 Disabled" if is_disabled == "1" else "✅ Active"
            embed.add_field(name="⚙️ Server Status", value=f"**{status}**", inline=True)
        except Exception:
            pass
            
    if command.cog:
        cog_meta = COG_METADATA.get(command.cog.qualified_name, {"name": command.cog.qualified_name})
        embed.add_field(name="📁 Module", value=cog_meta["name"], inline=True)
        
    if isinstance(command, commands.Group):
        subcmds = []
        for sub in command.commands:
            if sub.hidden and not ctx.author.guild_permissions.administrator:
                continue
            subcmds.append(f"`{sub.name}` - {sub.short_doc or 'No description.'}")
        if subcmds:
            embed.add_field(name="📋 Subcommands", value="\n".join(subcmds), inline=False)
            
    return embed


class HelpSelect(discord.ui.Select):
    def __init__(self, bot):
        self.bot = bot
        
        options = [
            discord.SelectOption(
                label="Main Menu",
                value="main_menu",
                description="Return to the main help page",
                emoji="🏠"
            )
        ]
        
        for cog_name, cog in self.bot.cogs.items():
            if cog_name == "Help":
                continue
                
            visible_commands = []
            for cmd in cog.get_commands():
                if cmd.hidden:
                    continue
                visible_commands.append(cmd)
                
            if not visible_commands:
                continue
                
            meta = COG_METADATA.get(
                cog_name,
                {"name": cog_name, "emoji": "📁", "desc": cog.__doc__ or f"Commands from {cog_name}."}
            )
            
            desc = meta.get("desc", "")
            if desc and len(desc) > 100:
                desc = desc[:97] + "..."
                
            options.append(
                discord.SelectOption(
                    label=meta["name"],
                    value=cog_name,
                    description=desc or "No description",
                    emoji=meta["emoji"]
                )
            )
            
        super().__init__(
            placeholder="Select a category...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="help_select_dropdown"
        )
        
    async def callback(self, interaction: discord.Interaction):
        ctx_like = SimpleNamespace(author=interaction.user, guild=interaction.guild)

        value = self.values[0]
        if value == "main_menu":
            embed = get_main_embed(self.bot, ctx_like)
            await self.view.edit_translated(interaction, embed=embed)
        else:
            cog = self.bot.get_cog(value)
            if not cog:
                return await interaction.response.send_message(
                    "❌ That category is no longer loaded.",
                    ephemeral=True
                )
            embed = await get_cog_embed(self.bot, cog, ctx_like)
            await self.view.edit_translated(interaction, embed=embed)


class HelpDropdownView(TranslatedView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(HelpSelect(bot))


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # Re-register persistent dropdown handlers so existing help embeds keep working.
        self.bot.add_view(HelpDropdownView(self.bot))
        
    @commands.hybrid_command(
        name="help",
        description="Display information on available commands and modules."
    )
    @app_commands.describe(
        command="The specific command you want detailed help with"
    )
    async def help_command(self, ctx, *, command: str = None):
        """Displays help for the bot's commands and modules dynamically."""
        if command:
            cmd = self.bot.get_command(command)
            if not cmd or (cmd.hidden and not ctx.author.guild_permissions.administrator):
                return await ctx.send(f"❌ Command `{command}` not found.")
                
            embed = await get_command_embed(self.bot, cmd, ctx)
            await ctx.send(embed=embed)
        else:
            embed = get_main_embed(self.bot, ctx)
            view = HelpDropdownView(self.bot)
            await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(
        name="sethelp",
        description="Post or move the persistent help embed to a selected channel (admins only)."
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(channel="Channel where the persistent help embed should be posted")
    async def set_help_embed(self, ctx, channel: discord.TextChannel = None):
        """Creates or moves a server-managed help embed message to the target channel."""
        target_channel = channel or ctx.channel
        guild_id = ctx.guild.id

        old_channel_id = await self.bot.db.get(f"help_embed_channel:{guild_id}")
        old_message_id = await self.bot.db.get(f"help_embed_message:{guild_id}")

        if old_channel_id and old_message_id:
            try:
                old_channel = ctx.guild.get_channel(int(old_channel_id))
                if old_channel is not None:
                    old_message = await old_channel.fetch_message(int(old_message_id))
                    await old_message.delete()
            except Exception:
                pass

        embed = get_main_embed(self.bot, ctx)
        embed.add_field(
            name="📘 Need More Details?",
            value="Use `/help` or `!help` to open the interactive help menu.",
            inline=False,
        )

        posted = await target_channel.send(embed=embed, view=HelpDropdownView(self.bot))

        pinned = False
        try:
            await posted.pin(reason=f"Persistent help embed set by {ctx.author}")
            pinned = True
        except Exception:
            pinned = False

        await self.bot.db.set(f"help_embed_channel:{guild_id}", str(target_channel.id))
        await self.bot.db.set(f"help_embed_message:{guild_id}", str(posted.id))

        pin_note = " and pinned" if pinned else ""
        await ctx.send(
            f"✅ Persistent help embed posted in {target_channel.mention}{pin_note}."
        )


async def setup(bot):
    await bot.add_cog(Help(bot))
