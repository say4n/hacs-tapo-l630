"""Local UDP discovery for modern Tapo devices."""

from __future__ import annotations

import asyncio
import binascii
from ipaddress import IPv4Address, ip_interface
import json
import logging
import os
import socket
import struct
from typing import Any, cast

from asyncio.transports import DatagramTransport
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from homeassistant.components.network import async_get_adapters
from homeassistant.core import HomeAssistant

from .exceptions import TapoConnectionError

_DISCOVERY_PORTS = (20002, 20004)
_LOGGER = logging.getLogger(__name__)


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


async def async_discover_l630s(
    hass: HomeAssistant, timeout: float = 5
) -> list[dict[str, Any]]:
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
    targets = await _async_broadcast_targets(hass)
    _LOGGER.debug("Sending Tapo discovery to: %s", ", ".join(sorted(targets)))
    try:
        for _ in range(3):
            for target in targets:
                for port in _DISCOVERY_PORTS:
                    transport.sendto(query, (target, port))
            await asyncio.sleep(timeout / 3)
    finally:
        transport.close()

    devices = [
        device
        for device in protocol.devices.values()
        if str(device.get("device_model", "")).upper().startswith("L630")
    ]
    _LOGGER.debug("Tapo discovery found %d L630 bulbs", len(devices))
    return devices


async def async_find_account_l630s(
    hass: HomeAssistant,
    cloud_devices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match cloud account bulbs to devices responding on the LAN."""
    local_devices = await async_discover_l630s(hass)
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
                "device_mac": cloud_device.get("deviceMac"),
                "host": host,
                "local_device_id": local and local.get("device_id"),
                "model": cloud_device.get("deviceModel")
                or (local and local.get("device_model")),
            }
        )

    _LOGGER.debug(
        "Matched %d of %d account L630 bulbs to LAN addresses",
        sum(isinstance(device.get("host"), str) for device in matched),
        len(matched),
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


def normalize_device_id(value: Any) -> str:
    """Return a normalized Tapo device ID."""
    return _normalize_identifier(value)


async def _async_broadcast_targets(hass: HomeAssistant) -> set[str]:
    """Return global and per-adapter IPv4 broadcast addresses.

    Include adapters disabled in Home Assistant's network selector because the
    selected default can be a Docker bridge while bulbs remain on a physical LAN.
    """
    targets = {"255.255.255.255"}
    for adapter in await async_get_adapters(hass):
        for address in adapter["ipv4"]:
            interface = ip_interface(
                f"{address['address']}/{address['network_prefix']}"
            )
            if interface.ip.is_loopback:
                continue
            _LOGGER.debug(
                "Tapo discovery adapter %s: %s (enabled=%s)",
                adapter["name"],
                interface,
                adapter["enabled"],
            )
            broadcast = interface.network.broadcast_address
            if broadcast not in {
                IPv4Address("127.255.255.255"),
                interface.ip,
            }:
                targets.add(str(broadcast))
    return targets
