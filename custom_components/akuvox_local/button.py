"""Button platform: one 'Open' button per relay."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AkuvoxConfigEntry
from .api import AkuvoxError
from .const import CONF_RELAY_COUNT, DEFAULT_RELAY_COUNT, RELAY_LABELS
from .entity import build_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkuvoxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a button for each configured relay."""
    relay_count = entry.data.get(CONF_RELAY_COUNT, DEFAULT_RELAY_COUNT)
    entities = [
        AkuvoxRelayButton(entry, door_num)
        for door_num in range(1, relay_count + 1)
    ]
    async_add_entities(entities)


class AkuvoxRelayButton(CoordinatorEntity, ButtonEntity):
    """Pressing the button triggers the relay and opens the door."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:door-open"

    def __init__(self, entry: AkuvoxConfigEntry, door_num: int) -> None:
        super().__init__(entry.runtime_data.coordinator)
        self._entry = entry
        self._client = entry.runtime_data.client
        self._door_num = door_num
        label = RELAY_LABELS.get(door_num, str(door_num))
        self._attr_name = f"Open Relay {label}"
        self._attr_unique_id = f"{entry.entry_id}_relay_{door_num}"
        self._attr_device_info = build_device_info(entry)

    @property
    def available(self) -> bool:
        return bool(self.coordinator.data)

    async def async_press(self) -> None:
        try:
            await self._client.async_open_door(self._door_num)
        except AkuvoxError as err:
            raise HomeAssistantError(f"Failed to open door: {err}") from err
