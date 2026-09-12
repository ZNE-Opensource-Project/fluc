import discord
import database
import asyncio
import logging
import utils
from traceback import TracebackException
from orjson import loads
from uuid import uuid4
from collections import defaultdict
from user import Settings, Permissions, User
from datetime import datetime, UTC
from discord.ext import commands
from default import cross, check
from host import Datalix, Service
import pydactyl
from typing import (
    List, Optional, Literal, Callable, Coroutine,
    Any, Dict, Union, Tuple
)

class EmptyAsyncClient:
    async def __aenter__(self):
        pass

    async def __aexit__(self, exc_type, exc, tb):
        pass

log = logging.getLogger()
running = defaultdict(set)
locks = defaultdict(asyncio.Semaphore)
datalix: Union[Datalix, EmptyAsyncClient] = EmptyAsyncClient()
datalix_service: Optional[Service] = None
dactyl: Union[pydactyl.async_api_client.AsyncClientAPI, EmptyAsyncClient] = EmptyAsyncClient()
server: Optional[str]
has_host: bool


class Cooldowns:
    rate_limits: Dict[str, Dict[int, float]]
    'Dict[command_name: Dict[user_id/server_id, timestamp_expires, min_members]]'
    cooldowns: Dict[str, Tuple[int, int, bool, bool, Optional[int]]]
    'Dict[command_name: (server_cooldown, user_cooldown, server_cooldown_enabled, user_cooldown_enabled)]'
    permissions: Dict[str, Optional[discord.Permissions]]
    'Dict[command_name: discord.Permissions]'
    # Basically ellipsis (the one we're supposed to use in 3.14) is not a thing in previous versions, that's why we use Ellipsis
    callbacks: Dict[str, Tuple[Callable[..., Coroutine[Any, Any, Any]], Union[Permissions, Ellipsis], Union[Callable[..., Coroutine[Any, Any, Any]], Ellipsis], Optional[Union[str, Ellipsis]]]] # pyright: ignore[reportInvalidTypeForm]
    'Dict[command_name: (coro, .../Permissions, .../wrapper, .../doc)]'
    aliases: Dict[str, List[str]]
    'Dict[command_name: alias_name]'
    warned_users: Dict[Tuple[str, int, int], float] = {}
    'Dict[(command_name, author_id, channel_id): timestamp_expires]'
    to_check: Dict[str, List[str]]
    'Dict[command_name: [command_name/alias_name]]'
    
    def __init__(self) -> None:
        self.rate_limits = defaultdict(dict)
        self.cooldowns = {}
        self.warned_users = {}
        self.permissions = {}
        self.callbacks = {}
        self.aliases = {}
        self.to_check = {}

    def check(
        self,
        cooldown: int,
        *,
        user_cooldown: bool = True,
        server_cooldown: bool = False,
        aliases: Optional[List[str]] = None,
        min_members: Optional[int] = None
    ) -> Callable[[Any], Any]:
        def decorator(coro: Callable[..., Coroutine[Any, Any, Any]]):
            command = coro.__name__
            command = command.removeprefix('cmd_')
            self.callbacks[command] = (coro, ..., ..., coro.__doc__)
            self.cooldowns[command] = (int(cooldown), int(min(60, cooldown)), bool(user_cooldown), bool(server_cooldown), min_members)

            if aliases:        
                self.aliases[command] = aliases
            return coro
        return decorator

    def add_command(
        self,
        command: str,
        permissions: Permissions,
        discord_permissions: Optional[discord.Permissions],
        wrapper: Callable[..., Coroutine[Any, Any, Any]],
        doc: Optional[str]
    ) -> None:
        callback = self.callbacks[command]
        func = callback[0]
        self.callbacks[command] = (func, permissions, wrapper, doc)
        self.permissions[command] = discord_permissions

    async def check_cooldown(
        self,
        command: str,
        guild_id: int,
        user_id: int,
        *,
        user_cooldown: bool = True,
        server_cooldown: bool = False,
        now: Optional[datetime] = None,
        apply_cooldown: bool = False,
        user: Optional[User] = None
    ) -> None:
        if now is None:
            now = datetime.now(UTC)
        utcnow = int(now.timestamp())
        server_cd, user_cd = self.cooldowns[command][:2]
        rate_limits = {key: value for key, value in self.rate_limits[command].items() if value > utcnow}

        async def apply_cd(key: int, duration: float, bucket_type: commands.BucketType):
            if key not in rate_limits:
                cooldown = utcnow + duration + 3
                if user and user.is_premium:
                    # 25% less for premium users
                    cooldown = cooldown - (cooldown // 4)
                rate_limits[key] = cooldown

            else:
                remaining = rate_limits[key] - utcnow
                if remaining > 0:
                    raise commands.CommandOnCooldown(
                        commands.Cooldown(0, duration),
                        remaining,
                        bucket_type
                    )
                
        if server_cooldown:
            await apply_cd(guild_id, server_cd, commands.BucketType.guild)
                
        if user_cooldown:
            await apply_cd(user_id, user_cd, commands.BucketType.user)
                
        if apply_cooldown:
            self.rate_limits[command] = rate_limits

    def remove_cooldown(self, command: str, guild_id: int, user_id: int) -> None:
        if command not in self.rate_limits:
            return

        rate_limits = self.rate_limits[command]
        rate_limits.pop(guild_id, None)
        rate_limits.pop(user_id, None)

        if not rate_limits:
            del self.rate_limits[command]


db = database.Database()
cooldowns = Cooldowns()
main_server: discord.Guild
rate_limit: bool = False
with open('config/config.json') as file:
    config = loads(file.read())


async def get_prefix(bot: commands.Bot, message: discord.Message) -> List[str]:
    user = await db.get_user(message.author.id)
    if not user:
        return Settings.default().command_prefix
    return user.settings.command_prefix

def get_embed(
    content: str,
    level: Optional[Literal['info', 'warning', 'error', '']] = None,
    header: Optional[str] = None,
    footer: Optional[str] = None,
    fields: Optional[List[Dict[str, str]]] = None
) -> discord.Embed:
    if not fields:
        fields = []

    if not level:
        level = ''

    level_map = {
        'info': [
            discord.Color.blue,
            check,
            'Success'
        ],
        'warning': [
            discord.Color.yellow,
            ':warning:',
            'Warning'
        ],
        'error': [
            discord.Color.red,
            cross,
            'Error'
        ],
        '': [
            discord.Color.green,
            '',
            ''
        ]
    }
    embed = discord.Embed(
        title=header or level_map[level][2],
        description=f'{level_map[level][1]} {content}',
        color=level_map[level][0]()
    )
    for field in fields:
        embed.add_field(inline=bool(field['inline']), name=field['name'], value=field['value'])
    if footer:
        embed.set_footer(text=footer)
    return embed

async def reply(
    ctx: commands.Context,
    content: str,
    level: Optional[Literal['info', 'warning', 'error', '']] = None,
    header: Optional[str] = None,
    footer: Optional[str] = None,
    fields: Optional[List[Dict[str, str]]] = None,
    **kwargs
) -> discord.Message:
    embed = get_embed(content, level, header, footer, fields)
    return await ctx.reply(embed=embed, **kwargs)

def command(permissions: Permissions = Permissions(), discord_permissions: discord.Permissions = discord.Permissions.none(), keep_message: bool = False):
    def decorator(coro: Callable[..., Coroutine[Any, Any, Any]]):
        command = coro.__name__
        command = command.removeprefix('cmd_')

        async def wrapper(ctx: commands.Context, *args, **kwargs):
            if not ctx.guild:
                return
            user = await db.get_user(ctx.author.id)
            if not user:
                if ctx.author in main_server.members:
                    user = User.new(ctx.author.id)
                    await db.add_user(user)
            
            try:
                assert user, 'You are not a user'
                assert command not in running[user.id]
            except AssertionError:
                return
            if permissions.elevated:
                assert user.is_elevated, 'User not elevated'
            if permissions.auth:
                assert user.auth, 'User not authorized'
            if permissions.owner:
                assert user.id == db.owner_id, 'User not owner'
            try:
                if not permissions.ignore_user_blacklist:
                    assert not await db.get_user_blacklist(ctx.author.id), 'User blacklisted'
                if not permissions.ignore_server_blacklist:
                    assert not await db.get_server_blacklist(ctx.guild.id), 'Server blacklisted'
            except AssertionError:
                return
            if not user.is_elevated:
                if not command in cooldowns.to_check:
                    cooldowns.to_check[command] = [command]

                now = datetime.now(UTC)
                to_check = cooldowns.to_check[command]
                for cmd in to_check:
                    server_cooldown = cooldowns.cooldowns[cmd][2]
                    user_cooldown = cooldowns.cooldowns[cmd][3]
                    min_members = cooldowns.cooldowns[cmd][4]
                    key = (cmd, ctx.author.id, ctx.channel.id)
                    try:
                        async with locks[ctx.author.id]:
                            await cooldowns.check_cooldown(
                                cmd,
                                ctx.guild.id,
                                ctx.author.id,
                                user_cooldown=user_cooldown,
                                server_cooldown=server_cooldown,
                                now=now,
                                apply_cooldown=True,
                                user=user
                            )
                    except commands.CommandOnCooldown as exc:
                        if isinstance(ctx.message, discord.Message):
                            if key not in cooldowns.warned_users or cooldowns.warned_users[key] < now.timestamp():
                                await reply(ctx, f'Command on cooldown. Retry <t:{int(exc.retry_after + datetime.now(UTC).timestamp())}:R>', 'error', delete_after=exc.retry_after - 0.5)
                                await ctx.message.delete()
                                cooldowns.warned_users[key] = now.timestamp() + exc.retry_after
                            return
                    # Check members AFTER cooldown is checked
                    if min_members:
                        if len(ctx.guild.members) <= min_members:
                            embed = get_embed('This command is not allowed in small servers.', 'warning')
                            if command == 'bypass':
                                # More info about common command
                                embed.description = f'Use `.nuke` instead or watch demo of this command here - {'YouTube video soon'}'
                            return await ctx.send(embed=embed, delete_after=10)
            try:
                if not keep_message:
                    await ctx.message.delete()
            except Exception:
                pass

            invoke_args = [*args]
            annotations = dict(coro.__annotations__)
            zipped = zip(invoke_args, list(annotations.values())[2:])
            zipped = [item for item in zipped]

            for i, (value, arg_type) in enumerate(zipped):
                try:
                    invoke_args[i] = utils.parse_arguments(list(annotations.keys())[i + 2], value, arg_type)
                except TypeError as exc:
                    raise commands.BadArgument(str(exc))

            ctx.args = [ctx, user] + invoke_args
            try:
                running[user.id].add(command)
                try:
                    log.info(f'Command {command} ran by {user.id}')
                    if user.is_premium or user.is_elevated:
                        return await coro(*ctx.args)
                    return await coro(*ctx.args[:2])
                except discord.HTTPException:
                    pass
            finally:
                running[user.id].remove(command)
                if not running[user.id]:
                    del running[user.id]
        cooldowns.add_command(command, permissions, discord_permissions, wrapper, coro.__doc__)
        return wrapper
    return decorator

async def on_command_error(ctx: commands.Context, exc: discord.ClientException):
    trace_id, trace = str(uuid4()), ''.join(TracebackException.from_exception(exc).format())
    footer = f'Trace ID: {trace_id}'
    if str(exc).endswith('AssertionError: '):
        return
    utils.set_trace(trace_id, trace) 
    log.error(trace)
    try:
        if isinstance(exc, commands.CommandInvokeError):
            await reply(ctx, str(exc), 'error', footer=footer)
        elif isinstance(exc, commands.MissingPermissions):
            await reply(ctx, str(exc), 'error', footer=footer)
        elif isinstance(exc, (commands.CommandNotFound, commands.CheckFailure, AssertionError)):
            pass
        else:
            await reply(ctx, str(exc), 'error', footer=footer)
    except discord.HTTPException:
        return