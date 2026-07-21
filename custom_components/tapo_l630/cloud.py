"""Tapo Cloud account API used to enumerate L630 bulbs."""

from __future__ import annotations

import asyncio
import json
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
_TOKEN_EXPIRED_CODES = {-20675, -20651}
_AUTHENTICATION_ERROR_CODES = {
    -20607,
    -20606,
    -20605,
    -20604,
    -20603,
    -20602,
    -20601,
    -20600,
    -1501,
}


class _TokenExpiredError(TapoError):
    """Raised when the cloud token needs refreshing."""


class TapoCloudClient:
    """Authenticate with Tapo Cloud and list account devices."""

    def __init__(
        self, session: ClientSession, username: str, password: str
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._terminal_id = str(uuid4())
        self._token: str | None = None
        self._devices: dict[str, dict[str, Any]] = {}
        self._login_lock = asyncio.Lock()

    async def async_list_l630s(self) -> list[dict[str, Any]]:
        """Return all L630 bulbs linked to the account."""
        for attempt in range(2):
            await self._async_login()
            token = self._token
            try:
                response = await self._async_post(
                    {"method": "getDeviceList"}, token=token
                )
            except _TokenExpiredError:
                await self._async_invalidate_token(token)
                if attempt == 0:
                    continue
                raise TapoConnectionError("Unable to refresh Tapo Cloud session")
            break
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
        self._devices = {device["deviceId"]: device for device in bulbs}
        return bulbs

    def device_client(self, device_id: str) -> TapoCloudDeviceClient:
        """Return a client that controls one bulb through Tapo Cloud."""
        return TapoCloudDeviceClient(self, device_id)

    async def async_passthrough(
        self, device_id: str, method: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Relay a device request through Tapo Cloud."""
        request: dict[str, Any] = {"method": method}
        if params is not None:
            request["params"] = params

        for attempt in range(2):
            if self._token is None or device_id not in self._devices:
                await self.async_list_l630s()
            device = self._devices.get(device_id)
            if device is None:
                raise TapoError("The bulb is no longer linked to this account")
            app_server_url = device.get("appServerUrl")
            if not isinstance(app_server_url, str) or not app_server_url:
                raise TapoError("Tapo Cloud did not provide a device relay URL")

            try:
                token = self._token
                response = await self._async_post(
                    {
                        "method": "passthrough",
                        "params": {
                            "deviceId": device_id,
                            "requestData": json.dumps(
                                request, separators=(",", ":")
                            ),
                        },
                    },
                    token=token,
                    url=app_server_url,
                )
            except _TokenExpiredError:
                await self._async_invalidate_token(token)
                if attempt == 0:
                    continue
                raise TapoConnectionError("Unable to refresh Tapo Cloud session")

            result = response.get("result")
            if not isinstance(result, dict):
                raise TapoError("Tapo Cloud returned an invalid relay response")
            response_data = result.get("responseData")
            if isinstance(response_data, str):
                try:
                    response_data = json.loads(response_data)
                except json.JSONDecodeError as err:
                    raise TapoError(
                        "Tapo Cloud returned invalid device data"
                    ) from err
            if not isinstance(response_data, dict):
                raise TapoError("Tapo Cloud returned invalid device data")
            error_code = response_data.get("error_code", 0)
            if error_code:
                raise TapoError(f"Cloud device error {error_code}")
            return response_data.get("result")
        raise TapoAuthenticationError("Unable to refresh the Tapo Cloud session")

    async def _async_login(self) -> None:
        async with self._login_lock:
            if self._token is not None:
                return
            login = await self._async_post(
                {
                    "method": "login",
                    "params": {
                        "appType": "Tapo_Ios",
                        "cloudPassword": self._password,
                        "cloudUserName": self._username,
                        "terminalUUID": self._terminal_id,
                    },
                },
                authentication=True,
            )
            result = login.get("result")
            if not isinstance(result, dict) or not isinstance(
                result.get("token"), str
            ):
                raise TapoAuthenticationError(
                    "Tapo Cloud did not return a login token"
                )
            self._token = result["token"]

    async def _async_invalidate_token(self, token: str | None) -> None:
        """Clear an expired token without clobbering a concurrent refresh."""
        async with self._login_lock:
            if self._token == token:
                self._token = None

    async def _async_post(
        self,
        payload: dict[str, Any],
        *,
        token: str | None = None,
        authentication: bool = False,
        url: str = _BASE_URL,
    ) -> dict[str, Any]:
        try:
            async with self._session.post(
                url,
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
            if error_code in _TOKEN_EXPIRED_CODES:
                raise _TokenExpiredError
            message = data.get("msg") or f"error {error_code}"
            if authentication and error_code in _AUTHENTICATION_ERROR_CODES:
                raise TapoAuthenticationError(str(message))
            if authentication:
                raise TapoConnectionError(f"Tapo Cloud login failed: {message}")
            raise TapoError(f"Tapo Cloud API {message}")
        return data


class TapoCloudDeviceClient:
    """Control one L630 through Tapo Cloud passthrough."""

    def __init__(self, cloud: TapoCloudClient, device_id: str) -> None:
        self._cloud = cloud
        self._device_id = device_id

    async def async_get_device_info(self) -> dict[str, Any]:
        """Return the bulb state through the cloud relay."""
        result = await self._cloud.async_passthrough(
            self._device_id, "get_device_info"
        )
        if not isinstance(result, dict):
            raise TapoError("Tapo Cloud returned invalid bulb information")
        return result

    async def async_set_device_info(self, **params: Any) -> None:
        """Update bulb properties through the cloud relay."""
        await self._cloud.async_passthrough(
            self._device_id, "set_device_info", params
        )
