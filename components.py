from __future__ import annotations

import discord
import requests
import asyncio
import queue
from logging import getLogger
from requests.adapters import HTTPAdapter
from time import sleep
from urllib.parse import urlencode
from discord import ui
from about import __version__
from user import User
from default import server_icon, cross, check, p_name
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Awaitable, Optional, List, TypedDict, Generator, Tuple

log = getLogger(__name__)


class TButton(TypedDict):
    label: str
    style: discord.ButtonStyle
    callback: Callable[[Buttons, discord.Interaction, ui.Button], Awaitable]
    custom_id: Optional[str]


class DmButton(ui.View):
    def __init__(self, bot_id: int, *, user_intall: bool = False):
        super().__init__(timeout=None)
        if user_intall:
            params = {
                'client_id': bot_id,
                'integration_type': 1,
                'scope': 'applications.commands'
            }
        else:
            params = {
                'client_id': bot_id,
                'permissions': 1099511627775,
                'scope': 'bot'
            }
        
        button = ui.Button(
            label='🤖 Add Bot',
            style=discord.ButtonStyle.link,
            url=f'https://discord.com/oauth2/authorize?' + urlencode(params)  
        )
        if not bot_id:
            button.disabled = True
        self.add_item(button)


class InviteButton(ui.View):
    def __init__(self, bot_id: int):
        super().__init__(timeout=None)
        self.bot_id = bot_id
        button = ui.Button(
            label='🤖 Add Bot',
            style=discord.ButtonStyle.primary,
            custom_id=f'button_{bot_id}'
        )
        button.callback = self.callback
        self.add_item(button)

    async def callback(self, interaction: discord.Interaction, *, retry: int = 0):
        if not retry:
            await interaction.response.defer(ephemeral=True)
        try:
            message = await interaction.user.send(
                embed=self.embed(),
                view=DmButton(self.bot_id),
                delete_after=60
            )
            await interaction.followup.send(
                embed=discord.Embed(
                    title='Success!',
                    description=f'{check} The bot invite has been sent to your DMs {message.jump_url}!',
                    color=discord.Color.blue()
                ),
                ephemeral=True
            )
        
        except discord.Forbidden:
            await interaction.followup.send(
                embed=discord.Embed(
                    title='Error',
                    description=f'{cross} Please enable your DMs in order to get the invite.'
                ),
                ephemeral=True
            )
        except discord.HTTPException as exc:
            # Could be rate limit due to opening DMs too fast
            # Discord returns 400 instead of 429 in such case
            if not retry:
                await interaction.followup.send('Bot invite will be sent to your DMs in a few moments..', ephemeral=True)
                log.warning(f'Rate limited while attempting to open DM for: {interaction.user.id} initialized.')
            else:
                log.warning(f'Rate limited while attempting to open DM for: {interaction.user.id} after {retry * 5}s cooldown.')
            await asyncio.sleep(5)
            return await self.callback(interaction, retry=retry + 1)

    @staticmethod
    def embed():
        return discord.Embed(
            title='Bot Invite',
            description='Click on the button below to add the bot to your server.\n-# Note: administrator permissions are required in order to add the bot.',
            color=discord.Color.green()
        )


class InviteNoadminButton(ui.View):
    def __init__(self, bot_id: int):
        super().__init__(timeout=None)
        self.bot_id = bot_id
        button = ui.Button(
            label='🤖 Add Bot',
            style=discord.ButtonStyle.primary,
            custom_id=f'button_{bot_id}'
        )
        button.callback = self.callback
        self.add_item(button)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            message = await interaction.user.send(
                embed=self.embed(),
                view=DmButton(self.bot_id, user_intall=True),
                delete_after=60
            )
            await interaction.followup.send(
                embed=discord.Embed(
                    title='Success!',
                    description=f'{check} The bot invite has been sent to your DMs {message.jump_url}!',
                    color=discord.Color.blue()
                ),
                ephemeral=True
            )
        
        except discord.Forbidden:
            await interaction.followup.send(
                embed=discord.Embed(
                    title='Error',
                    description=f'{cross} Please enable your DMs in order to get the invite.'
                ),
                ephemeral=True
            )

    @staticmethod
    def embed():
        return discord.Embed(
            title='No-admin Bot Invite',
            description='Click on the button below to add the bot to your account.',
            color=discord.Color.green()
        )


class HelpMenu(ui.View):
    def __init__(self, embed: discord.Embed, fields: list[dict]):
        super().__init__(timeout=None)
        self.embed = embed
        self.batches: list[list[dict]] = []
        self.page = 1
        self.per_page = 10
        for i in range(0, len(fields), self.per_page):
            self.batches.append(fields[i:i+self.per_page])
        self._update()

    @ui.button(label='⏮️ Previous Page', custom_id='button_previous')
    async def button_previous(self, interaction: discord.Interaction, _):
        self.page -= 1
        await self.update(interaction)

    @ui.button(label='Next Page ⏭️', custom_id='button_next')
    async def button_next(self, interaction: discord.Interaction, _):
        self.page += 1
        await self.update(interaction)

    def _update(self):
        if self.page == len(self.batches):
            self.button_next.disabled = True
            self.button_previous.disabled = False
        elif self.page == 1:
            self.button_next.disabled = False
            self.button_previous.disabled = True
        else:
            self.button_previous.disabled = False
            self.button_next.disabled = False
        
        self.embed.clear_fields()
        for field in self.batches[self.page - 1]:
            self.embed.add_field(name=field['name'], value=field['value'], inline=field['inline'])
        self.embed.set_footer(icon_url=server_icon,text=f'Page {self.page}/{len(self.batches)} | Powered by {p_name} V{__version__}')

    async def update(self, interaction: discord.Interaction) -> None:
        self._update()
        await interaction.response.edit_message(embed=self.embed, view=self)


class Buttons(ui.View):
    def __init__(self, *buttons: TButton):
        super().__init__(timeout=None)
        for _button in buttons:
            button = ui.Button(
                label=_button['label'],
                style=_button['style'],
                custom_id=_button['custom_id']
            )
            async def callback(interaction: discord.Interaction, button=button, data=_button):
                await _button['callback'](self, interaction, button)
            button.callback = callback
            self.add_item(button)


class SpamView(ui.View):
    interactions: List[discord.Interaction]

    def __init__(self, user: Optional[User]):
        super().__init__(timeout=None)
        self.queue = queue.Queue()
        self.settings = user and user.settings.no_admin or None
        self.interactions = []
        self.workers = 20
        self.stopped = False
        self.embed = discord.Embed(
            title='Panel',
            description='Click "+5 messages" if you want to make the bot send more messages. Click "Fire" to start spamming.'
        )
        self.update_queue()
        self.embed.set_footer(text=f'Powered by {p_name} V{__version__}', icon_url=server_icon)

    def update_queue(self):
        self.embed.clear_fields()
        # +5 in button_fire
        self.embed.add_field(name='Queue', value=f'{len(self.interactions) * 5 + 5} messages will be sent.')

    def get_followup(self, interactions: List[discord.Interaction]) -> Generator[discord.Webhook, None, None]:
        for interaction in interactions[:]:
            for _ in range(5):
                yield interaction.followup
            interactions.remove(interaction)

    def send_message(self, followup: discord.Webhook):
        session = requests.Session()
        # Make session be able to handle self.workers concurrent requests
        adapter = HTTPAdapter(pool_connections=self.workers, pool_maxsize=self.workers)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        # Expired 🥀
        # session.proxies.update(shared.config['proxy'])
        settings = self.settings
        assert settings, '???'
        data = {
            'content': settings.content,
            'tts': settings.tts,
            'embeds': [settings.embed.to_dict()] if settings.embed else []
        }
        if self.stopped:
            return
        response = session.post(f'https://discord.com/api/v10/webhooks/{followup.id}/{followup.token}', json=data)
        if response.status_code == 429:
            json = response.json()
            retry_after = json.get('retry_after')
            self.queue.put((followup, int(retry_after)))

    def consume(self):
        while True:
            try:
                followup, retry_after = self.queue.get(timeout=5)
            except queue.Empty:
                break
            if self.stopped:
                break
            sleep(retry_after)
            self.send_message(followup)
            self.queue.task_done()

    async def disable(self, interaction: discord.Interaction):
        self.button_add.disabled = True
        self.button_fire.disabled = True
        self.button_stop.disabled = True
        await interaction.response.edit_message(view=self)

    @ui.button(label='+5 messages', custom_id='plus_5_messages')
    async def button_add(self, interaction: discord.Interaction, _):
        if not self.settings:
            return await self.disable(interaction)
        self.interactions.append(interaction)
        self.update_queue()
        await interaction.response.edit_message(embed=self.embed)
        if len(self.interactions) >= 100:
            self.button_add.disabled = True
            await interaction.response.edit_message(embed=self.embed, view=self)

    @ui.button(label='🔥FIRE', custom_id='fire')
    async def button_fire(self, interaction: discord.Interaction, _):
        if not self.settings:
            return await self.disable(interaction)
        self.stopped = False
        interactions = self.interactions.copy()
        self.interactions.clear()
        asyncio.create_task(
            interaction.response.edit_message(embed=self.embed, view=self)
        )
        interactions.append(interaction)
        executor = ThreadPoolExecutor(max_workers=self.workers)
        for followup in self.get_followup(interactions):
            executor.submit(
                self.send_message,
                followup
            )
        executor.submit(self.consume)

    @ui.button(label='🛑Stop', custom_id='button_stop')
    async def button_stop(self, interaction: discord.Interaction, _):
        if not self.settings:
            return await self.disable(interaction)
        await interaction.response.defer(ephemeral=True)
        self.interactions.clear()
        self.stopped = True
        with self.queue.mutex:
            self.queue.queue.clear()