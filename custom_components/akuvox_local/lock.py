"""Lock platform: expose each relay as a momentary door lock.

Door-strike relays are momentary (they pulse open, then the door re-locks
itself), so the lock is optimistic: unlocking pulses the relay and the entity
returns to "locked" after ``relock_delay`` seconds. This makes the door work
nicely with voice assistants, HomeKit and Alexa ("unlock the front door").
"""

from __future__ import annotations

import logging

from collections.abc import Callable

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import AkuvoxConfigEntry
from .api import AkuvoxAuthError, AkuvoxError
from .const import (
    CONF_ENABLE_LOCK,
    CONF_RELAY_COUNT,
    CONF_RELOCK_DELAY,
    DEFAULT_ENABLE_LOCK,
    DEFAULT_RELAY_COUNT,
    DEFAULT_RELOCK_DELAY,
    RELAY_LABELS,
)
from .entity import build_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkuvoxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a lock for each relay (if enabled)."""
    if not entry.data.get(CONF_ENABLE_LOCK, DEFAULT_ENABLE_LOCK):
        return
    relay_count = entry.data.get(CONF_RELAY_COUNT, DEFAULT_RELAY_COUNT)
    async_add_entities(
        AkuvoxRelayLock(entry, door_num) for door_num in range(1, relay_count + 1)
    )


class AkuvoxRelayLock(LockEntity):
    """A momentary, optimistic lock backed by an Akuvox relay."""

    _attr_has_entity_name = True
    # OPEN = "unlatch": lets voice assistants / HomeKit offer an explicit
    # "open the door" action in addition to unlock.
    _attr_supported_features = LockEntityFeature.OPEN

    def __init__(self, entry: AkuvoxConfigEntry, door_num: int) -> None:
        self._entry = entry
        self._client = entry.runtime_data.client
        self._door_num = door_num
        self._relock_delay = entry.data.get(CONF_RELOCK_DELAY, DEFAULT_RELOCK_DELAY)
        label = RELAY_LABELS.get(door_num, str(door_num))
        self._attr_name = f"Lock {label}" if relay_count_gt_one(entry) else "Lock"
        self._attr_unique_id = f"{entry.entry_id}_lock_{door_num}"
        self._attr_device_info = build_device_info(entry)
        self._attr_is_locked = True
        self._cancel_relock: Callable[[], None] | None = None

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_relock_timer()
        await super().async_will_remove_from_hass()

    def _cancel_relock_timer(self) -> None:
        if self._cancel_relock is not None:
            self._cancel_relock()
            self._cancel_relock = None

    async def async_open(self, **kwargs) -> None:
        """Unlatch — same momentary relay pulse as unlock."""
        await self.async_unlock(**kwargs)

    async def async_unlock(self, **kwargs) -> None:
        """Pulse the relay open, then optimistically re-lock."""
        try:
            await self._client.async_open_door(self._door_num)
        except AkuvoxAuthError as err:
            # Credentials changed on the device — ask the user to update them.
            self._entry.async_start_reauth(self.hass)
            raise HomeAssistantError(f"Failed to unlock: {err}") from err
        except AkuvoxError as err:
            raise HomeAssistantError(f"Failed to unlock: {err}") from err

        self._attr_is_locked = False
        self.async_write_ha_state()

        self._cancel_relock_timer()
        self._cancel_relock = async_call_later(
            self.hass, self._relock_delay, self._relock
        )

    @callback
    def _relock(self, _now) -> None:
        self._cancel_relock = None
        self._attr_is_locked = True
        self.async_write_ha_state()

    async def async_lock(self, **kwargs) -> None:
        """The strike re-locks itself; just reflect the state."""
        self._cancel_relock_timer()
        self._attr_is_locked = True
        self.async_write_ha_state()


def relay_count_gt_one(entry: AkuvoxConfigEntry) -> bool:
    return entry.data.get(CONF_RELAY_COUNT, DEFAULT_RELAY_COUNT) > 1
