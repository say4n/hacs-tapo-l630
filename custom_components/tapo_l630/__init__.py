"""Tapo L630 integration."""

from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_DEVICES, PLATFORMS
from .coordinator import TapoL630Coordinator
from .exceptions import TapoAuthenticationError, TapoConnectionError
from .runtime import TapoL630Runtime


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Tapo L630 config entry."""
    runtime = TapoL630Runtime(hass, entry, async_get_clientsession(hass))
    try:
        await runtime.async_rediscover(force=True)
    except TapoConnectionError:
        pass

    runtime.coordinators = [
        TapoL630Coordinator(hass, entry, runtime, device)
        for device in runtime.devices
    ]
    results = await asyncio.gather(
        *(coordinator.async_initialize() for coordinator in runtime.coordinators),
        return_exceptions=True,
    )
    if auth_error := next(
        (result for result in results if isinstance(result, TapoAuthenticationError)),
        None,
    ):
        raise ConfigEntryAuthFailed from auth_error

    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Tapo L630 config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a per-bulb entry to the account-level data model."""
    if entry.version != 1:
        return True

    data = dict(entry.data)
    host = data.pop(CONF_HOST)
    data[CONF_DEVICES] = [
        {"device_id": entry.unique_id, "host": host, "model": "L630"}
    ]
    hass.config_entries.async_update_entry(
        entry,
        data=data,
        version=2,
    )
    return True
