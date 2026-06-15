"""Binary sensor platform: connectivity plus event-driven sensors.

Besides the connectivity sensor, the Action URL webhook drives three
momentary sensors that turn on when an event arrives and auto-clear shortly
after — handy for dashboards, camera cards and simple automations:

  - Ringing  → on while someone is calling (clears on answer/missed/timeout)
  - Motion   → on when the device reports motion
  - Door     → on when a relay opens the door
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AkuvoxConfigEntry
from .const import (
    DOOR_OFF_DELAY,
    MOTION_OFF_DELAY,
    RINGING_OFF_DELAY,
    SIGNAL_AKUVOX_EVENT,
)
from .entity import build_device_info


@dataclass(frozen=True, kw_only=True)
class AkuvoxEventBinarySensorDescription:
    """Describes a momentary, webhook-driven binary sensor."""

    key: str
    name: str
    on_events: frozenset[str]
    # Events that immediately clear the sensor (besides the timeout).
    off_events: frozenset[str] = frozenset()
    off_delay: int = 30
    device_class: BinarySensorDeviceClass | None = None
    icon: str | None = None


EVENT_SENSORS: tuple[AkuvoxEventBinarySensorDescription, ...] = (
    AkuvoxEventBinarySensorDescription(
        key="ringing",
        name="Ringing",
        on_events=frozenset({"call"}),
        off_events=frozenset({"call_answered", "call_missed"}),
        off_delay=RINGING_OFF_DELAY,
        icon="mdi:bell-ring",
    ),
    AkuvoxEventBinarySensorDescription(
        key="motion",
        name="Motion",
        on_events=frozenset({"motion"}),
        off_delay=MOTION_OFF_DELAY,
        device_class=BinarySensorDeviceClass.MOTION,
    ),
    AkuvoxEventBinarySensorDescription(
        key="door",
        name="Door",
        on_events=frozenset({"door_opened"}),
        off_delay=DOOR_OFF_DELAY,
        device_class=BinarySensorDeviceClass.DOOR,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkuvoxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the connectivity and event-driven sensors."""
    entities: list[BinarySensorEntity] = [AkuvoxConnectivitySensor(entry)]
    entities.extend(
        AkuvoxEventBinarySensor(entry, desc) for desc in EVENT_SENSORS
    )
    async_add_entities(entities)


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


class AkuvoxEventBinarySensor(BinarySensorEntity):
    """A momentary sensor switched on by webhook events, auto-clearing."""

    _attr_has_entity_name = True
    _attr_is_on = False
    # Purely push-driven via the webhook dispatcher; nothing to poll.
    _attr_should_poll = False

    def __init__(
        self,
        entry: AkuvoxConfigEntry,
        description: AkuvoxEventBinarySensorDescription,
    ) -> None:
        self._entry = entry
        self._desc = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_name = description.name
        self._attr_device_class = description.device_class
        self._attr_icon = description.icon
        self._attr_device_info = build_device_info(entry)
        self._cancel_off: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_AKUVOX_EVENT}_{self._entry.entry_id}",
                self._handle_event,
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_timer()
        await super().async_will_remove_from_hass()

    def _cancel_timer(self) -> None:
        if self._cancel_off is not None:
            self._cancel_off()
            self._cancel_off = None

    @callback
    def _handle_event(self, payload: dict) -> None:
        event_type = payload.get("event")
        if event_type in self._desc.on_events:
            self._cancel_timer()
            self._attr_is_on = True
            self._attr_extra_state_attributes = dict(payload.get("data", {}))
            self.async_write_ha_state()
            self._cancel_off = async_call_later(
                self.hass, self._desc.off_delay, self._switch_off
            )
        elif event_type in self._desc.off_events and self._attr_is_on:
            self._cancel_timer()
            self._attr_is_on = False
            self.async_write_ha_state()

    @callback
    def _switch_off(self, _now) -> None:
        self._cancel_off = None
        self._attr_is_on = False
        self.async_write_ha_state()
