"""Switch platform for CAKE QoS — autorate on/off."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CakeQosCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up CAKE QoS switches."""
    coordinator: CakeQosCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CakeAutorateSwitch(coordinator, entry)])


class CakeAutorateSwitch(CoordinatorEntity[CakeQosCoordinator], SwitchEntity):
    """Switch to start/stop cake-autorate service."""

    _attr_has_entity_name = True
    _attr_name = "Autorate"
    _attr_icon = "mdi:tune-vertical"

    def __init__(
        self,
        coordinator: CakeQosCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_autorate_switch"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
        )

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        state = self.coordinator.data.get("service", {}).get("active")
        return state == "active"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start cake-autorate."""
        await self.coordinator.client.autorate_start()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop cake-autorate."""
        await self.coordinator.client.autorate_stop()
        await self.coordinator.async_request_refresh()
