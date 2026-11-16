"""Polling coordinator."""

from datetime import timedelta
import asyncio
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import SwitcheOnApi, SwitcheOnApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class SwitcheOnCoordinator(DataUpdateCoordinator[list[dict]]):
    """Fetch box state at a conservative interval."""

    def __init__(self, hass: HomeAssistant, api: SwitcheOnApi) -> None:
        self.api = api
        self.account = api.account
        self._websocket_task = None
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            name=DOMAIN,
            update_interval=timedelta(minutes=2),
        )

    async def _async_update_data(self) -> list[dict]:
        try:
            return await self.api.async_get_boxes()
        except SwitcheOnApiError as err:
            raise UpdateFailed(str(err)) from err

    def start_websocket(self) -> None:
        """Start/restart the live update connection."""
        if self._websocket_task is None or self._websocket_task.done():
            self._websocket_task = self.hass.async_create_task(self._websocket_loop())

    async def _websocket_loop(self) -> None:
        while True:
            try:
                await self.api.async_listen(self._apply_live_update)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # reconnect on transient API/network failures
                _LOGGER.warning("SwitcheOn live connection lost; reconnecting: %s", err)
            await asyncio.sleep(5)

    def _apply_live_update(self, update: dict) -> None:
        """Merge documented SignalR check-in fields into the matching box."""
        box_id = update.get("BoxIdBin")
        boxes = [dict(box) for box in (self.data or [])]
        for box in boxes:
            if box.get("boxIdBin") != box_id:
                continue
            if update.get("stat") is not None:
                box["currentStatus"] = update["stat"]
                box["pendingStatus"] = None
            if update.get("temp") is not None:
                box["temp"] = update["temp"]
            if update.get("excl") is not None:
                box["channelsExclusive"] = update["excl"]
            if update.get("req") is not None:
                box["pendingStatus"] = update["req"]
            self.async_set_updated_data(boxes)
            return

    def set_pending_status(self, box_id: str, status: int) -> None:
        """Reflect an accepted channel request while the box applies it."""
        boxes = [dict(box) for box in (self.data or [])]
        for box in boxes:
            if box.get("boxIdText") == box_id:
                box["pendingStatus"] = status
                self.async_set_updated_data(boxes)
                return
