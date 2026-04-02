"""Button platform for CAKE QoS — restart autorate."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
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
    """Set up CAKE QoS buttons."""
    coordinator: CakeQosCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CakeAutorateRestartButton(coordinator, entry)])


class CakeAutorateRestartButton(CoordinatorEntity[CakeQosCoordinator], ButtonEntity):
    """Button to restart cake-autorate service."""

    _attr_has_entity_name = True
    _attr_name = "Restart autorate"
    _attr_icon = "mdi:restart"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: CakeQosCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_autorate_restart"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
        )

    async def async_press(self) -> None:
        """Restart cake-autorate."""
        await self.coordinator.client.autorate_restart()
        await self.coordinator.async_request_refresh()
