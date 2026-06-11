"""Lightweight availability coordinator for the Akuvox device."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import AkuvoxClient, AkuvoxError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)


class AkuvoxCoordinator(DataUpdateCoordinator[bool]):
    """Polls the device periodically to track availability."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: AkuvoxClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{client.host}",
            update_interval=SCAN_INTERVAL,
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> bool:
        try:
            await self.client.async_test_connection()
        except AkuvoxError:
            return False
        return True
