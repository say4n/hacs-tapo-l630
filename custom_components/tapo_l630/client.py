"""Local KLAP protocol client for Tapo L630 bulbs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import struct
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from yarl import URL

from .exceptions import (
    TapoAuthenticationError,
    TapoConnectionError,
    TapoError,
    TapoSessionError,
)

_TIMEOUT = ClientTimeout(total=10)


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _sha1(data: bytes) -> bytes:
    return hashlib.sha1(data, usedforsecurity=False).digest()


class TapoL630Client:
    """Communicate with one bulb over its local KLAP endpoint."""

    def __init__(
        self, session: ClientSession, host: str, username: str, password: str
    ) -> None:
        self._session = session
        self._base_url = URL.build(scheme="http", host=host) / "app"
        self._username = username
        self._password = password
        self._cookie: str | None = None
        self._key: bytes | None = None
        self._iv: bytes | None = None
        self._signature_key: bytes | None = None
        self._sequence = 0
        self._handshake_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()

    async def async_get_device_info(self) -> dict[str, Any]:
        """Return the bulb's current state and identifying information."""
        result = await self.async_request("get_device_info")
        if not isinstance(result, dict):
            raise TapoError("The bulb returned invalid device information")
        return result

    async def async_set_device_info(self, **params: Any) -> None:
        """Update one or more bulb properties in a single request."""
        await self.async_request("set_device_info", params)

    async def async_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Send an encrypted request, reconnecting once if the session expired."""
        async with self._request_lock:
            for attempt in range(2):
                if self._cookie is None:
                    await self._async_handshake()
                try:
                    return await self._async_send(method, params)
                except TapoSessionError:
                    self._clear_session()
                    if attempt:
                        raise
        raise TapoSessionError("Unable to establish a Tapo session")

    async def _async_handshake(self) -> None:
        async with self._handshake_lock:
            if self._cookie is not None:
                return

            local_seed = os.urandom(16)
            try:
                async with self._session.post(
                    self._base_url / "handshake1",
                    data=local_seed,
                    timeout=_TIMEOUT,
                ) as response:
                    if response.status >= 400:
                        raise TapoConnectionError(
                            f"Handshake failed with HTTP {response.status}"
                        )
                    response_bytes = await response.read()
                    cookies = response.headers.getall("Set-Cookie", [])
            except (ClientError, TimeoutError) as err:
                raise TapoConnectionError("Unable to connect to the bulb") from err

            if len(response_bytes) < 48 or not cookies:
                raise TapoConnectionError("The bulb returned an invalid handshake")

            remote_seed = response_bytes[:16]
            server_hash = response_bytes[16:]
            auth_hash = _sha256(
                _sha1(self._username.encode()) + _sha1(self._password.encode())
            )
            expected_hash = _sha256(local_seed + remote_seed + auth_hash)
            if expected_hash != server_hash:
                raise TapoAuthenticationError("Invalid Tapo username or password")

            cookie = cookies[0].split(";", 1)[0]
            payload = _sha256(remote_seed + local_seed + auth_hash)
            try:
                async with self._session.post(
                    self._base_url / "handshake2",
                    data=payload,
                    headers={"Cookie": cookie},
                    timeout=_TIMEOUT,
                ) as response:
                    if response.status >= 400:
                        raise TapoAuthenticationError(
                            f"Authentication failed with HTTP {response.status}"
                        )
                    await response.read()
            except (ClientError, TimeoutError) as err:
                raise TapoConnectionError(
                    "Connection failed during authentication"
                ) from err

            self._cookie = cookie
            self._key = _sha256(b"lsk" + local_seed + remote_seed + auth_hash)[:16]
            derived_iv = _sha256(b"iv" + local_seed + remote_seed + auth_hash)
            self._iv = derived_iv[:12]
            self._sequence = struct.unpack(">i", derived_iv[-4:])[0]
            self._signature_key = _sha256(
                b"ldk" + local_seed + remote_seed + auth_hash
            )[:28]

    async def _async_send(
        self, method: str, params: dict[str, Any] | None
    ) -> Any:
        if self._key is None or self._iv is None or self._signature_key is None:
            raise TapoSessionError("Tapo session is not initialized")

        self._sequence = (
            -2_147_483_648 if self._sequence == 2_147_483_647 else self._sequence + 1
        )
        sequence = struct.pack(">i", self._sequence)
        request: dict[str, Any] = {"method": method}
        if params is not None:
            request["params"] = params

        plaintext = json.dumps(request, separators=(",", ":")).encode()
        padder = PKCS7(128).padder()
        padded = padder.update(plaintext) + padder.finalize()
        encryptor = Cipher(
            algorithms.AES(self._key), modes.CBC(self._iv + sequence)
        ).encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()
        signature = _sha256(self._signature_key + sequence + ciphertext)

        try:
            async with self._session.post(
                self._base_url / "request",
                params={"seq": self._sequence},
                data=signature + ciphertext,
                headers={"Cookie": self._cookie or ""},
                timeout=_TIMEOUT,
            ) as response:
                if response.status == 403:
                    raise TapoSessionError("Tapo session expired")
                if response.status >= 400:
                    raise TapoConnectionError(
                        f"The bulb returned HTTP {response.status}"
                    )
                encrypted_response = await response.read()
        except TapoSessionError:
            raise
        except (ClientError, TimeoutError) as err:
            self._clear_session()
            raise TapoConnectionError("Lost connection to the bulb") from err

        if len(encrypted_response) <= 32:
            raise TapoSessionError("The bulb returned an invalid encrypted response")

        response_ciphertext = encrypted_response[32:]

        try:
            decryptor = Cipher(
                algorithms.AES(self._key), modes.CBC(self._iv + sequence)
            ).decryptor()
            padded_response = (
                decryptor.update(response_ciphertext) + decryptor.finalize()
            )
            unpadder = PKCS7(128).unpadder()
            decoded = unpadder.update(padded_response) + unpadder.finalize()
            response_data = json.loads(decoded)
        except (ValueError, json.JSONDecodeError) as err:
            raise TapoSessionError("Unable to decrypt the bulb response") from err

        if not isinstance(response_data, dict):
            raise TapoSessionError("The bulb returned an invalid response")

        error_code = response_data.get("error_code", 0)
        if error_code:
            raise TapoError(f"The bulb returned error {error_code}")
        return response_data.get("result")

    def _clear_session(self) -> None:
        self._cookie = None
        self._key = None
        self._iv = None
        self._signature_key = None
