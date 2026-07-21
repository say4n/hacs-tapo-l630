"""Tapo Cloud account API used to enumerate L630 bulbs."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from aiohttp import ClientError, ClientSession, ClientTimeout

from .exceptions import (
    NoDevicesFoundError,
    TapoAuthenticationError,
    TapoConnectionError,
    TapoError,
)

_BASE_URL = "https://eu-wap.tplinkcloud.com/"
_TIMEOUT = ClientTimeout(total=15)


class TapoCloudClient:
    """Authenticate with Tapo Cloud and list account devices."""

    def __init__(
        self, session: ClientSession, username: str, password: str
    ) -> None:
        self._session = session
        self._username = username
        self._password = password

    async def async_list_l630s(self) -> list[dict[str, Any]]:
        """Return all L630 bulbs linked to the account."""
        login = await self._async_post(
            {
                "method": "login",
                "params": {
                    "appType": "Tapo_Ios",
                    "cloudPassword": self._password,
                    "cloudUserName": self._username,
                    "terminalUUID": str(uuid4()),
                },
            },
            authentication=True,
        )
        result = login.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("token"), str):
            raise TapoAuthenticationError("Tapo Cloud did not return a login token")

        response = await self._async_post(
            {"method": "getDeviceList"}, token=result["token"]
        )
        response_result = response.get("result")
        if not isinstance(response_result, dict):
            raise TapoError("Tapo Cloud returned an invalid device list")
        devices = response_result.get("deviceList")
        if not isinstance(devices, list):
            raise TapoError("Tapo Cloud returned an invalid device list")

        bulbs = [
            device
            for device in devices
            if isinstance(device, dict)
            and device.get("deviceType") == "SMART.TAPOBULB"
            and str(device.get("deviceModel", "")).upper().startswith("L630")
            and isinstance(device.get("deviceId"), str)
        ]
        if not bulbs:
            raise NoDevicesFoundError("No Tapo L630 bulbs are linked to this account")
        return bulbs

    async def _async_post(
        self,
        payload: dict[str, Any],
        *,
        token: str | None = None,
        authentication: bool = False,
    ) -> dict[str, Any]:
        try:
            async with self._session.post(
                _BASE_URL,
                params={"token": token} if token else None,
                json=payload,
                timeout=_TIMEOUT,
            ) as response:
                if response.status >= 400:
                    raise TapoConnectionError(
                        f"Tapo Cloud returned HTTP {response.status}"
                    )
                data = await response.json()
        except (ClientError, TimeoutError, ValueError) as err:
            raise TapoConnectionError("Unable to connect to Tapo Cloud") from err

        if not isinstance(data, dict):
            raise TapoError("Tapo Cloud returned an invalid response")
        error_code = data.get("error_code", 0)
        if error_code:
            message = data.get("msg") or f"error {error_code}"
            if authentication:
                raise TapoAuthenticationError(str(message))
            raise TapoError(f"Tapo Cloud API {message}")
        return data
