import random
import asyncio
import logging
import uuid
import re
import time
import struct
import aiohttp
import base64
import orjson
import traceback
from datetime import datetime
from discord.ext import commands
from session import HTTPSession, Request

log = logging.getLogger(__name__)

class IDGenerator:
    def __init__(self):
        self.prefix = random.randint(0, 0xFFFFFFFF) & 0xFFFFFFFF
        self.creation_time = int(time.time() * 1000)
        self.sequence = 0

    def client_uuid(self, user_id: int = 0):
        uuid = bytearray(24)
        # Lowest signed 32 bits
        struct.pack_into("<I", uuid, 0, user_id & 0xFFFFFFFF)
        struct.pack_into("<I", uuid, 4, user_id >> 32)
        struct.pack_into("<I", uuid, 8, self.prefix)
        # Lowest signed 32 bits
        struct.pack_into("<I", uuid, 12, self.creation_time & 0xFFFFFFFF)
        struct.pack_into("<I", uuid, 16, self.creation_time >> 32)
        struct.pack_into("<I", uuid, 20, self.sequence)
        self.sequence += 1
        return base64.b64encode(uuid).decode("utf-8")


class Bot:
    def __init__(self, invite_code: str, token: str, bot: commands.Bot, **options) -> None:
        self.generator = IDGenerator()
        self.invite_code = invite_code
        self.token = token
        self.bot = bot
        self.client_launch_id = str(uuid.uuid4())
        self.client_heartbeat_session_id = str(uuid.uuid4())
        self.client_launch_signature = self._generate_launch_signature()
        asyncio.create_task(self._heartbeat_thread())
        self.bot.event(self.on_ready)
        self.session = HTTPSession(**options, http_options=[
            self.client_launch_id,
            self.client_launch_signature,
            self.client_heartbeat_session_id
        ])

    def _generate_launch_signature(self) -> str:
        bits = 0b00000000100000000001000000010000000010000001000000001000000000000010000010000001000000000100000000000001000000000000100000000000

        # Force all bits to 0
        random_uuid = uuid.uuid4().int & (~bits & ((1 << 128) - 1))
        result = uuid.UUID(int=random_uuid)
        return str(result)

    async def _heartbeat_thread(self):
        while True:
            await asyncio.sleep(30 * 60)
            self.client_heartbeat_session_id = uuid.uuid4()

    async def on_ready(self):
        try:
            assert self.bot.user
            print(f'connected (session: {self.bot.ws.session_id})')
            self.client_uuid = self.generator.client_uuid(self.bot.user.id)
            resp = await self.session.request(
                Request('GET', f'api/v9/invites/{self.invite_code}?inputValue={self.invite_code}&with_counts=true&with_expiration=true&with_permissions=true'),
                authorization=self.token
            )
            try:
                json = await resp.json()
            except ValueError:
                return
            
            _x_context_propertes = {
                "location":"Join Guild",
                "location_guild_id": json['guild_id'],
                "location_channel_id": json['channel']['id'],
                "location_channel_type": json['channel']['type']
            }
            x_content_propertes = base64.b64encode(orjson.dumps(_x_context_propertes)).decode()
            headers = {
                'x-context-propertes': x_content_propertes
            }
            await asyncio.sleep(1)
            print('Joining')
            await self.session.request(
                Request('POST', f'api/v9/invites/{self.invite_code}', {
                    'session_id': self.bot.ws.session_id
                }), headers, authorization=self.token)
        except Exception:
            print(traceback.format_exc())
        finally:
            await self.bot.close()
            
    async def start(self):
        print('starting')
        async with self.session:
            await self.bot.start(self.token)