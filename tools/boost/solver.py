import requests
import time
import aiohttp
import asyncio
import ssl


# https://www.razorcap.cc/docs
class RazorCapClient:
    """Clean wrapper for RazorCap API"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.razorcap.cc"
    
    def solve_hcaptcha(
        self, 
        sitekey: str, 
        siteurl: str, 
        proxy: str,
        # Let's not edit external code, supress errors instead
        rqdata: str = None # type: ignore
    ) -> str:
        """
        Solve hCaptcha challenge
        
        Args:
            sitekey: The site key from the target website
            siteurl: The URL where the captcha is displayed
            proxy: Proxy in format 'http://user:pass@host:port'
            rqdata: Optional rqdata parameter
            
        Returns:
            The response key to submit
        """
        payload = {
            'key': self.api_key,
            'type': 'hcaptcha',
            'data': {
                'sitekey': sitekey,
                'siteurl': siteurl,
                'proxy': proxy,
                'rqdata': rqdata
            }
        }
        
        # Create task
        response = requests.post(
            f'{self.base_url}/tasks/create_task',
            json=payload
        )
        response.raise_for_status()
        task_id = response.json()["task_id"]
        
        # Poll for result
        while True:
            result = requests.get(
                f'{self.base_url}/tasks/get_result/{task_id}'
            )
            result.raise_for_status()
            data = result.json()
            
            if data["status"] == "success":
                return data['response_key']
            elif data["status"] == "pending":
                time.sleep(1)
            else:
                raise Exception(f"Task failed: {data}")
            

class AsyncRazorCapClient:
    """Clean wrapper for RazorCap API"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.razorcap.cc"
        self.__session: aiohttp.ClientSession | None = None

    async def solve_hcaptcha(
        self, 
        sitekey: str, 
        siteurl: str, 
        proxy: str,
        rqdata: str | None = None
    ) -> str:
        """
        Solve hCaptcha challenge
        
        Args:
            sitekey: The site key from the target website
            siteurl: The URL where the captcha is displayed
            proxy: Proxy in format 'http://user:pass@host:port'
            rqdata: Optional rqdata parameter
            
        Returns:
            The response key to submit
        """
        if not self.__session or self.__session.closed:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            self.__session = aiohttp.ClientSession(self.base_url, connector=connector)
            self.__session.headers['content-type'] = 'application/json'

        payload = {
            'key': self.api_key,
            'type': 'hcaptcha',
            'data': {
                'sitekey': sitekey,
                'siteurl': siteurl,
                'proxy': proxy,
                'rqdata': rqdata
            }
        }
        
        # Create task
        response = await self.__session.post(
            f'{self.base_url}/tasks/create_task',
            json=payload
        )
        response.raise_for_status()
        json = await response.json()
        task_id = json["task_id"]
        
        # Poll for result
        while True:
            result = await self.__session.get(
                f'{self.base_url}/tasks/get_result/{task_id}'
            )
            result.raise_for_status()
            data = await result.json()
            
            if data["status"] == "success":
                return data['response_key']
            elif data["status"] == "pending":
                await asyncio.sleep(1)
            else:
                raise Exception(f"Task failed: {data}")
            
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc, tb):
        if self.__session and not self.__session.closed:
            await self.__session.close()

class AsyncOnyxClient:
    """Clean wrapper for RazorCap API"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://onyxsolver.io/"
        self.__session: aiohttp.ClientSession | None = None

    async def solve_hcaptcha(
        self, 
        sitekey: str, 
        siteurl: str, 
        proxy: str,
        rqdata: str | None = None
    ) -> str:
        """
        Solve hCaptcha challenge
        
        Args:
            sitekey: The site key from the target website
            siteurl: The URL where the captcha is displayed
            proxy: Proxy in format 'http://user:pass@host:port'
            rqdata: Optional rqdata parameter
            
        Returns:
            The response key to submit
        """
        if not self.__session or self.__session.closed:  
            self.__session = aiohttp.ClientSession(self.base_url)
            self.__session.headers['content-type'] = 'application/json'

        payload = {
            'clientKey': self.api_key,
            'task': {
                'type': 'PopularCaptchaTask',
                'websiteKey': sitekey,
                'websiteURL': siteurl,
                'proxy': proxy,
                'rqdata': rqdata
            }
        }
        print(payload)
        # Create task
        response = await self.__session.post(
            '/api/createTask',
            json=payload
        )
        print(f'Create task returned : {await response.text()}')
        response.raise_for_status()
        json = await response.json()
        if not json.get('taskId'):
            raise Exception
        task_id = json["taskId"]
        
        # Poll for result
        while True:
            result = await self.__session.post(
                '/api/getTaskResult',
                json={
                    'clientKey': self.api_key,
                    'taskId': task_id
                },
                timeout=aiohttp.ClientTimeout(60, 3)
            )
            result.raise_for_status()
            data = await result.json()
            
            if data["status"] == "ready":
                return data['solution']['gRecaptchaResponse']
            elif data["status"] == "processing":
                await asyncio.sleep(2)
            else:
                raise Exception(f"Task failed: {data}")
            
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc, tb):
        if self.__session and not self.__session.closed:
            await self.__session.close()


# # Usage
# client = RazorCapClient(api_key="your-api-key")
# key = client.solve_hcaptcha(
#     sitekey="a9b5fb07-92ff-493f-86fe-352a2803b3df",
#     siteurl="discord.com",
#     proxy="http://user:pass@host:port",
#     rqdata="optional-rqdata"
# )
# print(f"Solution: {key}")