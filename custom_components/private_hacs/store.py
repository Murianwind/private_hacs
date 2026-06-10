"""Persistent storage for Private HACS repository states."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


class RepositoryStore:
    """
    Persists installed_version and other mutable repo state.

    Internal layout:
        {
          "<component_id>": {
            "<branch>": {
              "installed_version": "...",
              "installed_commit_sha": "...",
            },
            ...
          },
          ...
        }

    Legacy flat layout (component_id → {installed_version, ...}) is
    migrated automatically on first load.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, dict] = {}

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if stored:
            self._data = self._migrate(stored)

    @staticmethod
    def _migrate(data: dict) -> dict:
        """Migrate legacy flat {component_id: {installed_version}} to nested layout."""
        migrated: dict = {}
        for key, val in data.items():
            if not isinstance(val, dict):
                continue
            # New layout: nested dict has branch keys (strings) as sub-dicts
            # Legacy layout: has keys like "installed_version", "installed_commit_sha"
            if any(k in val for k in ("installed_version", "installed_commit_sha")):
                # Legacy — wrap under "main"
                migrated[key] = {"main": val}
                _LOGGER.info("Migrated legacy store entry '%s' to branch-aware layout", key)
            else:
                migrated[key] = val
        return migrated

    async def async_save(self) -> None:
        await self._store.async_save(self._data)

    # ------------------------------------------------------------------
    # Branch-aware accessors
    # ------------------------------------------------------------------

    def get_branch(self, component_id: str, branch: str) -> dict:
        return self._data.get(component_id, {}).get(branch, {})

    async def async_set_branch(
        self, component_id: str, branch: str, data: dict
    ) -> None:
        self._data.setdefault(component_id, {}).setdefault(branch, {})
        self._data[component_id][branch].update(data)
        await self.async_save()

    async def async_remove_branch(self, component_id: str, branch: str) -> None:
        comp = self._data.get(component_id, {})
        comp.pop(branch, None)
        if not comp:
            self._data.pop(component_id, None)
        await self.async_save()

    async def async_remove(self, component_id: str) -> None:
        self._data.pop(component_id, None)
        await self.async_save()

    def installed_version(self, component_id: str, branch: str) -> str | None:
        return self.get_branch(component_id, branch).get("installed_version")

    # Legacy compatibility (used by coordinator for initial load)
    def get(self, component_id: str) -> dict:
        """Return merged data for all branches (legacy compat)."""
        return self._data.get(component_id, {})

    def all(self) -> dict[str, dict]:
        return dict(self._data)
