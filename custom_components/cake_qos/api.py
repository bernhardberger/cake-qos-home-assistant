"""API client for the CAKE QoS stats exporter."""

from __future__ import annotations

import aiohttp


class CakeApiError(Exception):
    """Generic API error."""


class CakeConnectionError(CakeApiError):
    """Cannot reach the exporter."""


class CakeClient:
    """Async HTTP client for the cake-stats-exporter."""

    def __init__(self, host: str, port: int, session: aiohttp.ClientSession) -> None:
        self._base = f"http://{host}:{port}"
        self._session = session

    async def get_stats(self) -> dict:
        """GET /stats — full CAKE + autorate + service state."""
        return await self._get("/stats")

    async def get_config(self) -> dict:
        """GET /config — current autorate tunables."""
        return await self._get("/config")

    async def autorate_start(self) -> dict:
        """POST /autorate/start."""
        return await self._post("/autorate/start")

    async def autorate_stop(self) -> dict:
        """POST /autorate/stop."""
        return await self._post("/autorate/stop")

    async def autorate_restart(self) -> dict:
        """POST /autorate/restart."""
        return await self._post("/autorate/restart")

    async def update_config(self, changes: dict) -> dict:
        """POST /config — update autorate tunables."""
        return await self._post("/config", json=changes)

    async def set_static_rates(self, dl_rate_mbit: float, ul_rate_mbit: float) -> dict:
        """POST /cake/rates — set static CAKE shaper rates."""
        return await self._post(
            "/cake/rates",
            json={"dl_rate_mbit": dl_rate_mbit, "ul_rate_mbit": ul_rate_mbit},
        )

    async def health_check(self) -> bool:
        """GET /health — returns True if exporter is reachable."""
        try:
            data = await self._get("/health")
            return data.get("status") == "ok"
        except CakeApiError:
            return False

    async def _get(self, path: str) -> dict:
        try:
            async with self._session.get(
                f"{self._base}{path}", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            raise CakeConnectionError(f"GET {path}: {err}") from err

    async def _post(self, path: str, json: dict | None = None) -> dict:
        try:
            async with self._session.post(
                f"{self._base}{path}",
                json=json,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            raise CakeConnectionError(f"POST {path}: {err}") from err
