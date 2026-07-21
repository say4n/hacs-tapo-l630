"""Account runtime and address reconciliation for Tapo L630."""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any

from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .client import TapoL630Client
from .const import CONF_DEVICES
from .discovery import (
    async_discover_l630s,
    map_hosts_by_device_id,
    normalize_device_id,
)

_REDISCOVERY_COOLDOWN = 60
_FORCED_DISCOVERY_COOLDOWN = 10


class TapoL630Runtime:
    """Manage clients and current addresses for one Tapo account."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        session: ClientSession,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.session = session
        self.devices = [dict(device) for device in entry.data[CONF_DEVICES]]
        self.coordinators: list[Any] = []
        self._discovery_lock = asyncio.Lock()
        self._last_discovery = 0.0
        self._confirmed_device_ids: set[str] = set()

    def client(self, host: str) -> TapoL630Client:
        """Create a local client using the account credentials."""
        return TapoL630Client(
            self.session,
            host,
            self.entry.data[CONF_USERNAME],
            self.entry.data[CONF_PASSWORD],
        )

    async def async_rediscover(self, *, force: bool = False) -> dict[str, str]:
        """Refresh known bulb addresses and persist any changes."""
        async with self._discovery_lock:
            elapsed = monotonic() - self._last_discovery
            cooldown = (
                _FORCED_DISCOVERY_COOLDOWN if force else _REDISCOVERY_COOLDOWN
            )
            if elapsed < cooldown:
                return self._known_hosts()

            discovered = await async_discover_l630s()
            self._last_discovery = monotonic()
            hosts = map_hosts_by_device_id(discovered)
            self._confirmed_device_ids = set(hosts)
            changed = False
            for device in self.devices:
                host = hosts.get(normalize_device_id(device.get("device_id")))
                if host and host != device.get(CONF_HOST):
                    device[CONF_HOST] = host
                    changed = True

            if changed:
                data = {**self.entry.data, CONF_DEVICES: self.devices}
                self.hass.config_entries.async_update_entry(self.entry, data=data)
            return self._known_hosts()

    def is_confirmed(self, device_id: str) -> bool:
        """Return whether the bulb answered the latest LAN discovery."""
        return device_id in self._confirmed_device_ids

    def _known_hosts(self) -> dict[str, str]:
        return {
            normalize_device_id(device.get("device_id")): device[CONF_HOST]
            for device in self.devices
            if isinstance(device.get(CONF_HOST), str)
        }
