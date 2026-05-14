"""Update platform for Private HACS."""
from __future__ import annotations

import logging
import os

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_REPOS, DOMAIN
from .coordinator import PrivateHacsCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    ed = hass.data[DOMAIN][entry.entry_id]
    coordinator: PrivateHacsCoordinator = ed["coordinator"]

    # Store references so services.py can dynamically add/remove entities
    ed["async_add_entities"] = async_add_entities
    ed.setdefault("update_entities", {})

    repos: list[dict] = entry.data.get(CONF_REPOS, [])
    async_add_entities(
        PrivateHacsUpdateEntity(coordinator, entry, repo) for repo in repos
    )


class PrivateHacsUpdateEntity(CoordinatorEntity[PrivateHacsCoordinator], UpdateEntity):
    """One update entity per tracked private repository."""

    # Use component name directly — no device name prefix
    _attr_has_entity_name = False
    _attr_auto_update = False
    _attr_supported_features = (
        UpdateEntityFeature.RELEASE_NOTES
        | UpdateEntityFeature.SPECIFIC_VERSION
        | UpdateEntityFeature.PROGRESS
    )

    def __init__(
        self,
        coordinator: PrivateHacsCoordinator,
        entry: ConfigEntry,
        repo_cfg: dict,
    ) -> None:
        super().__init__(coordinator)
        self._component_id: str = repo_cfg["component_id"]
        self._entry_id = entry.entry_id

        self.entity_id = f"update.{self._component_id}_update"
        self._attr_unique_id = f"repo_{self._component_id}"
        self._attr_name = repo_cfg["name"]
        self._attr_title = repo_cfg["name"]

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Private HACS",
            manufacturer="private-hacs",
            model="Private Repository Manager",
            entry_type=DeviceEntryType.SERVICE,
        )

        # Register entity reference for dynamic removal
        coordinator.hass.data[DOMAIN][self._entry_id]["update_entities"][
            self._component_id
        ] = self

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        entities = (
            self.hass.data.get(DOMAIN, {})
            .get(self._entry_id, {})
            .get("update_entities", {})
        )
        entities.pop(self._component_id, None)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def _repo_data(self) -> dict:
        if self.coordinator.data is None:
            return {}
        return self.coordinator.data.get(self._component_id) or {}

    @property
    def _latest(self) -> dict:
        return self._repo_data.get("latest") or {}

    @property
    def installed_version(self) -> str | None:
        return self._repo_data.get("installed_version")

    @property
    def latest_version(self) -> str | None:
        """
        Return the latest version string.
        When no update is available, return installed_version so HA
        displays the entity as up-to-date rather than showing a mismatch.
        """
        if not self._repo_data.get("has_update", False):
            return self._repo_data.get("installed_version")
        return self._latest.get("version")

    @property
    def release_url(self) -> str | None:
        """Release page for releases/tags, commit log for branch-tracked repos."""
        url = self._latest.get("release_url")
        if url:
            return url
        repo = self._repo_data.get("repo")
        branch = self._repo_data.get("branch", "main")
        if repo:
            return f"https://github.com/{repo}/commits/{branch}"
        return None

    @property
    def release_summary(self) -> str | None:
        return self._latest.get("release_summary")

    @property
    def in_progress(self) -> bool:
        return False

    @property
    def update_percentage(self) -> int | None:
        return None

    @property
    def extra_state_attributes(self) -> dict:
        latest = self._latest
        icon_path = self.hass.config.path(
            "custom_components", self._component_id, "brand", "icon.png"
        )
        # os.path.exists is blocking — acceptable here since it's
        # called on attribute read, not in a tight loop.
        has_icon = os.path.exists(icon_path)
        return {
            "version_source": self._repo_data.get("version_source", "none"),
            "latest_type": latest.get("type"),
            "remote_commit_sha": latest.get("commit_sha"),
            "installed_commit_sha": self._repo_data.get("installed_commit_sha"),
            "has_icon": has_icon,
        }

    async def async_release_notes(self) -> str | None:
        return self.release_summary

    async def async_install(self, version: str | None, backup: bool, **kwargs) -> None:
        await self.hass.services.async_call(
            DOMAIN,
            "install",
            {"component_id": self._component_id},
            blocking=True,
        )
