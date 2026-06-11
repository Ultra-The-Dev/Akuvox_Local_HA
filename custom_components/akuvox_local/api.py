"""Thin async client for the Akuvox local HTTP API.

Akuvox door phones (R20K, R20A, R20B, R23, R26, R29, E11/E12, X912/X915, …)
expose a documented local HTTP endpoint to trigger their relays. Depending on
the firmware and whether "High Security Mode" is enabled, one of several URL
formats is required:

  Standard (High Security OFF — factory default on most R2x units):
    http://{ip}/fcgi/do?action=OpenDoor&UserName={u}&Password={p}&DoorNum={n}

  High Security ON, with credentials (HTTP Basic auth):
    http://{ip}/fcgi/OpenDoor?action=OpenDoor&DoorNum={n}

  High Security ON, no credentials configured:
    http://{ip}/fcgi/OpenDoor?action=OpenDoor&DoorNum={n}

DoorNum 1/2/3/4 maps to Relay A/B/C/D.

To "just work" across every device/firmware combination, ``async_open_door``
tries the most likely format first (based on the user's High-Security setting)
and transparently falls back to the others if the device rejects it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

import aiohttp
from yarl import URL

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10


def normalize_host(raw: str) -> str:
    """Reduce free-form user input to a bare host[:port].

    Accepts values like ``http://192.168.1.50/``, ``https://door.local:8443``,
    ``192.168.1.50/`` or ``  192.168.1.50  `` and returns just the host (and
    port if the user supplied a non-default one). Prevents the most common
    "could not reach the device" cause: a pasted URL ending up doubled into
    ``http://http://...``.
    """
    host = (raw or "").strip()
    # Strip a leading scheme if present.
    if "://" in host:
        host = host.split("://", 1)[1]
    # Drop any path/query the user may have pasted.
    host = host.split("/", 1)[0].split("?", 1)[0]
    # Drop default web ports — the connection test adds the right scheme itself.
    for suffix in (":80", ":443"):
        if host.endswith(suffix):
            host = host[: -len(suffix)]
    return host.strip().rstrip(".")


class AkuvoxError(Exception):
    """Raised when communication with the device fails."""


class AkuvoxAuthError(AkuvoxError):
    """Raised when the device rejects the supplied credentials."""


@dataclass
class _Attempt:
    """A single open-door request strategy."""

    url: URL
    auth: aiohttp.BasicAuth | None
    label: str


class AkuvoxClient:
    """Minimal client wrapping the device's local HTTP API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        *,
        high_security: bool = False,
    ) -> None:
        self._session = session
        self._host = host
        self._username = username or ""
        self._password = password or ""
        self._high_security = high_security

    @property
    def host(self) -> str:
        return self._host

    # -- URL builders ---------------------------------------------------------
    def _url_standard(self, door_num: int) -> URL:
        # Build via a query dict so credentials containing &, #, %, spaces …
        # are URL-encoded instead of corrupting the query string.
        return URL(f"http://{self._host}/fcgi/do").with_query(
            {
                "action": "OpenDoor",
                "UserName": self._username,
                "Password": self._password,
                "DoorNum": str(door_num),
            }
        )

    def _url_secure(self, door_num: int) -> URL:
        return URL(
            f"http://{self._host}/fcgi/OpenDoor?action=OpenDoor&DoorNum={door_num}"
        )

    def _attempts(self, door_num: int) -> list[_Attempt]:
        """Ordered list of strategies to try, best guess first."""
        basic = (
            aiohttp.BasicAuth(self._username, self._password)
            if self._username
            else None
        )
        standard = _Attempt(self._url_standard(door_num), None, "standard")
        secure_auth = _Attempt(self._url_secure(door_num), basic, "high-security")
        secure_noauth = _Attempt(self._url_secure(door_num), None, "high-security-noauth")

        if self._high_security:
            order = [secure_auth, secure_noauth, standard]
        else:
            order = [standard, secure_auth, secure_noauth]
        # Drop duplicate auth-less secure attempt when there are no credentials.
        seen: set[tuple[str, bool]] = set()
        unique: list[_Attempt] = []
        for attempt in order:
            key = (str(attempt.url), attempt.auth is not None)
            if key in seen:
                continue
            seen.add(key)
            unique.append(attempt)
        return unique

    # -- Public API -----------------------------------------------------------
    async def async_open_door(self, door_num: int = 1) -> None:
        """Trigger the given relay (1=A, 2=B, ...). Raises on failure.

        Tries each known URL/auth format until one succeeds.
        """
        last_error: AkuvoxError = AkuvoxError("No open-door strategy succeeded")
        for attempt in self._attempts(door_num):
            try:
                await self._do_request(attempt)
            except AkuvoxAuthError as err:
                last_error = err
                _LOGGER.debug("Open door via %s rejected: %s", attempt.label, err)
                continue
            except AkuvoxError as err:
                last_error = err
                _LOGGER.debug("Open door via %s failed: %s", attempt.label, err)
                continue
            else:
                _LOGGER.debug("Open door succeeded via %s", attempt.label)
                return
        raise last_error

    async def _do_request(self, attempt: _Attempt) -> None:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                resp = await self._session.get(attempt.url, auth=attempt.auth)
                text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise AkuvoxError(f"Failed to reach {self._host}: {err}") from err

        if resp.status in (401, 403):
            raise AkuvoxAuthError("Device rejected the credentials")
        if resp.status >= 400:
            raise AkuvoxError(f"Device returned HTTP {resp.status}")

        # The fcgi endpoint returns a tiny payload. A successful trigger usually
        # contains "success"; some firmwares just return an empty 200 body.
        lowered = text.lower()
        if any(token in lowered for token in ("fail", "error", "incorrect", "invalid")):
            if "password" in lowered or "auth" in lowered or "user" in lowered:
                raise AkuvoxAuthError(f"Authentication failed: {text.strip()}")
            raise AkuvoxError(f"Device reported failure: {text.strip()}")

    async def async_test_connection(self) -> None:
        """Check that the device's web service is reachable.

        We GET the device root rather than the open-door endpoint so that setting
        up the integration never physically opens a door. Any HTTP response —
        even a 401 login page or a redirect — proves the device is reachable.

        Akuvox firmware varies: older R2x units serve plain HTTP on port 80,
        while newer firmware (and some R20K builds) force HTTPS with a
        self-signed certificate. We therefore try HTTP first, then HTTPS (with
        certificate verification disabled, since these are local self-signed
        devices), and only fail if every attempt is unreachable.
        """
        candidates = (
            f"http://{self._host}/",
            f"https://{self._host}/",
        )
        last_error: Exception | None = None
        for url in candidates:
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    # ssl=False disables verification for the HTTPS attempt;
                    # it is ignored for the plain-HTTP one.
                    resp = await self._session.get(
                        url, ssl=False, allow_redirects=False
                    )
                    await resp.read()
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                last_error = err
                _LOGGER.debug("Connection test to %s failed: %s", url, err)
                continue
            _LOGGER.debug("Connection test to %s -> HTTP %s", url, resp.status)
            return
        raise AkuvoxError(f"Cannot reach {self._host}: {last_error}")
