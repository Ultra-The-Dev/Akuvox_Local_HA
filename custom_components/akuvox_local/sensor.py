"""Sensor platform: surface the latest Action URL event for dashboards."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import AkuvoxConfigEntry
from .const import SIGNAL_AKUVOX_EVENT
from .entity import build_device_info

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class AkuvoxSensorDescription:
    """Describes one event-derived sensor."""

    key: str
    name: str
    icon: str | None = None
    device_class: SensorDeviceClass | None = None
    # Given the webhook payload, return the new state (or None to ignore).
    value_fn: Callable[[dict], str | None]


def _last_event_value(payload: dict) -> str | None:
    return payload.get("event")


def _last_card_value(payload: dict) -> str | None:
    data = payload.get("data", {})
    # Action URLs may pass the card code under various keys depending on model.
    for key in ("card", "Card", "CardCode", "code", "rfid"):
        if data.get(key):
            return str(data[key])
    if payload.get("event") in ("valid_card", "invalid_card"):
        return payload.get("event")
    return None


SENSORS: tuple[AkuvoxSensorDescription, ...] = (
    AkuvoxSensorDescription(
        key="last_event",
        name="Last event",
        icon="mdi:bell-ring",
        value_fn=_last_event_value,
    ),
    AkuvoxSensorDescription(
        key="last_card",
        name="Last card",
        icon="mdi:card-account-details",
        value_fn=_last_card_value,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkuvoxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the event sensors."""
    entities: list[SensorEntity] = [
        AkuvoxEventSensor(entry, desc) for desc in SENSORS
    ]
    entities.append(AkuvoxLastEventTimeSensor(entry))
    async_add_entities(entities)


class _AkuvoxBaseSensor(RestoreEntity, SensorEntity):
    """Shared plumbing: subscribe to the webhook dispatcher signal."""

    _attr_has_entity_name = True

    def __init__(self, entry: AkuvoxConfigEntry) -> None:
        self._entry = entry
        self._attr_device_info = build_device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_native_value = last.state
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_AKUVOX_EVENT}_{self._entry.entry_id}",
                self._handle_event,
            )
        )

    @callback
    def _handle_event(self, payload: dict) -> None:
        raise NotImplementedError


class AkuvoxEventSensor(_AkuvoxBaseSensor):
    """A sensor whose value is derived from the latest matching event."""

    def __init__(
        self, entry: AkuvoxConfigEntry, description: AkuvoxSensorDescription
    ) -> None:
        super().__init__(entry)
        self._desc = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_name = description.name
        self._attr_icon = description.icon
        self._attr_native_value = None

    @callback
    def _handle_event(self, payload: dict) -> None:
        value = self._desc.value_fn(payload)
        if value is None:
            return
        self._attr_native_value = value
        self._attr_extra_state_attributes = dict(payload.get("data", {}))
        self.async_write_ha_state()


class AkuvoxLastEventTimeSensor(_AkuvoxBaseSensor):
    """Timestamp of the most recent event."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-outline"

    def __init__(self, entry: AkuvoxConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_last_event_time"
        self._attr_name = "Last event time"
        self._attr_native_value = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Timestamps must be datetimes; parse the restored ISO string.
        if isinstance(self._attr_native_value, str):
            self._attr_native_value = dt_util.parse_datetime(self._attr_native_value)

    @callback
    def _handle_event(self, payload: dict) -> None:
        self._attr_native_value = dt_util.utcnow()
        self.async_write_ha_state()
