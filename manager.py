import discord
import logging
import orjson
import shared
import asyncio
import utils
import platform
import pydactyl
import psutil
from shutil import disk_usage
from noadmin import bot as noadmin
from api import get_roles
from host import Service as DatalixService
from typing import Union, Optional
from shared import reply, get_embed
from components import InviteButton, DmButton, InviteNoadminButton
from default import check, cross, p_name
from settings import BetaSettings
from user import User, Permissions
from discord import app_commands
from discord.ext import commands
from discord.ext.tasks import loop
from about import __version__

log = logging.getLogger(__name__)
bot = commands.Bot(command_prefix='.', intents=discord.Intents.all(), help_command=None)
config = shared.config
db = shared.db
main_server: discord.Guild
cooldowns = shared.cooldowns
command = shared.command
bot.event(shared.on_command_error)

with open('config/state.json') as file:
    state = orjson.loads(file.read())

with open('config/roles.json') as file:
    roles: dict = orjson.loads(file.read())

async def verify_member(member: discord.Member):
    user = await db.get_user(member.id)
    if not config['enable_verify']:
        assign_ids = [role.id for role in member.roles if not role.id in roles.values()]
        # hidden role
        if 1475527811476230348 not in assign_ids:
            assign_ids += [roles['community']]
        if user:
            if user.is_premium:
                assign_ids.append(roles['premium'])
            if user.is_super:
                assign_ids.append(roles['moderator'])
        if await db.get_user_blacklist(member.id):
            assign_ids = [roles['blacklist']]
        assign_ids = set(assign_ids)
        if assign_ids != {role.id for role in member.roles}:
            update = [role for role in member.guild.roles if role.id in assign_ids]
            await member.edit(roles=update)
    
    elif user:
        auth = user.auth
        if not member == member.guild.me:
            current = {role.id for role in member.roles}
            remove = {
                role_id for name, role_id in roles.items()
                if name != 'mute'
            }
            new = [
                role for role in member.roles
                if role.id not in remove
            ]
            if not auth or auth.expires_in < 0:
                if not current.intersection(remove):
                    return
                try:
                    await member.edit(roles=new)
                except discord.HTTPException:
                    return
            else:
                user_roles = set(get_roles(user))
                if user_roles != current:
                    try:
                        update = [role for role in member.guild.roles if role.id in user_roles]
                        await member.edit(roles=update)
                    except discord.HTTPException:
                        return

@loop(seconds=10)
async def betaloop():
    while not getattr(db, 'pool', None):
        await asyncio.sleep(1)
    for member in shared.main_server.members:
        await verify_member(member)

@bot.event
async def on_ready():
    assert bot.user, '???'
    bot.add_view(DmButton(0))
    bot.add_view(InviteButton(state['bot_id']))
    await bot.tree.sync()
    global main_server
    main_server = bot.get_guild(config['server_id']) # type: ignore
    if not main_server:
        log.critical(f'Main server not found. Add me via: https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=8&scope=bot')
        while not main_server:
            await asyncio.sleep(1)
            main_server = bot.get_guild(config['server_id'])
    shared.main_server = main_server
    while not noadmin.user:
        log.info('Waiting for no-admin startup ...')
        await asyncio.sleep(1)
    bot.add_view(InviteNoadminButton(noadmin.user.id))
    log.info(f'Logged on {bot.user} (ID: {bot.user.id})')
    # betaloop.start()

@bot.event
async def on_member_join(member: discord.Member):
    await verify_member(member)
    channel = discord.utils.get(member.guild.channels, name='chat')
    if isinstance(channel, discord.TextChannel):
        await channel.send(f'Welcome to {p_name} V{__version__} {member.mention}. Invite nake bot: <#{config['invite_channel']}>')

@bot.event
async def on_member_update(_, after: discord.Member):
    await verify_member(after)

@bot.command('stats', aliases=['ping'])
@command(keep_message=True)
@cooldowns.check(1)
async def cmd_stats(ctx: commands.Context, user: User, *args):
    embed = discord.Embed(title=f'{p_name} V{__version__}')
    version = discord.version_info
    embed.add_field(
        name='Connection',
        value=(
            f'Client latency: {round(bot.latency * 1000, 2)}ms\n'
            f'Discord API version: 10\n'
        )
    )
    disk = disk_usage('./')
    memory = psutil.virtual_memory()
    used = utils.convert_bytes(disk.used)
    total = utils.convert_bytes(disk.total)
    memory_used = utils.convert_bytes(memory.used)
    memory_total = utils.convert_bytes(memory.available)
    embed.add_field(
        name='Stats',
        value=(
            f'Memory Usage: {round(memory_used[0], 2)}{memory_used[1]}/{round(memory_total[0], 2)}{memory_total[1]}\n'
            f'Disk Usage: {round(used[0], 2)}{used[1]}/{round(total[0], 2)}{total[1]}'
        )
    )
    embed.add_field(
        name='System',
        value=(
            f'Platform: {platform.platform()}\n'
            f'Python version: {platform.python_version()}\n'
            f'Discord.py version: {version.major}.{version.minor}.{version.micro} {version.releaselevel}'
        ),
        inline=False
    )
    await ctx.reply(embed=embed)

@bot.command('check')
@command(Permissions(elevated_only=True), keep_message=True)
@cooldowns.check(1)
async def cmd_check(ctx: commands.Context, user_: User, subject: Union[str, int], *args):
    def yn(value: bool):
        return check if value else cross

    assert ctx.guild, '???'
    user = None
    if isinstance(subject, int):
        user = await db.get_user(subject)
    if not user:
        member = discord.utils.get(ctx.guild.members, name=subject)
        if member:
            user = await db.get_user(member.id)
    if not user:
        return await reply(ctx, f'Member "{subject}" not found', 'warning')
    member_ = discord.utils.get(ctx.guild.members, id=user.id)
    name = None
    if member_:
        name = member_.name
    else:
        if user.auth:
            name = user.auth.username
        else:
            name = subject
    embed = discord.Embed(
        title=f'Info about {name}',
        description=f'ID: {user.id}'
    )
    if member_:
        if member_.avatar:
            embed.set_thumbnail(url=member_.avatar.url)
        else:
            embed.set_thumbnail(url=member_.default_avatar.url)
        if member_.banner:
            embed.set_image(url=member_.banner.url)
    embed.add_field(name='Info', value=(
        f'<:crown:1480917537389543485> Owner: {yn(user.is_owner)}\n'
        f'<:star:1475461823028396042> Super Privileges: {yn(user.is_elevated)}\n'
        f'<:booster:1475459072475004938> Premium: {yn(user.is_premium)}\n'
        f'<:ban:1480902776434458656> Blacklisted: {yn(user.is_blacklisted)}'
    ))
    await ctx.reply(embed=embed)

@bot.command('reinvite')
@command(Permissions(elevated_only=True))
@cooldowns.check(1)
async def cmd_reinvite(ctx: commands.Context, user: User, bot_id: int):
    await ctx.send(embed=InviteButton.embed(), view=InviteButton(bot_id))
    content = orjson.dumps({'bot_id': bot_id, 'last_bot': bot_id})
    with open('config/state.json', 'wb') as file:
        file.write(content)

@bot.command('reinvite_noadmin')
@command(Permissions(elevated_only=True))
@cooldowns.check(1)
async def cmd_reinvite_noadmin(ctx: commands.Context, user: User):
    assert noadmin.user, '???'
    await ctx.send(embed=InviteNoadminButton.embed(), view=InviteNoadminButton(noadmin.user.id))

@bot.command('shutdown')
@command(Permissions(elevated_only=True), keep_message=True)
@cooldowns.check(1)
async def cmd_shutdown(ctx: commands.Context, user: User):
    if shared.has_host:
        await reply(ctx, 'All bots scheduled for shutdown...', 'info')
    else:
        return await reply(ctx, 'No host specified', 'warning')
    if isinstance(shared.dactyl, pydactyl.async_api_client.AsyncClientAPI):
        response = await shared.dactyl.servers.send_power_action(shared.server, 'stop')
        if response:
            await reply(ctx, 'Failed to shutdown server', 'error')
    elif isinstance(shared.datalix_service, DatalixService):
        await shared.datalix_service.shutdown()

@bot.command('reboot', aliases=['restart'])
@command(Permissions(elevated_only=True), keep_message=True)
@cooldowns.check(1)
async def cmd_reboot(ctx: commands.Context, user: User):
    if shared.has_host:
        await reply(ctx, 'All bots scheduled for restart...', 'info')
    else:
        return await reply(ctx, 'No host specified', 'warning')
    if isinstance(shared.dactyl, pydactyl.async_api_client.AsyncClientAPI):
        response = await shared.dactyl.servers.send_power_action(shared.server, 'restart')
        if response:
            await reply(ctx, 'Failed to reboot server', 'error')
    elif isinstance(shared.datalix_service, DatalixService):
        await shared.datalix_service.restart()

@bot.command('kill')
@command(Permissions(elevated_only=True), keep_message=True)
@cooldowns.check(1)
async def cmd_kill(ctx: commands.Context, user: User):
    if shared.has_host:
        await reply(ctx, 'Killing all bots...', 'info')
    else:
        return await reply(ctx, 'No host specified', 'warning')
    if isinstance(shared.dactyl, pydactyl.async_api_client.AsyncClientAPI):
        response = await shared.dactyl.servers.send_power_action(shared.server, 'kill')
        if response:
            await reply(ctx, 'Failed to kill server', 'error')
    elif isinstance(shared.datalix_service, DatalixService):
        await shared.datalix_service.shutdown()

@bot.command('create_backup')
@command(Permissions(elevated_only=True), keep_message=True)
@cooldowns.check(1)
async def cmd_create_backup(ctx: commands.Context, user: User):
    if shared.has_host:
        await reply(ctx, 'Creating backup...', 'info')
    else:
        return await reply(ctx, 'No host specified', 'warning')
    if isinstance(shared.datalix_service, DatalixService):
        await shared.datalix_service.create_backups()
        await reply(ctx, 'Successfully created backup', 'info')
    else:
        await reply(ctx, 'Invalid host. Could not create backup', 'warning')

@bot.command('view_trace')
@command(Permissions(elevated_only=True), keep_message=True)
@cooldowns.check(0)
async def cmd_view_trace(ctx: commands.Context, user: User, trace_id: str):
    with open('data/trace.json', 'rb') as file:
        traces = orjson.loads(file.read())
    
    trace = traces.get(trace_id)
    if not trace:
        return await reply(ctx, f'Trace with id {trace_id} not found', 'warning')

    for i in range(0, len(trace), 4000):
        for part in trace[i:i+4000]:
            fields = [{
                'name': 'Data',
                'value': part,
                'inline': False
            }]
            await reply(ctx, f'Part {i} of {len(trace) // 4000}', fields=fields)

@bot.command('blacklist')
@command(Permissions(elevated_only=True))
@cooldowns.check(0)
async def cmd_blacklist(ctx: commands.Context, user: User, subject: int, type_: str = 'user'):
    assert ctx.guild, '???'
    if type_ == 'user':
        if await db.add_user_blacklist(subject):
            member = main_server.get_member(subject)
            if member:
                assign = [role for role in ctx.guild.roles if role.id == roles['blacklist']]
                await member.edit(roles=assign)
                try:
                    embed = get_embed('You have been blacklisted from Fluc', 'warning')
                    await member.send(embed=embed)
                except discord.HTTPException:
                    pass
            return await reply(ctx, f'User with ID {subject} blacklisted')
        await reply(ctx, f'User with ID {subject} not blacklisted')
    if type_ == 'server':
        if await db.add_server_blacklist(subject):
            return await reply(ctx, f'Sever with ID {subject} blacklisted')
        await reply(ctx, f'Sever with ID {subject} not blacklisted')

# @bot.command('betasettings', aliases=['betaset'])
# @command(Permissions(elevated_only=True))
@cooldowns.check(0)
async def cmd_betasettings(ctx: commands.Context, user: User, *args):
    view = BetaSettings(user)
    await ctx.send(f'Settings for {ctx.author.mention}. Separate each value with a comma', view=view)

@bot.tree.command(name='setautonake')
@app_commands.describe(delay = 'Delay for auto nake. Skip or set to -1 to disable auto nake.')
async def cmd_set_autonuke(interaction: discord.Interaction, delay: Optional[int]):
    user = await db.get_user(interaction.user.id)
    if not user:
        user = User.new(interaction.user.id)
        await db.add_user(user)
    if max(delay or -1, -1) == -1:
        del user.settings._data['master']['auto_nuke']
    else:
        user.settings._data['master']['auto_nuke'] = max(-1, delay or -1)
    if await db.update_settings(user.id, user.settings):
        embed = get_embed('Settings updated')
        return await interaction.response.send_message(embed=embed)
    embed = get_embed('Settings not updated')
    await interaction.response.send_message(embed=embed)

# @bot.tree.command(name='selectpreset')
# @app_commands.describe(preset = 'Index of the preset you want to select. Skip or set index to 0 to randomize it every time.')
async def cmd_select_preset(interaction: discord.Interaction, preset: Optional[int]):
    user = await db.get_user(interaction.user.id)
    if not user:
        user = User.new(interaction.user.id)
        await db.add_user(user)
    if not preset:
        del user.settings._data['selected_preset']
    else:
        presets = len(user.settings.presets)
        if preset > presets:
            embed = get_embed(f'You can\'t select preset {preset}, because you have only {presets} preset{'s' if presets > 1 else ''}', 'warning')
            return await interaction.response.send_message(embed=embed)
        user.settings._data['selected_preset'] = preset
    if await db.update_settings(user.id, user.settings):
        embed = get_embed('Settings updated')
        return await interaction.response.send_message(embed=embed)
    embed = get_embed('Settings not updated')
    await interaction.response.send_message(embed=embed)