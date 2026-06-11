"""Camera platform: the door phone's RTSP video stream."""

from __future__ import annotations

import logging

from homeassistant.components import ffmpeg
from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AkuvoxConfigEntry
from .const import (
    CONF_ENABLE_CAMERA,
    CONF_TWO_WAY_AUDIO,
    DEFAULT_ENABLE_CAMERA,
    DEFAULT_TWO_WAY_AUDIO,
)
from .entity import build_device_info
from .stream import build_rtsp_url, go2rtc_stream_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkuvoxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the camera entity if enabled."""
    if not entry.data.get(CONF_ENABLE_CAMERA, DEFAULT_ENABLE_CAMERA):
        return
    async_add_entities([AkuvoxCamera(hass, entry)])


class AkuvoxCamera(Camera):
    """Exposes the Akuvox RTSP feed as a Home Assistant camera."""

    _attr_has_entity_name = True
    _attr_name = "Camera"
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, hass: HomeAssistant, entry: AkuvoxConfigEntry) -> None:
        super().__init__()
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_camera"
        self._attr_device_info = build_device_info(entry)
        self._rtsp_url = build_rtsp_url(entry)

        two_way = entry.data.get(CONF_TWO_WAY_AUDIO, DEFAULT_TWO_WAY_AUDIO)
        # Non-sensitive hints for the dashboard / advanced camera card.
        self._attr_extra_state_attributes = {
            "two_way_audio": two_way,
            "go2rtc_stream": go2rtc_stream_name(entry) if two_way else None,
        }

    async def stream_source(self) -> str:
        return self._rtsp_url

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Grab a single JPEG frame from the RTSP stream via ffmpeg."""
        return await ffmpeg.async_get_image(
            self.hass, self._rtsp_url, width=width, height=height
        )
