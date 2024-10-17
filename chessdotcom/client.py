import asyncio
import time
import warnings
from functools import wraps

import requests
from aiohttp import ClientSession

from .types import ChessDotComError, ChessDotComResponse


class RateLimitHandler(object):
    """
    Rate Limit Handler for handling 429 responses from the API.

    :tts: The time the client will wait after a 429 response if there are tries remaining.
    :retries: The number of times the client will retry calling the API after the first attempt.
    """

    def __init__(self, tts=0, retries=1):
        self.tts = tts
        self.retries = retries

    @property
    def retries(self):
        return self._retries

    @retries.setter
    def retries(self, retries):
        if retries < 0:
            warnings.warn(
                "Number of retries can not be less than 0. Setting value to 0."
            )
            retries = 0
        self._retries = retries

    def should_try_again(self, status_code, resource):
        if status_code == 429 and self.retries - resource.times_requested >= 0:
            time.sleep(self.tts)
            return True
        return False


class Client:
    """
    Client for Chess.com Public API. The client is only responsible for making calls.

    :ivar default_request_options: Dictionary containing extra keyword arguments for
        requests to the API (headers, proxy, etc).
    :ivar aio: Determines if the functions behave asynchronously.
    :ivar rate_limit_handler: A RateLimitHandler object.
        See :obj:`chessdotcom.client.RateLimitHandler`.
    :loop_callback: Function that returns the current loop for aiohttp.ClientSession.
    """

    aio = False
    default_request_options = {"headers": {}}
    request_config = default_request_options  # to maintain backwards compadibility

    rate_limit_handler = RateLimitHandler(tts=0, retries=1)
    endpoints = []

    @classmethod
    def endpoint(cls, func):
        cls.endpoints.append(func)

        return cls().activate_endpoint(func)

    @staticmethod
    def loop_callback():
        return asyncio.get_running_loop()

    def do_get_request(self, resource):
        if resource.tts:
            time.sleep(resource.tts)

        _do_get_request = (
            self._do_async_get_request if self.aio else self._do_sync_get_request
        )

        return _do_get_request(resource)

    def activate_endpoint(self, endpoint):
        @wraps(endpoint)
        def wrapper(*args, **kwargs):
            return self.do_get_request(endpoint(*args, **kwargs))

        setattr(self, endpoint.__name__, wrapper)
        return wrapper

    def _build_request_options(self, resource):
        options = {**resource.request_config, **self.default_request_options}

        if "user-agent" not in [header.lower() for header in options["headers"].keys()]:
            warnings.warn(
                "Calls to api.chess.com require an updated 'User-Agent' header. "
                "You can update this with something like "
                "chessdotcom.Client.request_config['headers']['User-Agent'] "
                "= 'My Python Application. Contact me at email@example.com'"
            )

        return options

    def _do_sync_get_request(self, resource):
        r = requests.get(**self._build_request_options(resource), timeout=30)
        resource.times_requested += 1

        if r.status_code != 200:
            if self.rate_limit_handler.should_try_again(r.status_code, resource):
                return self._do_sync_get_request(resource)
            raise ChessDotComError(
                status_code=r.status_code, response_text=r.text, headers=r.headers
            )
        return ChessDotComResponse(r.text, resource.top_level_attr, resource.no_json)

    async def _do_async_get_request(self, resource):
        async with ClientSession(loop=self.loop_callback()) as session:
            async with session.get(**self._build_request_options(resource)) as r:
                text = await r.text()
                resource.times_requested += 1

                if r.status != 200:
                    if self.rate_limit_handler.should_try_again(r.status, resource):
                        return await self._do_async_get_request(resource)
                    raise ChessDotComError(
                        status_code=r.status, response_text=text, headers=r.headers
                    )
                return ChessDotComResponse(
                    text, resource.top_level_attr, resource.no_json
                )


class ChessDotComClient(Client):
    def __init__(
        self,
        aio: bool = False,
        request_options: dict = None,
        rate_limit_handler: RateLimitHandler = None,
    ) -> None:
        self.aio = aio
        self.request_config = request_options or self.request_config
        self.rate_limit_handler = rate_limit_handler or RateLimitHandler(
            tts=0, retries=1
        )
        for endpoint in self.endpoints:
            self.activate_endpoint(endpoint)
