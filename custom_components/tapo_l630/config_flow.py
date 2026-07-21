"""Config flow for Tapo L630."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from yarl import URL

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import TapoL630Client
from .const import DOMAIN
from .exceptions import (
    TapoAuthenticationError,
    TapoConnectionError,
    TapoError,
    UnsupportedDeviceError,
)
from .util import decode_nickname

_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class TapoL630ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a Tapo L630 bulb."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle setup initiated by the user."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                user_input[CONF_HOST] = _normalize_host(user_input[CONF_HOST])
                info = await self._async_validate(user_input)
                model = str(info.get("model", ""))
                if not model.upper().startswith("L630"):
                    raise UnsupportedDeviceError
            except ValueError:
                errors["base"] = "invalid_host"
            except TapoAuthenticationError:
                errors["base"] = "invalid_auth"
            except TapoConnectionError:
                errors["base"] = "cannot_connect"
            except UnsupportedDeviceError:
                errors["base"] = "unsupported_device"
            except TapoError:
                errors["base"] = "unknown"
            else:
                device_id = str(info.get("device_id") or user_input[CONF_HOST])
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: user_input[CONF_HOST]}
                )
                title = _device_name(info) or f"Tapo L630 ({user_input[CONF_HOST]})"
                return self.async_create_entry(title=title, data=user_input)

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
            updated_data = {**entry.data, **user_input}
            try:
                await self._async_validate(updated_data)
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
                vol.Required(
                    CONF_USERNAME, default=entry.data[CONF_USERNAME]
                ): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=schema, errors=errors
        )

    async def _async_validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Connect and return validated device information."""
        client = TapoL630Client(
            async_get_clientsession(self.hass),
            data[CONF_HOST],
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
        )
        return await client.async_get_device_info()


def _device_name(info: dict[str, Any]) -> str | None:
    """Get a useful unencoded device name."""
    return decode_nickname(info.get("nickname"))


def _normalize_host(value: str) -> str:
    """Validate and normalize an IP address or hostname."""
    host = value.strip().rstrip(".")
    if not host or "://" in host or "/" in host or "?" in host or "#" in host:
        raise ValueError
    URL.build(scheme="http", host=host)
    return host
