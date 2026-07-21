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
from .cloud import TapoCloudClient, TapoCloudDeviceClient
from .const import CONF_DEVICES
from .discovery import (
    async_discover_l630s,
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
        cloud: TapoCloudClient | None = None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.session = session
        self.cloud = cloud or TapoCloudClient(
            session,
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
        )
        self.devices = [dict(device) for device in entry.data[CONF_DEVICES]]
        self.coordinators: list[Any] = []
        self._discovery_lock = asyncio.Lock()
        self._last_discovery = 0.0
        self._confirmed_hosts: dict[str, str] = {}

    def client(self, host: str) -> TapoL630Client:
        """Create a local client using the account credentials."""
        return TapoL630Client(
            self.session,
            host,
            self.entry.data[CONF_USERNAME],
            self.entry.data[CONF_PASSWORD],
        )

    def cloud_client(self, device_id: str) -> TapoCloudDeviceClient:
        """Create a cloud relay client for a bulb."""
        return self.cloud.device_client(device_id)

    def invalidate_confirmed_host(self, device_id: str) -> None:
        """Stop retrying a LAN host until a fresh discovery confirms it."""
        self._confirmed_hosts.pop(device_id, None)

    async def async_rediscover(self, *, force: bool = False) -> dict[str, str]:
        """Refresh known bulb addresses and persist any changes."""
        async with self._discovery_lock:
            elapsed = monotonic() - self._last_discovery
            cooldown = (
                _FORCED_DISCOVERY_COOLDOWN if force else _REDISCOVERY_COOLDOWN
            )
            if elapsed < cooldown:
                return dict(self._confirmed_hosts)

            discovered = await async_discover_l630s(self.hass)
            self._last_discovery = monotonic()
            devices_by_id = {
                normalize_device_id(device.get("device_id")): device
                for device in discovered
            }
            devices_by_mac = {
                normalize_device_id(device.get("mac")): device
                for device in discovered
            }
            changed = False
            confirmed_hosts: dict[str, str] = {}
            for device in self.devices:
                device_id = normalize_device_id(device.get("device_id"))
                device_mac = normalize_device_id(device.get("device_mac"))
                local = devices_by_id.get(device_id) or devices_by_mac.get(device_mac)
                if local:
                    host = local["host"]
                    confirmed_hosts[device_id] = host
                    local_device_id = local.get("device_id")
                    if local_device_id != device.get("local_device_id"):
                        device["local_device_id"] = local_device_id
                        changed = True
                else:
                    host = None
                if host and host != device.get(CONF_HOST):
                    device[CONF_HOST] = host
                    changed = True
            self._confirmed_hosts = confirmed_hosts
            if changed:
                data = {**self.entry.data, CONF_DEVICES: self.devices}
                self.hass.config_entries.async_update_entry(self.entry, data=data)
            return dict(self._confirmed_hosts)
