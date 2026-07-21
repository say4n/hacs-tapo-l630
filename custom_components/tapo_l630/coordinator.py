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
from .exceptions import TapoAuthenticationError, TapoError

_LOGGER = logging.getLogger(__name__)


class TapoL630Coordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll and update a Tapo L630 bulb."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: TapoL630Client,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.config_entry = config_entry
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.async_get_device_info()
        except TapoAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except TapoError as err:
            raise UpdateFailed(str(err)) from err
