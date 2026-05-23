import discord
from discord.ext import commands


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command()
    @commands.has_permissions(administrator=True)
    async def purge(self, ctx, amount: int = None):
        """Purges a specified number of recent messages in the channel."""
        if not amount or amount < 1 or amount > 500:
            return await ctx.send("❌ Usage: `!purge <number between 1 and 500>`")

        await ctx.channel.purge(limit=amount + 1)
        resp = await ctx.send(f"✅ Purged **{amount}** messages.")
        await resp.delete(delay=3)

    @commands.hybrid_command()
    @commands.has_permissions(administrator=True)
    async def kick(self, ctx, member: discord.Member = None, *, reason: str = None):
        """Kicks a user from the server."""
        if not member:
            return await ctx.send("❌ Usage: `!kick @user [Reason]`")
        try:
            await member.kick(reason=reason)
            await ctx.send(
                f"✅ Kicked **{member.display_name}**. Reason: {reason or 'No reason provided.'}"
            )
        except discord.Forbidden:
            await ctx.send(
                "❌ I don't have permission to kick this user (They might have a higher role than me)."
            )

    @commands.hybrid_command()
    @commands.has_permissions(administrator=True)
    async def ban(self, ctx, member: discord.Member = None, *, reason: str = None):
        """Bans a user from the server."""
        if not member:
            return await ctx.send("❌ Usage: `!ban @user [Reason]`")
        try:
            await member.ban(reason=reason)
            embed = discord.Embed(
                title="🔨 User Banned",
                description=f"**{member.display_name}** has been banned.",
                color=discord.Color.red(),
            )
            embed.add_field(name="Reason", value=reason or "No reason provided.")
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to ban this user.")

    @commands.hybrid_command()
    @commands.has_permissions(administrator=True)
    async def unban(self, ctx, user_id: int = None):
        """Unbans a user by their user ID."""
        if not user_id:
            return await ctx.send("❌ Usage: `!unban <User_ID>`")

        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user)
            embed = discord.Embed(
                title="🕊️ User Unbanned",
                description=f"**{user.display_name}** has been unbanned.",
                color=discord.Color.green(),
            )
            await ctx.send(embed=embed)
        except discord.NotFound:
            await ctx.send("❌ That user is not banned or does not exist.")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to unban users.")
        except ValueError:
            await ctx.send("❌ Invalid User ID. Must be a number.")

    @commands.hybrid_command()
    @commands.has_permissions(administrator=True)
    async def addrole(
        self, ctx, member: discord.Member = None, *, role_name: str = None
    ):
        """Assigns a role to a user."""
        if not member or not role_name:
            return await ctx.send("❌ Usage: `!addrole @user RoleName`")

        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if not role:
            return await ctx.send(f"❌ Could not find a role named `{role_name}`.")

        try:
            await member.add_roles(role)
            await ctx.send(f"✅ Added role **{role.name}** to {member.mention}.")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to assign that role.")

    @commands.hybrid_command()
    @commands.has_permissions(administrator=True)
    async def removerole(
        self, ctx, member: discord.Member = None, *, role_name: str = None
    ):
        """Removes a role from a user."""
        if not member or not role_name:
            return await ctx.send("❌ Usage: `!removerole @user RoleName`")

        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if not role:
            return await ctx.send(f"❌ Could not find a role named `{role_name}`.")

        try:
            await member.remove_roles(role)
            await ctx.send(f"✅ Removed role **{role.name}** from {member.mention}.")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to remove that role.")

    @commands.hybrid_command()
    @commands.has_permissions(administrator=True)
    async def forcename(
        self, ctx, member: discord.Member = None, *, new_name: str = None
    ):
        """Force changes a user's nickname."""
        if not member or not new_name:
            return await ctx.send("❌ Usage: `!forcename @user NewNickname`")

        try:
            await member.edit(nick=new_name[:32])
            await ctx.send(
                f"✅ Changed {member.display_name}'s nickname to **{new_name[:32]}**."
            )
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to change their nickname.")

    @commands.hybrid_command()
    @commands.has_permissions(administrator=True)
    async def mute(
        self,
        ctx,
        member: discord.Member = None,
        minutes: int = None,
        *,
        reason: str = None,
    ):
        """Mutes (timeouts) a user for a specific number of minutes."""
        if not member or not minutes:
            return await ctx.send("❌ Usage: `!mute @user <minutes> [Reason]`")

        import datetime

        try:
            duration = datetime.timedelta(minutes=minutes)
            await member.timeout(duration, reason=reason)
            embed = discord.Embed(
                title="🔇 User Muted",
                description=f"**{member.display_name}** has been timed out for {minutes} minutes.",
                color=discord.Color.orange(),
            )
            if reason:
                embed.add_field(name="Reason", value=reason)
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to timeout this user.")

    @commands.hybrid_command()
    @commands.has_permissions(administrator=True)
    async def unmute(self, ctx, member: discord.Member = None):
        """Removes a timeout from a user."""
        if not member:
            return await ctx.send("❌ Usage: `!unmute @user`")

        try:
            await member.timeout(None, reason="Unmuted by admin")
            embed = discord.Embed(
                title="🔊 User Unmuted",
                description=f"**{member.display_name}**'s timeout was removed.",
                color=discord.Color.green(),
            )
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to remove timeouts.")

    @commands.hybrid_command()
    @commands.has_permissions(administrator=True)
    async def lock(self, ctx, channel: discord.TextChannel = None):
        """Locks a channel so @everyone cannot send messages."""
        target_channel = channel or ctx.channel

        try:
            await target_channel.set_permissions(
                ctx.guild.default_role, send_messages=False
            )
            embed = discord.Embed(
                title="🔒 Channel Locked",
                description=f"{target_channel.mention} has been locked.",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to lock channels.")

    @commands.hybrid_command()
    @commands.has_permissions(administrator=True)
    async def unlock(self, ctx, channel: discord.TextChannel = None):
        """Unlocks a channel so @everyone can send messages."""
        target_channel = channel or ctx.channel

        try:
            await target_channel.set_permissions(
                ctx.guild.default_role, send_messages=None
            )
            embed = discord.Embed(
                title="🔓 Channel Unlocked",
                description=f"{target_channel.mention} has been unlocked.",
                color=discord.Color.green(),
            )
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to unlock channels.")


async def setup(bot):
    await bot.add_cog(Moderation(bot))
