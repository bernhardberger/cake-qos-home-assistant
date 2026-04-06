"""The CAKE QoS integration.

Provides control entities (switch, number, button) for managing
cake-autorate and static CAKE shaper rates.  Monitoring sensors
are handled separately by cake-autorate's built-in MQTT publisher
with Home Assistant auto-discovery.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CakeClient
from .const import CONF_HOST, CONF_PORT, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import CakeQosCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "number", "button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CAKE QoS from a config entry."""
    session = async_get_clientsession(hass)
    client = CakeClient(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        session=session,
    )

    coordinator = CakeQosCoordinator(hass, client, DEFAULT_SCAN_INTERVAL)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
