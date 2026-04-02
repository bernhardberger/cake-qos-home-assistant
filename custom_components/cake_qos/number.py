"""Number platform for CAKE QoS — autorate config tunables + static rates."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CakeQosCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class CakeQosNumberDescription(NumberEntityDescription):
    """Number description with config key mapping."""

    config_key: str
    unit: str = "kbps"
    is_static_rate: bool = False


# ── Autorate config tunables ────────────────────────────────────────────
AUTORATE_NUMBER_DESCRIPTIONS: tuple[CakeQosNumberDescription, ...] = (
    CakeQosNumberDescription(
        key="base_dl_rate",
        name="Base download rate",
        icon="mdi:download",
        native_min_value=50,
        native_max_value=500,
        native_step=10,
        native_unit_of_measurement="Mbit/s",
        config_key="base_dl_shaper_rate_kbps",
    ),
    CakeQosNumberDescription(
        key="base_ul_rate",
        name="Base upload rate",
        icon="mdi:upload",
        native_min_value=10,
        native_max_value=150,
        native_step=5,
        native_unit_of_measurement="Mbit/s",
        config_key="base_ul_shaper_rate_kbps",
    ),
    CakeQosNumberDescription(
        key="dl_delay_threshold",
        name="Download delay threshold",
        icon="mdi:timer-alert-outline",
        native_min_value=10,
        native_max_value=200,
        native_step=5,
        native_unit_of_measurement="ms",
        config_key="dl_owd_delta_delay_thr_ms",
        unit="ms",
    ),
    CakeQosNumberDescription(
        key="ul_delay_threshold",
        name="Upload delay threshold",
        icon="mdi:timer-alert-outline",
        native_min_value=10,
        native_max_value=200,
        native_step=5,
        native_unit_of_measurement="ms",
        config_key="ul_owd_delta_delay_thr_ms",
        unit="ms",
    ),
)

# ── Static CAKE rate controls ──────────────────────────────────────────
STATIC_NUMBER_DESCRIPTIONS: tuple[CakeQosNumberDescription, ...] = (
    CakeQosNumberDescription(
        key="static_dl_rate",
        name="Static download rate",
        icon="mdi:download-lock",
        native_min_value=10,
        native_max_value=600,
        native_step=10,
        native_unit_of_measurement="Mbit/s",
        config_key="dl_rate_mbit",
        is_static_rate=True,
    ),
    CakeQosNumberDescription(
        key="static_ul_rate",
        name="Static upload rate",
        icon="mdi:upload-lock",
        native_min_value=5,
        native_max_value=200,
        native_step=5,
        native_unit_of_measurement="Mbit/s",
        config_key="ul_rate_mbit",
        is_static_rate=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up CAKE QoS number entities."""
    coordinator: CakeQosCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[NumberEntity] = []
    for desc in AUTORATE_NUMBER_DESCRIPTIONS:
        entities.append(CakeQosAutorateNumber(coordinator, desc, entry))
    for desc in STATIC_NUMBER_DESCRIPTIONS:
        entities.append(CakeQosStaticRateNumber(coordinator, desc, entry))
    async_add_entities(entities)


class CakeQosAutorateNumber(CoordinatorEntity[CakeQosCoordinator], NumberEntity):
    """Number entity for a cake-autorate config tunable."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG
    entity_description: CakeQosNumberDescription

    def __init__(
        self,
        coordinator: CakeQosCoordinator,
        description: CakeQosNumberDescription,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
        )

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        config = self.coordinator.data.get("config", {})
        raw = config.get(self.entity_description.config_key)
        if raw is None:
            return None
        # Config stores kbps — display as Mbit/s for rate controls
        if self.entity_description.unit == "kbps":
            return round(raw / 1000, 0)
        return float(raw)

    async def async_set_native_value(self, value: float) -> None:
        """Update the config value on the exporter."""
        desc = self.entity_description
        # Convert Mbit/s back to kbps for rate controls
        if desc.unit == "kbps":
            api_value = int(value * 1000)
        else:
            api_value = value

        result = await self.coordinator.client.update_config(
            {desc.config_key: api_value}
        )
        if result.get("status") == "ok":
            # Restart autorate to apply the new config
            await self.coordinator.client.autorate_restart()
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to update %s: %s", desc.config_key, result)


class CakeQosStaticRateNumber(CoordinatorEntity[CakeQosCoordinator], NumberEntity):
    """Number entity for static CAKE shaper rates (used when autorate is OFF)."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER
    entity_description: CakeQosNumberDescription

    def __init__(
        self,
        coordinator: CakeQosCoordinator,
        description: CakeQosNumberDescription,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
        )

    @property
    def native_value(self) -> float | None:
        """Read persisted static rate setting from exporter."""
        if not self.coordinator.data:
            return None
        rates = self.coordinator.data.get("static_rates", {})
        return rates.get(self.entity_description.config_key)

    async def async_set_native_value(self, value: float) -> None:
        """Set static CAKE rates via apply-cake.sh.

        We need both DL and UL rates for the tc call. Read the current
        value for the other direction from the persisted static rates.
        """
        desc = self.entity_description
        rates = self.coordinator.data.get("static_rates", {}) if self.coordinator.data else {}

        if "dl" in desc.key:
            dl = value
            ul = rates.get("ul_rate_mbit", 80)
        else:
            dl = rates.get("dl_rate_mbit", 400)
            ul = value

        result = await self.coordinator.client.set_static_rates(dl, ul)
        if result.get("status") == "ok":
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to set static rate: %s", result)
