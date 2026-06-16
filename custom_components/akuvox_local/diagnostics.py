"""Diagnostics support: downloadable, secret-redacted debug snapshot."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import AkuvoxConfigEntry
from .const import CONF_PASSWORD, CONF_RTSP_PASSWORD, CONF_WEBHOOK_ID

# Secrets and personally identifying values stripped from the download.
TO_REDACT = {
    CONF_PASSWORD,
    CONF_RTSP_PASSWORD,
    CONF_WEBHOOK_ID,
    # RFID card codes in recorded events.
    "card",
    "Card",
    "CardCode",
    "code",
    "rfid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AkuvoxConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
        },
        "device_reachable": bool(runtime.coordinator.data),
        "last_update_success": runtime.coordinator.last_update_success,
        "recent_events": async_redact_data(list(runtime.history), TO_REDACT),
    }
