"""Small async client for the read-only parts of the SwitcheOn API."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import API_BASE


class SwitcheOnApiError(Exception):
    """API request failed."""


class SwitcheOnApi:
    """API client; credentials are kept in memory and login is renewed as needed."""

    def __init__(self, session: ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._user_id: str | None = None
        self._token: str | None = None
        self.account: dict[str, Any] = {}

    async def _login(self) -> None:
        try:
            async with self._session.post(
                f"{API_BASE}/User",
                data={"Email": self._email, "UserPassword": self._password},
            ) as response:
                if response.status == 401:
                    raise SwitcheOnApiError("invalid_auth")
                response.raise_for_status()
                result = await response.json()
        except (ClientError, ValueError) as err:
            raise SwitcheOnApiError("cannot_connect") from err
        self._user_id = result["userIdBin"]
        self._token = result["token"]

    async def async_get_boxes(self) -> list[dict[str, Any]]:
        """Return account boxes, logging in again if the token was rejected."""
        for attempt in range(2):
            if self._token is None or self._user_id is None:
                await self._login()
            try:
                async with self._session.get(
                    f"{API_BASE}/User",
                    params={"UserIdBin": self._user_id, "UserSecret": self._token},
                ) as response:
                    if response.status == 404 and attempt == 0:
                        self._token = None
                        continue
                    response.raise_for_status()
                    payload = await response.json()
            except (ClientError, ValueError) as err:
                raise SwitcheOnApiError("cannot_connect") from err
            self.account = {
                "email": payload.get("email"),
                "firstname": payload.get("firstname"),
                "lastname": payload.get("lastname"),
            }
            return payload.get("boxes", [])
        raise SwitcheOnApiError("invalid_auth")

    async def async_set_channel(self, box: dict[str, Any], channel: int, turn_on: bool) -> int:
        """Queue a complete channel state with one bit changed and return it."""
        current = box.get("pendingStatus")
        if current is None:
            current = box.get("currentStatus") or 0
        bit = 1 << channel
        requested = current | bit if turn_on else current & ~bit
        try:
            async with self._session.put(
                f"{API_BASE}/req",
                json={
                    "userIdBin": self._user_id,
                    "userSecret": self._token,
                    "boxIdBin": box["boxIdBin"],
                    "requestedStatus": requested,
                },
            ) as response:
                if response.status == 401:
                    self._token = None
                    await self._login()
                    return await self.async_set_channel(box, channel, turn_on)
                response.raise_for_status()
        except (ClientError, ValueError) as err:
            raise SwitcheOnApiError("cannot_connect") from err
        return requested

    async def async_listen(self, on_update) -> None:
        """Connect to SignalR JSON protocol and forward box check-ins."""
        if self._token is None or self._user_id is None:
            await self._login()
        async with self._session.ws_connect("https://www.switcheon.com/api/userhub", heartbeat=None) as ws:
            await ws.send_str('{"protocol":"json","version":1}\x1e')
            handshake = await ws.receive(timeout=15)
            if handshake.type.name != "TEXT" or '"error"' in handshake.data:
                raise SwitcheOnApiError("websocket_handshake_failed")
            await ws.send_str(json.dumps({
                "type": 1,
                "invocationId": "1",
                "target": "registerConnectionSecure",
                "arguments": [self._user_id, self._token],
            }) + "\x1e")
            registered = False
            while True:
                try:
                    message = await ws.receive(timeout=15)
                except asyncio.TimeoutError:
                    await ws.send_str('{"type":6}\x1e')
                    continue
                if message.type.name in ("CLOSED", "CLOSE", "ERROR"):
                    return
                if message.type.name != "TEXT":
                    continue
                for item in message.data.split("\x1e"):
                    if not item:
                        continue
                    payload = json.loads(item)
                    if payload.get("type") == 3 and payload.get("invocationId") == "1":
                        if payload.get("error"):
                            raise SwitcheOnApiError("websocket_registration_failed")
                        registered = True
                    elif payload.get("type") == 6:
                        await ws.send_str('{"type":6}\x1e')
                    elif payload.get("type") == 7:
                        return
                    elif payload.get("type") == 1 and payload.get("target") == "updateFromServer":
                        if not registered:
                            continue
                        raw = payload.get("arguments", [None])[0]
                        update = json.loads(raw) if isinstance(raw, str) else raw
                        if isinstance(update, dict) and "req" not in update and update.get("BoxIdBin"):
                            on_update(update)
