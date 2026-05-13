"""Update platform for Private HACS."""
from __future__ import annotations

import logging

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
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
    coordinator: PrivateHacsCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    repos: list[dict] = entry.data.get(CONF_REPOS, [])

    async_add_entities(
        PrivateHacsUpdateEntity(coordinator, entry, repo)
        for repo in repos
    )


class PrivateHacsUpdateEntity(CoordinatorEntity[PrivateHacsCoordinator], UpdateEntity):
    """One update entity per tracked private repository."""

    _attr_has_entity_name = True
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

        self._attr_unique_id = f"{DOMAIN}_{self._component_id}"
        self._attr_name = f"{repo_cfg['name']} update"
        self._attr_title = repo_cfg["name"]

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Private HACS",
            manufacturer="private-hacs",
            model="Private Repository Manager",
            entry_type="service",  # type: ignore[arg-type]
        )

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
        return self._latest.get("version")

    @property
    def release_url(self) -> str | None:
        return self._latest.get("release_url")

    @property
    def release_summary(self) -> str | None:
        return self._latest.get("release_summary")

    @property
    def in_progress(self) -> bool:
        return False

    @property
    def update_percentage(self) -> int | None:
        return None

    async def async_release_notes(self) -> str | None:
        return self.release_summary

    async def async_install(self, version: str | None, backup: bool, **kwargs) -> None:
        """Trigger install via the integration's service."""
        hass = self.hass
        await hass.services.async_call(
            DOMAIN,
            "install",
            {"component_id": self._component_id},
            blocking=True,
        )
