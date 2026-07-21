"""Data update coordinator for Tapo L630."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import TapoL630Client
from .const import DOMAIN, SCAN_INTERVAL
from .discovery import normalize_device_id
from .exceptions import (
    TapoAuthenticationError,
    TapoConnectionError,
    TapoError,
)
from .runtime import TapoL630Runtime

_LOGGER = logging.getLogger(__name__)


class TapoL630Coordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll and update a Tapo L630 bulb."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        runtime: TapoL630Runtime,
        device: dict[str, Any],
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_{device.get('device_id', device['host'])}",
            update_interval=SCAN_INTERVAL,
        )
        self.config_entry = config_entry
        self.runtime = runtime
        self.device = device
        self.expected_device_id = normalize_device_id(device.get("device_id"))
        host = device.get("host")
        self.client = runtime.client(host) if isinstance(host, str) else None

    async def async_initialize(self) -> None:
        """Fetch initial data while allowing an individual bulb to be offline."""
        try:
            data = await self._async_fetch_data()
        except TapoAuthenticationError:
            raise
        except TapoError as err:
            self.data = self.device
            self.async_set_update_error(err)
        else:
            self.async_set_updated_data(data)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._async_fetch_data()
        except TapoAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except TapoError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_fetch_data(self) -> dict[str, Any]:
        old_host = self.device.get("host")
        try:
            if self.client is None:
                raise TapoConnectionError("The bulb has not been found on the LAN")
            info = await self.client.async_get_device_info()
            self._validate_identity(info)
            return info
        except (TapoConnectionError, TapoAuthenticationError) as err:
            is_auth_error = isinstance(err, TapoAuthenticationError)
            hosts = await self.runtime.async_rediscover(force=is_auth_error)
            host = hosts.get(self.expected_device_id)
            if not host or host == old_host:
                if is_auth_error and not self.runtime.is_confirmed(
                    self.expected_device_id
                ):
                    raise TapoConnectionError(
                        "The bulb has not been found on the LAN"
                    ) from err
                raise
            self.device["host"] = host
            self.client = self.runtime.client(host)
            info = await self.client.async_get_device_info()
            self._validate_identity(info)
            return info

    def _validate_identity(self, info: dict[str, Any]) -> None:
        """Ensure a host still represents the configured L630 bulb."""
        actual_id = normalize_device_id(info.get("device_id"))
        model = str(info.get("model", ""))
        if actual_id != self.expected_device_id or (
            model and not model.upper().startswith("L630")
        ):
            raise TapoConnectionError(
                "The configured address responded as a different Tapo device"
            )
