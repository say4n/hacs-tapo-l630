"""Config flow for Tapo L630."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .cloud import TapoCloudClient
from .const import CONF_DEVICES, DOMAIN
from .discovery import async_find_account_l630s
from .exceptions import (
    NoDevicesFoundError,
    TapoAuthenticationError,
    TapoConnectionError,
    TapoError,
)

_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class TapoL630ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a Tapo L630 bulb."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle setup initiated by the user."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_USERNAME] = user_input[CONF_USERNAME].strip()
            try:
                devices = await self._async_validate(user_input, discover=True)
            except TapoAuthenticationError:
                errors["base"] = "invalid_auth"
            except TapoConnectionError:
                errors["base"] = "cannot_connect"
            except NoDevicesFoundError:
                errors["base"] = "no_devices"
            except TapoError:
                errors["base"] = "unknown"
            else:
                username = user_input[CONF_USERNAME]
                user_input[CONF_USERNAME] = username
                user_input[CONF_DEVICES] = devices
                if result := await self._async_consolidate_existing(user_input):
                    return result
                await self.async_set_unique_id(username.lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=username, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication for an existing entry."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate replacement Tapo credentials."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            updated_data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            try:
                await self._async_validate(updated_data, discover=False)
            except TapoAuthenticationError:
                errors["base"] = "invalid_auth"
            except TapoConnectionError:
                errors["base"] = "cannot_connect"
            except TapoError:
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(entry, data=updated_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        schema = vol.Schema(
            {
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=schema, errors=errors
        )

    async def _async_validate(
        self, data: dict[str, Any], *, discover: bool
    ) -> list[dict[str, Any]]:
        """Authenticate the account and optionally discover its local bulbs."""
        client = TapoCloudClient(
            async_get_clientsession(self.hass),
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
        )
        cloud_devices = await client.async_list_l630s()
        if discover:
            return await async_find_account_l630s(
                self.hass,
                cloud_devices,
            )
        return []

    async def _async_consolidate_existing(
        self, data: dict[str, Any]
    ) -> ConfigFlowResult | None:
        """Replace legacy per-bulb entries with one account entry."""
        username = data[CONF_USERNAME]
        entries = [
            entry
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if str(entry.data.get(CONF_USERNAME, "")).lower() == username.lower()
        ]
        if not entries:
            return None

        account_id = username.lower()
        account_entries = [entry for entry in entries if entry.unique_id == account_id]
        if len(entries) == 1 and account_entries:
            return self.async_abort(reason="already_configured")

        primary = account_entries[0] if account_entries else entries[0]
        self.hass.config_entries.async_update_entry(
            primary,
            data=data,
            title=username,
            unique_id=account_id,
            version=self.VERSION,
        )
        for entry in entries:
            if entry is not primary:
                await self.hass.config_entries.async_remove(entry.entry_id)
        await self.hass.config_entries.async_reload(primary.entry_id)
        return self.async_abort(reason="account_updated")
