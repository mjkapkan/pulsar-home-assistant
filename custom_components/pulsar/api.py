"""Client for the Pulsar agent API (enroll + heartbeat)."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)


class PulsarError(Exception):
    """Pulsar answered with an error."""


class PulsarConnectionError(PulsarError):
    """Pulsar could not be reached."""


class PulsarAuthError(PulsarError):
    """Pulsar no longer accepts this installation's key."""


class PulsarInvalidCode(PulsarError):
    """The pairing code is unknown, used or expired."""


class PulsarClient:
    """Talks to Pulsar. Every request starts from Home Assistant."""

    def __init__(self, session: aiohttp.ClientSession, url: str, api_key: str | None = None) -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._api_key = api_key

    async def enroll(self, **fields: Any) -> dict[str, Any]:
        """Exchange a pairing code for this installation's key."""
        return await self._post("/api/agent/v1/enroll", fields, authenticated=False)

    async def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Report entities and results; receive targets and commands."""
        return await self._post("/api/agent/v1/heartbeat", payload, authenticated=True)

    async def _post(self, path: str, payload: dict[str, Any], authenticated: bool) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._api_key}"} if authenticated else {}
        try:
            async with self._session.post(
                f"{self._url}{path}", json=payload, headers=headers, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status == 401:
                    raise PulsarAuthError("unauthorized")
                if resp.status == 403 and not authenticated:
                    raise PulsarInvalidCode("invalid_or_expired_code")
                if resp.status >= 400:
                    raise PulsarError(f"Pulsar answered HTTP {resp.status}")
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise PulsarConnectionError(str(err) or type(err).__name__) from err
        if not isinstance(data, dict):
            raise PulsarError("Unexpected response from Pulsar")
        return data
