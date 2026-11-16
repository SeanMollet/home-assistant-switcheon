"""SwitcheOn box sensors."""

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SwitcheOnCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: SwitcheOnCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        entity
        for box in coordinator.data
        for entity in (SwitcheOnTemperatureSensor(coordinator, box),)
    )


class SwitcheOnBoxEntity(CoordinatorEntity[SwitcheOnCoordinator]):
    """Base entity for one box."""

    def __init__(self, coordinator: SwitcheOnCoordinator, box: dict) -> None:
        super().__init__(coordinator)
        self._box_id = box["boxIdText"]
        self._initial_box = box
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._box_id)},
            name=box.get("location") or "SwitcheOn box",
            manufacturer="SwitcheOn",
            model=box.get("deviceType"),
        )

    @property
    def box(self) -> dict:
        """Latest box data."""
        return next(
            (box for box in self.coordinator.data if box.get("boxIdText") == self._box_id),
            self._initial_box,
        )


class SwitcheOnStatusSensor(SwitcheOnBoxEntity, SensorEntity):
    """Reported channel bitmask, with channel names and pending state as attributes."""

    _attr_has_entity_name = True
    _attr_name = "Channel status"
    _attr_icon = "mdi:counter"

    @property
    def unique_id(self) -> str:
        return f"{self._box_id}_status"

    @property
    def native_value(self):
        return self.box.get("currentStatus")

    @property
    def extra_state_attributes(self):
        box = self.box
        count = box.get("channels", 0)
        names = box.get("channelNames") or []
        return {
            "account_email": self.coordinator.api.account.get("email"),
            "box_id": self._box_id,
            "location": box.get("location"),
            "device_type": box.get("deviceType"),
            "box_count_for_account": len(self.coordinator.data),
            "channel_names": names,
            "channels_on": [
                names[i] if i < len(names) and names[i] else f"Channel {i + 1}"
                for i in range(count)
                if (box.get("currentStatus", 0) or 0) & (1 << i)
            ],
            "pending_status": box.get("pendingStatus"),
            "signal_strength": box.get("signalStrength"),
        }


class SwitcheOnTemperatureSensor(SwitcheOnBoxEntity, SensorEntity):
    """Reported box temperature."""

    _attr_has_entity_name = True
    _attr_name = "Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE

    @property
    def unique_id(self) -> str:
        return f"{self._box_id}_temperature"

    @property
    def native_unit_of_measurement(self):
        return UnitOfTemperature.CELSIUS if self.box.get("celcius") else UnitOfTemperature.FAHRENHEIT

    @property
    def native_value(self):
        return self.box.get("temp")
