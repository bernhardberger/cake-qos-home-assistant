"""DataUpdateCoordinator for CAKE QoS."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CakeApiError, CakeClient

_LOGGER = logging.getLogger(__name__)


class CakeQosCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch stats from the cake-stats-exporter."""

    def __init__(
        self, hass: HomeAssistant, client: CakeClient, scan_interval: int
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="CAKE QoS",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            stats = await self.client.get_stats()
            config = await self.client.get_config()
            stats["config"] = config
            return stats
        except CakeApiError as err:
            raise UpdateFailed(f"Failed to fetch CAKE stats: {err}") from err
