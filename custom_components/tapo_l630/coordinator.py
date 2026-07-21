"""Data update coordinator for Tapo L630."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SCAN_INTERVAL
from .discovery import normalize_device_id
from .exceptions import (
    TapoAuthenticationError,
    TapoConnectionError,
    TapoError,
    TapoSessionError,
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
        self._using_cloud = False
        self._local_identity_validated = False

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

    async def async_set_device_info(self, **params: Any) -> None:
        """Update the bulb, falling back to cloud if local control fails."""
        if self.client is None or (
            not self._using_cloud and not self._local_identity_validated
        ):
            await self._async_fetch_data()
        try:
            await self.client.async_set_device_info(**params)
        except (TapoConnectionError, TapoAuthenticationError, TapoSessionError):
            if self._using_cloud:
                raise
            self.runtime.invalidate_confirmed_host(self.expected_device_id)
            await self._async_fetch_cloud()
            await self.client.async_set_device_info(**params)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._async_fetch_data()
        except TapoAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except TapoError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_fetch_data(self) -> dict[str, Any]:
        if self._using_cloud:
            try:
                hosts = await self.runtime.async_rediscover()
            except TapoConnectionError:
                hosts = {}
            if host := hosts.get(self.expected_device_id):
                _LOGGER.debug(
                    "Restoring LAN control for Tapo L630 %s",
                    self.device["device_id"],
                )
                self.device["host"] = host
                self.client = self.runtime.client(host)
                self._using_cloud = False
                self._local_identity_validated = False
            else:
                return await self._async_fetch_cloud()

        old_host = self.device.get("host")
        try:
            if self.client is None:
                raise TapoConnectionError("The bulb has not been found on the LAN")
            info = await self.client.async_get_device_info()
            self._validate_identity(info)
            self._local_identity_validated = True
            return info
        except (
            TapoConnectionError,
            TapoAuthenticationError,
            TapoSessionError,
        ) as err:
            self._local_identity_validated = False
            self.runtime.invalidate_confirmed_host(self.expected_device_id)
            is_auth_error = isinstance(err, TapoAuthenticationError)
            hosts = await self.runtime.async_rediscover(force=is_auth_error)
            host = hosts.get(self.expected_device_id)
            if not host or host == old_host:
                return await self._async_fetch_cloud()
            self.device["host"] = host
            self.client = self.runtime.client(host)
            self._local_identity_validated = False
            try:
                info = await self.client.async_get_device_info()
                self._validate_identity(info)
                self._local_identity_validated = True
                return info
            except (
                TapoConnectionError,
                TapoAuthenticationError,
                TapoSessionError,
            ):
                return await self._async_fetch_cloud()

    async def _async_fetch_cloud(self) -> dict[str, Any]:
        """Fetch state through Tapo Cloud when local control is unavailable."""
        if not self._using_cloud:
            _LOGGER.debug(
                "Using Tapo Cloud fallback for L630 %s", self.device["device_id"]
            )
        self.client = self.runtime.cloud_client(str(self.device["device_id"]))
        self._using_cloud = True
        self._local_identity_validated = False
        info = await self.client.async_get_device_info()
        self._validate_identity(info)
        return info

    def _validate_identity(self, info: dict[str, Any]) -> None:
        """Ensure a host still represents the configured L630 bulb."""
        actual_id = normalize_device_id(info.get("device_id"))
        expected_ids = {
            self.expected_device_id,
            normalize_device_id(self.device.get("local_device_id")),
        }
        expected_ids.discard("")
        model = str(info.get("model", ""))
        if actual_id not in expected_ids or (
            model and not model.upper().startswith("L630")
        ):
            raise TapoConnectionError(
                "The configured address responded as a different Tapo device"
            )
