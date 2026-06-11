"""Event platform: door / call events pushed via the device Action URL."""

from __future__ import annotations

import logging

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AkuvoxConfigEntry
from .const import EVENT_TYPES, SIGNAL_AKUVOX_EVENT
from .entity import build_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkuvoxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the door event entity."""
    async_add_entities([AkuvoxDoorEvent(entry)])


class AkuvoxDoorEvent(EventEntity):
    """A single event entity carrying all Action URL events from the device."""

    _attr_has_entity_name = True
    _attr_name = "Doorbell"
    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types = EVENT_TYPES

    def __init__(self, entry: AkuvoxConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_event"
        self._attr_device_info = build_device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_AKUVOX_EVENT}_{self._entry.entry_id}",
                self._handle_event,
            )
        )

    @callback
    def _handle_event(self, payload: dict) -> None:
        event_type = payload.get("event", "call")
        if event_type not in EVENT_TYPES:
            # Unknown events are surfaced as a generic "call" so nothing is lost.
            event_type = "call"
        self._trigger_event(event_type, payload.get("data", {}))
        self.async_write_ha_state()
