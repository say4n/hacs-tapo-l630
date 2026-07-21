"""Local UDP discovery for modern Tapo devices."""

from __future__ import annotations

import asyncio
import binascii
import json
import os
import socket
import struct
from typing import Any, cast

from asyncio.transports import DatagramTransport
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .exceptions import TapoConnectionError

_DISCOVERY_PORTS = (20002, 20004)


class _TapoDiscoveryProtocol(asyncio.DatagramProtocol):
    """Collect responses to a Tapo discovery broadcast."""

    def __init__(self) -> None:
        self.transport: DatagramTransport | None = None
        self.devices: dict[str, dict[str, Any]] = {}

    def connection_made(self, transport: DatagramTransport) -> None:
        self.transport = cast(DatagramTransport, transport)
        sock = transport.get_extra_info("socket")
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if addr[1] not in _DISCOVERY_PORTS or len(data) <= 16:
            return
        try:
            response = json.loads(data[16:])
            result = response["result"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return
        if not isinstance(result, dict):
            return
        result = {**result, "host": addr[0]}
        device_id = result.get("device_id")
        if isinstance(device_id, str):
            self.devices[device_id] = result

    def error_received(self, exc: Exception) -> None:
        """Ignore per-interface broadcast errors."""


async def async_discover_l630s(timeout: float = 5) -> list[dict[str, Any]]:
    """Broadcast a modern Tapo discovery request and return L630 responses."""
    loop = asyncio.get_running_loop()
    try:
        transport, protocol = await loop.create_datagram_endpoint(
            _TapoDiscoveryProtocol,
            local_addr=("0.0.0.0", 0),
            family=socket.AF_INET,
        )
    except OSError as err:
        raise TapoConnectionError("Unable to start local Tapo discovery") from err

    protocol = cast(_TapoDiscoveryProtocol, protocol)
    query = _build_discovery_query()
    try:
        for _ in range(3):
            for port in _DISCOVERY_PORTS:
                transport.sendto(query, ("255.255.255.255", port))
            await asyncio.sleep(timeout / 3)
    finally:
        transport.close()

    return [
        device
        for device in protocol.devices.values()
        if str(device.get("device_model", "")).upper().startswith("L630")
    ]


async def async_find_account_l630s(
    cloud_devices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match cloud account bulbs to devices responding on the LAN."""
    local_devices = await async_discover_l630s()
    local_by_id = {
        _normalize_identifier(device.get("device_id")): device
        for device in local_devices
    }
    local_by_mac = {
        _normalize_identifier(device.get("mac")): device for device in local_devices
    }

    matched: list[dict[str, Any]] = []
    for cloud_device in cloud_devices:
        local = local_by_id.get(
            _normalize_identifier(cloud_device.get("deviceId"))
        ) or local_by_mac.get(_normalize_identifier(cloud_device.get("deviceMac")))
        host = local.get("host") if local else None
        matched.append(
            {
                "alias": cloud_device.get("alias"),
                "device_id": cloud_device.get("deviceId")
                or (local and local.get("device_id")),
                "host": host,
                "model": cloud_device.get("deviceModel")
                or (local and local.get("device_model")),
            }
        )

    return matched


def _build_discovery_query() -> bytes:
    """Build a Tapo Discovery Protocol v2 probe."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    payload = json.dumps(
        {"params": {"rsa_key": public_key.decode()}}, separators=(",", ":")
    ).encode()
    header = struct.pack(
        ">BBHHBBII",
        2,
        0,
        1,
        len(payload),
        17,
        0,
        int.from_bytes(os.urandom(4), "big"),
        0x5A6B7C8D,
    )
    query = bytearray(header + payload)
    query[12:16] = binascii.crc32(query).to_bytes(4, "big")
    return bytes(query)


def _normalize_identifier(value: Any) -> str:
    """Normalize device IDs and MAC addresses for matching."""
    return str(value or "").lower().replace(":", "").replace("-", "")


def map_hosts_by_device_id(
    devices: list[dict[str, Any]],
) -> dict[str, str]:
    """Map normalized device IDs to their discovered hosts."""
    return {
        _normalize_identifier(device.get("device_id")): device["host"]
        for device in devices
        if isinstance(device.get("host"), str)
    }


def normalize_device_id(value: Any) -> str:
    """Return a normalized Tapo device ID."""
    return _normalize_identifier(value)
