"""Persistent storage for Private HACS repository states."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


class RepositoryStore:
    """Persists installed_version and other mutable repo state across restarts."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, dict] = {}

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if stored:
            self._data = stored

    async def async_save(self) -> None:
        await self._store.async_save(self._data)

    def get(self, component_id: str) -> dict:
        return self._data.get(component_id, {})

    async def async_set(self, component_id: str, data: dict) -> None:
        self._data[component_id] = {**self._data.get(component_id, {}), **data}
        await self.async_save()

    async def async_remove(self, component_id: str) -> None:
        self._data.pop(component_id, None)
        await self.async_save()

    def installed_version(self, component_id: str) -> str | None:
        return self._data.get(component_id, {}).get("installed_version")

    def all(self) -> dict[str, dict]:
        return dict(self._data)
