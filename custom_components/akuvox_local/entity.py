"""Shared base entity / device info for Akuvox entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_HOST, CONF_NAME, DEFAULT_NAME, DOMAIN


def build_device_info(entry) -> DeviceInfo:
    """Return the device registry entry shared by all platforms."""
    host = entry.data[CONF_HOST]
    name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=name,
        manufacturer="Akuvox",
        model="Door Phone (R20K / compatible)",
        configuration_url=f"http://{host}/",
    )
