"""Config flow for CAKE QoS integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .api import CakeClient
from .const import CONF_HOST, CONF_PORT, DEFAULT_HOST, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
})


class CakeQosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for CAKE QoS exporter."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — enter host and port."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            # Validate connectivity
            try:
                session = aiohttp.ClientSession()
                try:
                    client = CakeClient(host=host, port=port, session=session)
                    ok = await client.health_check()
                    if not ok:
                        errors["base"] = "cannot_connect"
                finally:
                    await session.close()
            except Exception:
                _LOGGER.exception("Unexpected error connecting to CAKE exporter")
                errors["base"] = "cannot_connect"

            if not errors:
                return self.async_create_entry(
                    title=f"CAKE QoS ({host})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )
