"""Binary sensor platform: device connectivity."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AkuvoxConfigEntry
from .entity import build_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkuvoxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the connectivity sensor."""
    async_add_entities([AkuvoxConnectivitySensor(entry)])


class AkuvoxConnectivitySensor(CoordinatorEntity, BinarySensorEntity):
    """Reports whether the door phone is reachable on the network."""

    _attr_has_entity_name = True
    _attr_name = "Connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: AkuvoxConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator)
        self._attr_unique_id = f"{entry.entry_id}_connectivity"
        self._attr_device_info = build_device_info(entry)

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data)

    @property
    def available(self) -> bool:
        # Connectivity itself is always available; it just reports on/off.
        return True
