"""The Akuvox (Local) integration."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import logging
import time

import voluptuous as vol
from aiohttp.web import Request, Response

from homeassistant.components import persistent_notification, webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.network import get_url
from homeassistant.util import dt as dt_util

from .api import AkuvoxAuthError, AkuvoxClient, AkuvoxError
from .const import (
    CONF_HIGH_SECURITY,
    CONF_HOST,
    CONF_NOTIFIED_MARKER,
    CONF_PASSWORD,
    CONF_TWO_WAY_AUDIO,
    CONF_USERNAME,
    CONF_WEBHOOK_ID,
    DOMAIN,
    EVENT_HISTORY_SIZE,
    PLATFORMS,
    SIGNAL_AKUVOX_EVENT,
    WEBHOOK_MAX_KEY_LENGTH,
    WEBHOOK_MAX_KEYS,
    WEBHOOK_MAX_VALUE_LENGTH,
    WEBHOOK_RATE_LIMIT_COUNT,
    WEBHOOK_RATE_LIMIT_WINDOW,
)
from .coordinator import AkuvoxCoordinator
from .stream import build_go2rtc_snippet, go2rtc_stream_name

_LOGGER = logging.getLogger(__name__)


@dataclass
class AkuvoxRuntimeData:
    """Objects shared across the integration's platforms."""

    client: AkuvoxClient
    coordinator: AkuvoxCoordinator
    webhook_id: str
    # Recent webhook events, newest last — surfaced in diagnostics.
    history: deque = field(
        default_factory=lambda: deque(maxlen=EVENT_HISTORY_SIZE)
    )
    # Timestamps of recently accepted webhooks, for rate limiting.
    recent_webhooks: deque = field(default_factory=deque)


# entry.runtime_data holds an AkuvoxRuntimeData instance.
AkuvoxConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: AkuvoxConfigEntry) -> bool:
    """Set up Akuvox (Local) from a config entry."""
    session = async_get_clientsession(hass)
    client = AkuvoxClient(
        session,
        entry.data[CONF_HOST],
        entry.data.get(CONF_USERNAME, ""),
        entry.data.get(CONF_PASSWORD, ""),
        high_security=entry.data.get(CONF_HIGH_SECURITY, False),
    )

    coordinator = AkuvoxCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    webhook_id = entry.data[CONF_WEBHOOK_ID]
    # Runtime data must exist before the webhook is registered — the handler
    # reads it as soon as the first push arrives.
    entry.runtime_data = AkuvoxRuntimeData(
        client=client, coordinator=coordinator, webhook_id=webhook_id
    )

    # Defensively clear any stale registration (e.g. after a failed reload).
    try:
        webhook.async_unregister(hass, webhook_id)
    except ValueError:
        pass
    webhook.async_register(
        hass,
        DOMAIN,
        f"Akuvox {entry.title}",
        webhook_id,
        _make_webhook_handler(entry),
        # Akuvox Action URLs are sent as HTTP GET; POST/PUT supported too.
        allowed_methods=["GET", "POST", "PUT"],
        # The door phone lives on the LAN, but allow any source so setups behind
        # reverse proxies / different subnets still receive events. The webhook
        # ID is a long random secret.
        local_only=False,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_register_services(hass)

    # Show the setup notifications once (and again if the relevant settings
    # change), not on every Home Assistant restart. The marker is stored in the
    # entry before the update listener is attached, so writing it does not
    # trigger a reload loop.
    two_way = entry.data.get(CONF_TWO_WAY_AUDIO, False)
    marker = f"{webhook_id}|{two_way}"
    if entry.data.get(CONF_NOTIFIED_MARKER) != marker:
        _async_notify_webhook_url(hass, entry, webhook_id)
        if two_way:
            _async_notify_two_way_audio(hass, entry)
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_NOTIFIED_MARKER: marker}
        )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _async_notify_two_way_audio(
    hass: HomeAssistant, entry: AkuvoxConfigEntry
) -> None:
    """Show the ready-to-paste go2rtc snippet for two-way (talk) audio."""
    snippet = build_go2rtc_snippet(entry)
    name = go2rtc_stream_name(entry)
    persistent_notification.async_create(
        hass,
        title=f"Akuvox ({entry.title}) — Two-way audio setup",
        notification_id=f"{DOMAIN}_{entry.entry_id}_twoway",
        message=(
            "Talk-back uses go2rtc's ONVIF backchannel. Add this to your "
            "**go2rtc.yaml** (Settings → Add-ons → go2rtc, or the AlexxIT/WebRTC "
            "add-on), then restart go2rtc:\n\n"
            f"```yaml\n{snippet}```\n"
            f"Then add a card pointing at the `{name}` stream (Advanced Camera "
            "Card or WebRTC Camera) and use its microphone button to talk.\n\n"
            "If you can hear but not talk, your firmware may need the RTSP "
            "backchannel variant instead — see the README troubleshooting."
        ),
    )


def _async_notify_webhook_url(
    hass: HomeAssistant, entry: AkuvoxConfigEntry, webhook_id: str
) -> None:
    """Show the Action URL webhook to the user so they can paste it into the device."""
    try:
        base = get_url(hass, prefer_external=False, allow_internal=True)
    except Exception:  # noqa: BLE001
        base = "http://<home-assistant-ip>:8123"
    url = f"{base}/api/webhook/{webhook_id}"
    persistent_notification.async_create(
        hass,
        title=f"Akuvox ({entry.title}) — Action URL",
        notification_id=f"{DOMAIN}_{entry.entry_id}_webhook",
        message=(
            "To receive call/door events, open the device web UI "
            "(**Setting → Action URL**) and use this base webhook URL:\n\n"
            f"`{url}?event=call`\n\n"
            "Examples for each event:\n"
            f"- Call/button: `{url}?event=call`\n"
            f"- Door opened: `{url}?event=door_opened`\n"
            f"- Valid card: `{url}?event=valid_card`\n"
            f"- Invalid card: `{url}?event=invalid_card`\n"
            f"- Motion: `{url}?event=motion`\n"
        ),
    )


SERVICE_OPEN_DOOR = "open_door"
SERVICE_OPEN_DOOR_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
        vol.Optional("door_num", default=1): vol.All(int, vol.Range(min=1, max=4)),
    }
)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the open_door service (once)."""
    if hass.services.has_service(DOMAIN, SERVICE_OPEN_DOOR):
        return

    async def _handle_open_door(call: ServiceCall) -> None:
        door_num = call.data["door_num"]
        device_id = call.data.get("device_id")

        entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if getattr(e, "runtime_data", None) is not None
        ]

        if device_id:
            device = dr.async_get(hass).async_get(device_id)
            if not device:
                raise HomeAssistantError(f"Unknown device: {device_id}")
            entries = [e for e in entries if e.entry_id in device.config_entries]

        if not entries:
            raise HomeAssistantError("No loaded Akuvox device found for this call")

        for entry in entries:
            try:
                await entry.runtime_data.client.async_open_door(door_num)
            except AkuvoxAuthError as err:
                # Credentials changed on the device — ask the user to update them.
                entry.async_start_reauth(hass)
                raise HomeAssistantError(f"Failed to open door: {err}") from err
            except AkuvoxError as err:
                raise HomeAssistantError(f"Failed to open door: {err}") from err

    hass.services.async_register(
        DOMAIN, SERVICE_OPEN_DOOR, _handle_open_door, schema=SERVICE_OPEN_DOOR_SCHEMA
    )


async def async_unload_entry(hass: HomeAssistant, entry: AkuvoxConfigEntry) -> bool:
    """Unload a config entry."""
    webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: AkuvoxConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


@callback
def _async_enrich_device(
    hass: HomeAssistant, entry: AkuvoxConfigEntry, data: dict[str, str]
) -> None:
    """Update the device registry with MAC/model/firmware sent by the device.

    Akuvox Action URLs can include $mac/$model/$firmware variables. We only
    write fields that are present and not already set.
    """
    mac = data.get("mac") or data.get("MAC")
    model = data.get("model") or data.get("Model")
    firmware = data.get("firmware") or data.get("Firmware")
    if not any((mac, model, firmware)):
        return

    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    if device is None:
        return

    updates: dict = {}
    if model and device.model in (None, "", "Door Phone (R20K / compatible)"):
        updates["model"] = model
    if firmware and not device.sw_version:
        updates["sw_version"] = firmware
    if mac:
        conn = (dr.CONNECTION_NETWORK_MAC, dr.format_mac(mac))
        # Another integration (e.g. ONVIF) may already own this MAC on a
        # different device entry; claiming it again raises a collision error.
        owner = registry.async_get_device(connections={conn})
        if conn not in device.connections and owner is None:
            updates["merge_connections"] = {conn}
    if not updates:
        return
    try:
        registry.async_update_device(device.id, **updates)
    except Exception as err:  # noqa: BLE001 - enrichment must never break events
        _LOGGER.debug("Skipping device registry update: %s", err)


def _sanitize_webhook_data(raw: dict) -> dict[str, str]:
    """Clamp untrusted webhook input to sane key/value counts and lengths."""
    data: dict[str, str] = {}
    # The event type must survive truncation regardless of key order.
    if "event" in raw:
        data["event"] = str(raw["event"])[:WEBHOOK_MAX_VALUE_LENGTH]
    for key, value in raw.items():
        if key == "event":
            continue
        if len(data) >= WEBHOOK_MAX_KEYS:
            _LOGGER.debug("Akuvox webhook: payload truncated at %s keys", WEBHOOK_MAX_KEYS)
            break
        data[str(key)[:WEBHOOK_MAX_KEY_LENGTH]] = str(value)[:WEBHOOK_MAX_VALUE_LENGTH]
    return data


def _webhook_rate_limited(runtime: AkuvoxRuntimeData) -> bool:
    """Sliding-window rate limit so a misbehaving device can't flood HA."""
    now = time.monotonic()
    recent = runtime.recent_webhooks
    while recent and now - recent[0] > WEBHOOK_RATE_LIMIT_WINDOW:
        recent.popleft()
    if len(recent) >= WEBHOOK_RATE_LIMIT_COUNT:
        return True
    recent.append(now)
    return False


def _make_webhook_handler(entry: AkuvoxConfigEntry):
    """Build a webhook handler bound to this config entry."""

    async def _handle_webhook(
        hass: HomeAssistant, webhook_id: str, request: Request
    ) -> Response:
        """Receive an Action URL push from the Akuvox device.

        The device calls a URL like:
          /api/webhook/<id>?event=door_opened&relay=$relay1status&mac=$mac
        Query params (GET) and form/JSON body (POST) are both accepted.
        """
        runtime: AkuvoxRuntimeData = entry.runtime_data
        if _webhook_rate_limited(runtime):
            _LOGGER.warning(
                "Akuvox webhook for %s rate-limited (>%s pushes/%ss); dropping event",
                entry.title,
                WEBHOOK_RATE_LIMIT_COUNT,
                WEBHOOK_RATE_LIMIT_WINDOW,
            )
            return Response(text="Too Many Requests", status=429)

        raw: dict = dict(request.query)
        if request.method in ("POST", "PUT"):
            try:
                if request.content_type == "application/json":
                    body = await request.json()
                    if isinstance(body, dict):
                        raw.update(body)
                else:
                    form = await request.post()
                    raw.update(form)
            except Exception:  # noqa: BLE001 - never fail on a bad push
                _LOGGER.debug("Akuvox webhook: could not parse %s body", request.method)
        data = _sanitize_webhook_data(raw)

        event_type = (data.get("event") or "call").lower()
        _LOGGER.debug("Akuvox webhook (%s): %s", event_type, data)

        # A push from the device proves it is online — refresh availability.
        runtime.coordinator.async_set_updated_data(True)
        runtime.history.append(
            {
                "time": dt_util.utcnow().isoformat(),
                "event": event_type,
                "data": data,
            }
        )

        try:
            _async_enrich_device(hass, entry, data)
        except Exception:  # noqa: BLE001 - enrichment is best-effort only
            _LOGGER.debug("Device enrichment failed", exc_info=True)

        payload = {"entry_id": entry.entry_id, "event": event_type, "data": data}
        # Fire a bus event for automations...
        hass.bus.async_fire(f"{DOMAIN}_event", payload)
        # ...and notify entities (event entity, binary sensors).
        async_dispatcher_send(hass, f"{SIGNAL_AKUVOX_EVENT}_{entry.entry_id}", payload)

        return Response(text="OK")

    return _handle_webhook
