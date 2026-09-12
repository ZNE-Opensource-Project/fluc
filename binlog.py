import asyncio
import threading
import shared
import orjson
from random import randint
from pymysqlreplication import BinLogStreamReader
from pymysqlreplication import row_event
from user import User, AuthData, Settings
from typing import Union, Coroutine, Any, Optional
from concurrent.futures import Future

db = shared.db

def run(loop: asyncio.AbstractEventLoop, sql: dict):
    def async_run(coro: Coroutine[Any, Any, Any]) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, loop)

    server_id = sql.pop('server')
    unique = randint(1, 2147483547)
    stream = BinLogStreamReader(
        connection_settings=sql,
        blocking=True,
        only_events=[
            row_event.WriteRowsEvent,
            row_event.UpdateRowsEvent,
            row_event.DeleteRowsEvent
        ],
        only_tables=[
            'supers',
            'premium',
            'user_blacklist',
            'server_blacklist',
            'users',
            'auths',
            'settings'
        ],
        server_id=unique if server_id != unique else unique + randint(1, 100)
    )
    for event in stream:
        event: Union[
            row_event.WriteRowsEvent,
            row_event.DeleteRowsEvent,
            row_event.UpdateRowsEvent
        ]
        if event.rows:
            for row in event.rows:
                table = event.table
                if isinstance(event, row_event.UpdateRowsEvent):
                    row = row['after_values']
                    match table:
                        case 'users':
                            future = async_run(db.get_user(row['id']))
                            user: Optional[User] = future.result()
                            if user:
                                # You never know
                                user._data.update(row)
                        case 'auths':
                            future = async_run(db.get_auth(row['id']))
                            auth: Optional[AuthData] = future.result()
                            if auth:
                                auth._data.update(row)
                        case 'settings':
                            future = async_run(db._cache.get_user(row['id']))
                            user: Optional[User] = future.result()
                            if user:
                                decoded = orjson.loads(row['data'])
                                if user._settings:
                                    user._settings.update(decoded)
                                else:
                                    settings = Settings.default()._data
                                    settings.update(decoded)
                                    user._settings = settings
                else:
                    row = row['values']
                if isinstance(event, row_event.WriteRowsEvent):
                    match table:
                        case 'supers':
                            async_run(db._cache.add_super(row['id'], row['expires']))
                        case 'premium':
                            async_run(db._cache.add_premium(row['id'], row['expires'] or None))
                        case 'user_blacklist':
                            async_run(db._cache.add_user_blacklist(row['id'], row['expires']))
                        case 'server_blacklist':
                            async_run(db._cache.add_server_blacklist(row['id'], row['expires']))
                        case 'users':
                            async_run(db.get_user(row['id']))
                        case 'auths':
                            async_run(db.get_auth(row['id']))
                        case 'settings':
                            async_run(db.get_settings(row['id']))
                elif isinstance(event, row_event.DeleteRowsEvent):
                    match table:
                        case 'supers':
                            async_run(db._cache.remove_super(row['id']))
                        case 'premium':
                            async_run(db._cache.remove_premium(row['id']))
                        case 'user_blacklist':
                            async_run(db._cache.remove_user_blacklist(row['id']))
                        case 'server_blacklist':
                            async_run(db._cache.remove_server_blacklist(row['id']))
                        case 'users':
                            async_run(db._cache.remove_user(row['id']))
                        case 'auths':
                            async_run(db._cache.remove_auth(row['id']))
                        case 'settings':
                            future = async_run(db._cache.get_user(row['id']))
                            user: Optional[User] = future.result()
                            if user:
                                user._settings = {}

def get_thread(loop: asyncio.AbstractEventLoop, sql_config: dict) -> threading.Thread:
    return threading.Thread(target=run, args=(loop, sql_config), daemon=True)