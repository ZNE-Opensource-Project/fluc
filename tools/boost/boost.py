import asyncio
import orjson
import bot as client
from discord.ext import commands

with open('config.json') as file:
    config = orjson.loads(file.read())

def proxygen():
    while True:
        yield config['proxy']

options = {
    'base': 'https://discord.com',
    'razorcap_api_key': config['razorcap_api_key'],
    'proxygen': proxygen()
}

async def boost(invite_code: str, auth: str):
    user = commands.Bot(command_prefix='', self_bot=True)
    bot = client.Bot(invite_code, auth, user, **options)
    await bot.start()

async def main():
    await boost('tease', 'MTQ3Nzc3MzY1NTk2MTUwNTgxMg.GqGz51.2sa7zayCpqrAu2RxvxoX2SahlTrxkzdI_d80xM')

asyncio.run(main())