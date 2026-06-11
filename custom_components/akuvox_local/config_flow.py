"""Config flow for the Akuvox (Local) integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AkuvoxAuthError, AkuvoxClient, AkuvoxError, normalize_host
from .const import (
    CONF_ENABLE_CAMERA,
    CONF_ENABLE_LOCK,
    CONF_HIGH_SECURITY,
    CONF_HOST,
    CONF_NAME,
    CONF_ONVIF_PORT,
    CONF_PASSWORD,
    CONF_RELAY_COUNT,
    CONF_RELOCK_DELAY,
    CONF_RTSP_PASSWORD,
    CONF_RTSP_PATH,
    CONF_RTSP_PORT,
    CONF_RTSP_USERNAME,
    CONF_TWO_WAY_AUDIO,
    CONF_USERNAME,
    CONF_WEBHOOK_ID,
    DEFAULT_ENABLE_CAMERA,
    DEFAULT_ENABLE_LOCK,
    DEFAULT_HIGH_SECURITY,
    DEFAULT_NAME,
    DEFAULT_ONVIF_PORT,
    DEFAULT_PASSWORD,
    DEFAULT_RELAY_COUNT,
    DEFAULT_RELOCK_DELAY,
    DEFAULT_RTSP_PASSWORD,
    DEFAULT_RTSP_PATH,
    DEFAULT_RTSP_PORT,
    DEFAULT_RTSP_USERNAME,
    DEFAULT_TWO_WAY_AUDIO,
    DEFAULT_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _build_schema(defaults: dict[str, Any], *, include_host: bool) -> vol.Schema:
    """Build the config/options schema. Host is only editable at setup time."""
    schema: dict[Any, Any] = {}
    if include_host:
        schema[vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, ""))] = str
    schema.update(
        {
            vol.Required(
                CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)
            ): str,
            vol.Required(
                CONF_USERNAME, default=defaults.get(CONF_USERNAME, DEFAULT_USERNAME)
            ): str,
            vol.Required(
                CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, DEFAULT_PASSWORD)
            ): str,
            vol.Required(
                CONF_RELAY_COUNT,
                default=defaults.get(CONF_RELAY_COUNT, DEFAULT_RELAY_COUNT),
            ): vol.All(int, vol.Range(min=1, max=4)),
            vol.Required(
                CONF_HIGH_SECURITY,
                default=defaults.get(CONF_HIGH_SECURITY, DEFAULT_HIGH_SECURITY),
            ): bool,
            vol.Required(
                CONF_ENABLE_LOCK,
                default=defaults.get(CONF_ENABLE_LOCK, DEFAULT_ENABLE_LOCK),
            ): bool,
            vol.Required(
                CONF_RELOCK_DELAY,
                default=defaults.get(CONF_RELOCK_DELAY, DEFAULT_RELOCK_DELAY),
            ): vol.All(int, vol.Range(min=1, max=60)),
            vol.Required(
                CONF_ENABLE_CAMERA,
                default=defaults.get(CONF_ENABLE_CAMERA, DEFAULT_ENABLE_CAMERA),
            ): bool,
            vol.Optional(
                CONF_RTSP_PATH,
                default=defaults.get(CONF_RTSP_PATH, DEFAULT_RTSP_PATH),
            ): str,
            vol.Optional(
                CONF_RTSP_PORT,
                default=defaults.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT),
            ): int,
            vol.Optional(
                CONF_RTSP_USERNAME,
                default=defaults.get(CONF_RTSP_USERNAME, DEFAULT_RTSP_USERNAME),
            ): str,
            vol.Optional(
                CONF_RTSP_PASSWORD,
                default=defaults.get(CONF_RTSP_PASSWORD, DEFAULT_RTSP_PASSWORD),
            ): str,
            vol.Required(
                CONF_TWO_WAY_AUDIO,
                default=defaults.get(CONF_TWO_WAY_AUDIO, DEFAULT_TWO_WAY_AUDIO),
            ): bool,
            vol.Optional(
                CONF_ONVIF_PORT,
                default=defaults.get(CONF_ONVIF_PORT, DEFAULT_ONVIF_PORT),
            ): int,
        }
    )
    return vol.Schema(schema)


async def _async_validate(hass, host: str, user_input: dict[str, Any]) -> str | None:
    """Return an error key, or None if the device is reachable."""
    client = AkuvoxClient(
        async_get_clientsession(hass),
        host,
        user_input[CONF_USERNAME],
        user_input[CONF_PASSWORD],
        high_security=user_input[CONF_HIGH_SECURITY],
    )
    try:
        await client.async_test_connection()
    except AkuvoxAuthError:
        return "invalid_auth"
    except AkuvoxError:
        return "cannot_connect"
    return None


class AkuvoxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = normalize_host(user_input[CONF_HOST])
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            error = await _async_validate(self.hass, host, user_input)
            if error:
                errors["base"] = error
            else:
                data = dict(user_input)
                data[CONF_HOST] = host
                data[CONF_WEBHOOK_ID] = webhook.async_generate_id()
                return self.async_create_entry(title=user_input[CONF_NAME], data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(user_input or {}, include_host=True),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AkuvoxOptionsFlow()


class AkuvoxOptionsFlow(OptionsFlow):
    """Allow editing credentials and options after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry

        if user_input is not None:
            error = await _async_validate(self.hass, entry.data[CONF_HOST], user_input)
            if error:
                errors["base"] = error
            else:
                # Persist updated values back into the entry data and reload.
                new_data = {**entry.data, **user_input}
                self.hass.config_entries.async_update_entry(entry, data=new_data)
                return self.async_create_entry(title="", data={})

        defaults = {k: v for k, v in entry.data.items() if k != CONF_HOST}
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(defaults, include_host=False),
            errors=errors,
        )
