import discord
import shared
from discord import app_commands
from discord.ext import commands
from components import SpamView
from logging import getLogger

bot = commands.Bot('.', intents=discord.Intents.all(), help_command=None)
log = getLogger('fluc.NoAdmin')
db = shared.db

@bot.event
async def on_ready():
    assert bot.user
    bot.add_view(SpamView(None))
    await bot.tree.sync()
    log.info(f'Logged on {bot.user} (ID: {bot.user.id})')

@bot.tree.command(name='spam')
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def cmd_spam(interaction: discord.Interaction):
    user = await db.get_user(interaction.user.id)
    if not user:
        return await interaction.response.defer(ephemeral=True)
    log.debug(f'Command spam ran by {interaction.user.id}')
    view = SpamView(user)
    await interaction.response.send_message(view=view, embed=view.embed, ephemeral=True)