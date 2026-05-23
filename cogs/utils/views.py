import discord
import asyncio
from cogs.utils.translator import translate_content


class TranslatedView(discord.ui.View):
    async def send_translated(
        self,
        interaction: discord.Interaction,
        content: str = None,
        embed: discord.Embed = None,
        **kwargs
    ):
        if not interaction.response.is_done():
            ephemeral = kwargs.get("ephemeral", False)
            await interaction.response.defer(ephemeral=ephemeral)

        target_locale = interaction.locale
        tasks = []

        if content:
            tasks.append(
                translate_content(
                    content,
                    target_locale,
                    bot=interaction.client,
                    guild_id=interaction.guild_id,
                )
            )

        if embed:
            if embed.title:
                tasks.append(
                    translate_content(
                        embed.title,
                        target_locale,
                        bot=interaction.client,
                        guild_id=interaction.guild_id,
                    )
                )
            if embed.description:
                tasks.append(
                    translate_content(
                        embed.description,
                        target_locale,
                        bot=interaction.client,
                        guild_id=interaction.guild_id,
                    )
                )

            for field in embed.fields:
                if field.name:
                    tasks.append(
                        translate_content(
                            field.name,
                            target_locale,
                            bot=interaction.client,
                            guild_id=interaction.guild_id,
                        )
                    )
                if field.value:
                    tasks.append(
                        translate_content(
                            field.value,
                            target_locale,
                            bot=interaction.client,
                            guild_id=interaction.guild_id,
                        )
                    )

        results = await asyncio.gather(*tasks) if tasks else []

        res_idx = 0
        if content:
            content = results[res_idx]
            res_idx += 1

        if embed:
            if embed.title:
                embed.title = results[res_idx]
                res_idx += 1
            if embed.description:
                embed.description = results[res_idx]
                res_idx += 1

            for index, set_field in enumerate(embed.fields):
                new_name = set_field.name
                new_value = set_field.value
                if set_field.name:
                    new_name = results[res_idx]
                    res_idx += 1
                if set_field.value:
                    new_value = results[res_idx]
                    res_idx += 1
                embed.set_field_at(
                    index, name=new_name, value=new_value, inline=set_field.inline
                )

        # Send the final translated response
        if interaction.response.is_done():
            await interaction.followup.send(content=content, embed=embed, **kwargs)
        else:
            await interaction.response.send_message(
                content=content, embed=embed, **kwargs
            )

    async def edit_translated(
        self,
        interaction: discord.Interaction,
        content: str = None,
        embed: discord.Embed = None,
        **kwargs
    ):
        if not interaction.response.is_done():
            await interaction.response.defer()

        target_locale = interaction.locale
        tasks = []

        if content:
            tasks.append(
                translate_content(
                    content,
                    target_locale,
                    bot=interaction.client,
                    guild_id=interaction.guild_id,
                )
            )

        if embed:
            if embed.title:
                tasks.append(
                    translate_content(
                        embed.title,
                        target_locale,
                        bot=interaction.client,
                        guild_id=interaction.guild_id,
                    )
                )
            if embed.description:
                tasks.append(
                    translate_content(
                        embed.description,
                        target_locale,
                        bot=interaction.client,
                        guild_id=interaction.guild_id,
                    )
                )

            for field in embed.fields:
                if field.name:
                    tasks.append(
                        translate_content(
                            field.name,
                            target_locale,
                            bot=interaction.client,
                            guild_id=interaction.guild_id,
                        )
                    )
                if field.value:
                    tasks.append(
                        translate_content(
                            field.value,
                            target_locale,
                            bot=interaction.client,
                            guild_id=interaction.guild_id,
                        )
                    )

        results = await asyncio.gather(*tasks) if tasks else []

        res_idx = 0
        if content:
            content = results[res_idx]
            res_idx += 1

        if embed:
            if embed.title:
                embed.title = results[res_idx]
                res_idx += 1
            if embed.description:
                embed.description = results[res_idx]
                res_idx += 1

            for index, set_field in enumerate(embed.fields):
                new_name = set_field.name
                new_value = set_field.value
                if set_field.name:
                    new_name = results[res_idx]
                    res_idx += 1
                if set_field.value:
                    new_value = results[res_idx]
                    res_idx += 1
                embed.set_field_at(
                    index, name=new_name, value=new_value, inline=set_field.inline
                )

        # Edit the final translated response
        if interaction.response.is_done():
            await interaction.message.edit(content=content, embed=embed, **kwargs)
        else:
            await interaction.response.edit_message(
                content=content, embed=embed, **kwargs
            )


class TranslatedModal(discord.ui.Modal):
    async def send_translated(
        self,
        interaction: discord.Interaction,
        content: str = None,
        embed: discord.Embed = None,
        **kwargs
    ):
        if not interaction.response.is_done():
            ephemeral = kwargs.get("ephemeral", False)
            await interaction.response.defer(ephemeral=ephemeral)

        target_locale = interaction.locale
        tasks = []

        if content:
            tasks.append(
                translate_content(
                    content,
                    target_locale,
                    bot=interaction.client,
                    guild_id=interaction.guild_id,
                )
            )

        if embed:
            if embed.title:
                tasks.append(
                    translate_content(
                        embed.title,
                        target_locale,
                        bot=interaction.client,
                        guild_id=interaction.guild_id,
                    )
                )
            if embed.description:
                tasks.append(
                    translate_content(
                        embed.description,
                        target_locale,
                        bot=interaction.client,
                        guild_id=interaction.guild_id,
                    )
                )

            for field in embed.fields:
                if field.name:
                    tasks.append(
                        translate_content(
                            field.name,
                            target_locale,
                            bot=interaction.client,
                            guild_id=interaction.guild_id,
                        )
                    )
                if field.value:
                    tasks.append(
                        translate_content(
                            field.value,
                            target_locale,
                            bot=interaction.client,
                            guild_id=interaction.guild_id,
                        )
                    )

        results = await asyncio.gather(*tasks) if tasks else []

        res_idx = 0
        if content:
            content = results[res_idx]
            res_idx += 1

        if embed:
            if embed.title:
                embed.title = results[res_idx]
                res_idx += 1
            if embed.description:
                embed.description = results[res_idx]
                res_idx += 1

            for index, set_field in enumerate(embed.fields):
                new_name = set_field.name
                new_value = set_field.value
                if set_field.name:
                    new_name = results[res_idx]
                    res_idx += 1
                if set_field.value:
                    new_value = results[res_idx]
                    res_idx += 1
                embed.set_field_at(
                    index, name=new_name, value=new_value, inline=set_field.inline
                )

        # Send the final translated response
        if interaction.response.is_done():
            await interaction.followup.send(content=content, embed=embed, **kwargs)
        else:
            await interaction.response.send_message(
                content=content, embed=embed, **kwargs
            )
