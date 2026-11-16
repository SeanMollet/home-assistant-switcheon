"""Per-channel SwitcheOn switches."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SwitcheOnCoordinator
from .sensor import SwitcheOnBoxEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: SwitcheOnCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SwitcheOnChannelSwitch(coordinator, box, index)
        for box in coordinator.data
        for index in range(int(box.get("channels") or 0))
    )


class SwitcheOnChannelSwitch(SwitcheOnBoxEntity, SwitchEntity):
    """Switch state follows currentStatus; commands remain pending until check-in."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SwitcheOnCoordinator, box: dict, index: int) -> None:
        super().__init__(coordinator, box)
        self._index = index
        names = box.get("channelNames") or []
        self._attr_name = names[index] if index < len(names) and names[index] else f"Channel {index + 1}"
        self._attr_icon = "mdi:toggle-switch"

    @property
    def unique_id(self) -> str:
        return f"{self._box_id}_channel_{self._index + 1}"

    @property
    def is_on(self) -> bool:
        # The API echoes queued requests before the box checks in. Match the
        # app by showing that requested state while it is pending.
        state = self.box.get("pendingStatus")
        if state is None:
            state = self.box.get("currentStatus") or 0
        return bool(state & (1 << self._index))

    @property
    def extra_state_attributes(self):
        return {
            "command_pending": self.box.get("pendingStatus") is not None,
            "pending_status": self.box.get("pendingStatus"),
            "channel_number": self._index + 1,
        }

    async def async_turn_on(self, **kwargs) -> None:
        requested = await self.coordinator.api.async_set_channel(self.box, self._index, True)
        self.coordinator.set_pending_status(self._box_id, requested)

    async def async_turn_off(self, **kwargs) -> None:
        requested = await self.coordinator.api.async_set_channel(self.box, self._index, False)
        self.coordinator.set_pending_status(self._box_id, requested)
