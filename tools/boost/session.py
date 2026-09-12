import aiohttp
import asyncio
import re
import orjson
import uuid
import random
import traceback
from aiohttp.client import _RequestOptions
from base64 import b64encode
from solver import AsyncOnyxClient
from typing import Literal, Iterator, Unpack


class Request:
    def __init__(self, method: Literal['GET', 'POST', 'PATCH', 'PUT'], path: str, json: dict | list | None = None):
        self.json = json
        self.method = method
        self.path = path
        

class HTTPSession:
    def __init__(self, base: str, razorcap_api_key: str, proxygen: Iterator[str], *, tries: int = 5, http_options: list[str]) -> None:
        self._BASE = base
        if not base.endswith('/'):
            self._BASE += '/'
        self._tries = tries
        self._proxygen = proxygen
        self.__session: aiohttp.ClientSession | None = None
        self.__onyx: AsyncOnyxClient | None = None
        self.__razorcap_api_key: str = razorcap_api_key
        self.http_options = http_options
        print(http_options, )

    async def _init_session(self):
        self.__session = aiohttp.ClientSession(self._BASE)
        self.__onyx = AsyncOnyxClient(self.__razorcap_api_key)

        safe_headers = {
            "accept-language": "en-US,en;q=0.9,de-DE;q=0.8,de;q=0.6",
            "authorization": '...',
            "dnt": "1",
            "origin": str(self.__session._base_url_origin),
            "priority": "u=1, i",
            "referer": '...',
            "sec-ch-ua": "\"Not:A-Brand\";v=\"99\", \"Google Chrome\";v=\"145\", \"Chromium\";v=\"145\"",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"Windows\"",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            "x-debug-options": "bugReporterEnabled",
            "x-discord-locale": "en-US",
            "x-discord-timezone": "America/Los_Angeles",
            # Used in most requests
            'content-type': 'application/json'
        }
        self.__session.headers.update(safe_headers)
        # Set cookies
        response = await self.request(Request('GET', 'channels/@me'))
        content = await response.text()
        challenge = re.sub(r".*r:'([^']+)'*", r"\1", content, flags=re.DOTALL)
        build_number = re.sub(r'.*BUILD_NUMBER":"(\d+)".*', r'\1', content, flags=re.DOTALL)
        self.build_number = build_number
        self.__session.headers[ "x-super-properties"] = await self._get_x_super_properties()
        print(dict(self.__session.headers))


    async def _get_x_super_properties(self) -> str:
        if not self.__session or self.__session.closed:
            raise NotImplementedError()
        
        async with self.__session.get('https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions.json') as response:
            try:
                json = await response.json()
                browser_version = json['channels']['Stable']['version']
            except Exception:
                browser_version = "145.0.0.0"

        data = {
            "os":"Windows",
            "browser":"Chrome",
            "device":"",
            "system_locale":"en-US",
            "has_client_mods":False,
            "browser_user_agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            "browser_version": browser_version,
            "os_version":"10",
            "referrer":"",
            "referring_domain":"",
            "referrer_current":"",
            "referring_domain_current":"",
            "release_channel":"stable",
            "client_build_number": self.build_number,
            "client_event_source": str(uuid.uuid4()),
            "client_launch_id": self.http_options[0],
            "launch_signature": self.http_options[1],
            "client_heartbeat_session_id": self.http_options[2],
            "client_app_state":"focused"
        }
        return b64encode(orjson.dumps(data)).decode()

    async def request(self, request: Request, headers_: dict | None = None, authorization: str | None = None, **options: Unpack[_RequestOptions]) -> aiohttp.ClientResponse:
        captcha_data: dict | None = None
        if not self.__session or not self.__onyx:
            raise NotImplementedError()
        for i in range(self._tries):
            if i:
                await asyncio.sleep(random.randint(1, 2))
            headers = {
                'authorization': authorization or None,
                'referer': self._BASE + request.path
            }
            if not headers.get('authorization'):
                headers.pop('authorization')
            if captcha_data:
                headers.update(captcha_data)
            if headers_:
                headers.update(headers_)
            options.update(json=request.json, headers=headers)
            _resp = None
            response = await self.__session.request(request.method, request.path, **options)
            print(response.status)
            print(await response.text())
            try:
                print(await response.json())
            except Exception:
                pass
            if response.ok:
                _resp = response
            if response.status == 400:
                # Possible captcha
                try:
                    json = await response.json()
                    if 'captcha_key' in json:
                        try:
                            x_captcha_key = await self.__onyx.solve_hcaptcha(
                                json['captcha_sitekey'],
                                'https://discord.com',
                                next(self._proxygen),
                                json['captcha_rqdata']
                            )
                            print(f'got key: {x_captcha_key}')
                            captcha_data = {
                                'x-captcha-key': x_captcha_key,
                                'x-captcha-rqtoken': json['captcha_rqtoken']
                            }
                        except Exception:
                            print(f'exc: {traceback.format_exc()}')
                            pass
                        continue
                except ValueError:
                    pass
            if response.status == 429:
                try:
                    json = await response.json()
                    retry_after = float(json['retry_after'])
                    await asyncio.sleep(retry_after)
                    continue
                except (ValueError, KeyError):
                    pass
            response.raise_for_status()
            if _resp:
                return _resp
        # Should be unreachable
        return NotImplemented
                        

    async def close(self):
        if self.__session and not self.__session.closed:
            await self.__session.close()

    async def __aenter__(self):
        await self._init_session()
        if not self.__onyx:
            # Unreacable
            raise NotImplementedError()
        async with self.__onyx:
            return self
    
    async def __aexit__(self, exc_type, exc, tb):
        await self.close()