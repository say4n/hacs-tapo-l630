"""Light entity for Tapo L630."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MAX_COLOR_TEMP_KELVIN, MIN_COLOR_TEMP_KELVIN
from .coordinator import TapoL630Coordinator
from .util import decode_nickname


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the light entity."""
    async_add_entities(
        TapoL630Light(coordinator)
        for coordinator in entry.runtime_data.coordinators
    )


class TapoL630Light(CoordinatorEntity[TapoL630Coordinator], LightEntity):
    """Representation of a Tapo L630 bulb."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.HS}
    _attr_min_color_temp_kelvin = MIN_COLOR_TEMP_KELVIN
    _attr_max_color_temp_kelvin = MAX_COLOR_TEMP_KELVIN

    def __init__(self, coordinator: TapoL630Coordinator) -> None:
        super().__init__(coordinator)
        info = coordinator.data
        device_id = str(info.get("device_id") or coordinator.config_entry.unique_id)
        model = str(info.get("model") or "L630")
        self._attr_unique_id = device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            manufacturer="TP-Link",
            model=model,
            name=decode_nickname(info.get("nickname"))
            or info.get("alias")
            or "Tapo L630",
            sw_version=info.get("fw_ver"),
        )

    @property
    def is_on(self) -> bool:
        """Return whether the light is on."""
        return bool(self.coordinator.data.get("device_on"))

    @property
    def brightness(self) -> int | None:
        """Return brightness on Home Assistant's 0-255 scale."""
        value = self.coordinator.data.get("brightness")
        return round(float(value) * 255 / 100) if value is not None else None

    @property
    def color_mode(self) -> ColorMode:
        """Return the bulb's active color mode."""
        if int(self.coordinator.data.get("color_temp") or 0) > 0:
            return ColorMode.COLOR_TEMP
        return ColorMode.HS

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the current color temperature."""
        value = int(self.coordinator.data.get("color_temp") or 0)
        return value or None

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return current hue and saturation."""
        if self.color_mode != ColorMode.HS:
            return None
        return (
            float(self.coordinator.data.get("hue") or 0),
            float(self.coordinator.data.get("saturation") or 0),
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the bulb and apply requested attributes together."""
        params: dict[str, Any] = {"device_on": True}
        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
            params["brightness"] = max(1, round(brightness * 100 / 255))
        if ATTR_HS_COLOR in kwargs:
            params["hue"], params["saturation"] = kwargs[ATTR_HS_COLOR]
            params["color_temp"] = 0
        elif ATTR_COLOR_TEMP_KELVIN in kwargs:
            params["color_temp"] = max(
                MIN_COLOR_TEMP_KELVIN,
                min(MAX_COLOR_TEMP_KELVIN, kwargs[ATTR_COLOR_TEMP_KELVIN]),
            )

        await self.coordinator.client.async_set_device_info(**params)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the bulb."""
        await self.coordinator.client.async_set_device_info(device_on=False)
        await self.coordinator.async_request_refresh()
