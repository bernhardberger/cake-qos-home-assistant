"""Sensor platform for CAKE QoS integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfDataRate, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CakeQosCoordinator

# Load condition labels for display
LOAD_CONDITION_MAP = {
    "dl_idle": "Idle",
    "dl_low": "Low",
    "dl_refl_wait": "Waiting",
    "dl_high": "High",
    "ul_idle": "Idle",
    "ul_low": "Low",
    "ul_refl_wait": "Waiting",
    "ul_high": "High",
}


@dataclass(frozen=True, kw_only=True)
class CakeQosSensorDescription(SensorEntityDescription):
    """Sensor description with a value extraction function."""

    value_fn: Callable[[dict[str, Any]], Any]


def _autorate(key: str) -> Callable[[dict], Any]:
    """Extract a value from the autorate section."""
    def fn(data: dict) -> Any:
        return data.get("autorate", {}).get(key)
    return fn


def _cake(direction: str, key: str) -> Callable[[dict], Any]:
    """Extract a value from the cake qdisc section."""
    def fn(data: dict) -> Any:
        return data.get("cake", {}).get(direction, {}).get(key)
    return fn


def _shaper_rate(direction: str) -> Callable[[dict], Any]:
    """Extract the live CAKE shaper rate from tc (ground truth).

    tc bandwidth is what's actually applied to the qdisc — autorate
    SUMMARY values are a stale log artifact and unreliable for display.
    """
    def fn(data: dict) -> Any:
        return data.get("cake", {}).get(direction, {}).get("bandwidth_mbit")
    return fn


def _cake_tin(direction: str, key: str) -> Callable[[dict], Any]:
    """Extract a value from the cake tin (flow stats)."""
    def fn(data: dict) -> Any:
        return data.get("cake", {}).get(direction, {}).get("tin", {}).get(key)
    return fn


def _load_condition(key: str) -> Callable[[dict], Any]:
    """Extract load condition with human-readable mapping."""
    def fn(data: dict) -> Any:
        raw = data.get("autorate", {}).get(key)
        return LOAD_CONDITION_MAP.get(raw, raw)
    return fn


def _service_active(data: dict) -> Any:
    """Extract autorate service state."""
    return data.get("service", {}).get("active", "unknown")


SENSOR_DESCRIPTIONS: tuple[CakeQosSensorDescription, ...] = (
    # ── Autorate rates ──────────────────────────────────────────────────
    CakeQosSensorDescription(
        key="cake_dl_rate",
        name="Download shaper rate",
        icon="mdi:download",
        native_unit_of_measurement="Mbit/s",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_shaper_rate("download"),
    ),
    CakeQosSensorDescription(
        key="cake_ul_rate",
        name="Upload shaper rate",
        icon="mdi:upload",
        native_unit_of_measurement="Mbit/s",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_shaper_rate("upload"),
    ),
    # ── Achieved throughput ─────────────────────────────────────────────
    CakeQosSensorDescription(
        key="dl_achieved",
        name="Download achieved",
        icon="mdi:download-network",
        native_unit_of_measurement="Mbit/s",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_autorate("dl_achieved_mbit"),
    ),
    CakeQosSensorDescription(
        key="ul_achieved",
        name="Upload achieved",
        icon="mdi:upload-network",
        native_unit_of_measurement="Mbit/s",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_autorate("ul_achieved_mbit"),
    ),
    # ── Load conditions ─────────────────────────────────────────────────
    CakeQosSensorDescription(
        key="dl_load_condition",
        name="Download load",
        icon="mdi:speedometer",
        value_fn=_load_condition("dl_load_condition"),
    ),
    CakeQosSensorDescription(
        key="ul_load_condition",
        name="Upload load",
        icon="mdi:speedometer",
        value_fn=_load_condition("ul_load_condition"),
    ),
    # ── Latency (from CAKE tin stats) ───────────────────────────────────
    CakeQosSensorDescription(
        key="dl_avg_delay",
        name="Download delay",
        icon="mdi:timer-outline",
        native_unit_of_measurement="µs",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_cake_tin("download", "avg_delay_us"),
    ),
    CakeQosSensorDescription(
        key="ul_avg_delay",
        name="Upload delay",
        icon="mdi:timer-outline",
        native_unit_of_measurement="µs",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_cake_tin("upload", "avg_delay_us"),
    ),
    # ── Latency delta (from autorate OWD measurements) ──────────────────
    CakeQosSensorDescription(
        key="dl_latency_delta",
        name="Download latency delta",
        icon="mdi:swap-vertical",
        native_unit_of_measurement="µs",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        value_fn=_autorate("dl_avg_latency_delta_us"),
    ),
    CakeQosSensorDescription(
        key="ul_latency_delta",
        name="Upload latency delta",
        icon="mdi:swap-vertical",
        native_unit_of_measurement="µs",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        value_fn=_autorate("ul_avg_latency_delta_us"),
    ),
    # ── Drops & flows ───────────────────────────────────────────────────
    CakeQosSensorDescription(
        key="dl_drops",
        name="Download drops",
        icon="mdi:package-variant-remove",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_cake("download", "drops"),
    ),
    CakeQosSensorDescription(
        key="ul_drops",
        name="Upload drops",
        icon="mdi:package-variant-remove",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_cake("upload", "drops"),
    ),
    CakeQosSensorDescription(
        key="dl_sparse_flows",
        name="Download sparse flows",
        icon="mdi:lan",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_cake_tin("download", "sparse_flows"),
    ),
    CakeQosSensorDescription(
        key="dl_bulk_flows",
        name="Download bulk flows",
        icon="mdi:lan",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_cake_tin("download", "bulk_flows"),
    ),
    # ── CAKE bandwidth (from tc, not autorate) ──────────────────────────
    CakeQosSensorDescription(
        key="dl_bandwidth",
        name="Download bandwidth",
        icon="mdi:speedometer",
        native_unit_of_measurement="Mbit/s",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=_cake("download", "bandwidth_mbit"),
    ),
    CakeQosSensorDescription(
        key="ul_bandwidth",
        name="Upload bandwidth",
        icon="mdi:speedometer",
        native_unit_of_measurement="Mbit/s",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=_cake("upload", "bandwidth_mbit"),
    ),
    # ── Service state ───────────────────────────────────────────────────
    CakeQosSensorDescription(
        key="autorate_state",
        name="Autorate service",
        icon="mdi:cog-play",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_service_active,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up CAKE QoS sensors from a config entry."""
    coordinator: CakeQosCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CakeQosSensor(coordinator, desc, entry)
        for desc in SENSOR_DESCRIPTIONS
    )


class CakeQosSensor(CoordinatorEntity[CakeQosCoordinator], SensorEntity):
    """A sensor for a single CAKE QoS metric."""

    _attr_has_entity_name = True
    entity_description: CakeQosSensorDescription

    def __init__(
        self,
        coordinator: CakeQosCoordinator,
        description: CakeQosSensorDescription,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        host = self.coordinator.config_entry.data.get("host", "")
        port = self.coordinator.config_entry.data.get("port", 9101)
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name="CAKE QoS",
            manufacturer="cake-autorate",
            model="cake-stats-exporter",
            configuration_url=f"http://{host}:{port}/stats",
        )

    @property
    def native_value(self) -> float | str | None:
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
