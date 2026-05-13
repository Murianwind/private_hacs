"""Service handlers for Private HACS."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_INSTALL = "install"
SERVICE_UNINSTALL = "uninstall"
SERVICE_REFRESH = "refresh"

SCHEMA_COMPONENT = vol.Schema({vol.Required("component_id"): cv.string})
SCHEMA_EMPTY = vol.Schema({})


def async_register_services(hass: HomeAssistant) -> None:
    """Register all Private HACS services."""

    async def handle_install(call: ServiceCall) -> None:
        component_id: str = call.data["component_id"]
        await _do_install(hass, component_id)

    async def handle_uninstall(call: ServiceCall) -> None:
        component_id: str = call.data["component_id"]
        await _do_uninstall(hass, component_id)

    async def handle_refresh(call: ServiceCall) -> None:
        await _do_refresh(hass)

    hass.services.async_register(
        DOMAIN, SERVICE_INSTALL, handle_install, schema=SCHEMA_COMPONENT
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UNINSTALL, handle_uninstall, schema=SCHEMA_COMPONENT
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, handle_refresh, schema=SCHEMA_EMPTY
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    hass.services.async_remove(DOMAIN, SERVICE_INSTALL)
    hass.services.async_remove(DOMAIN, SERVICE_UNINSTALL)
    hass.services.async_remove(DOMAIN, SERVICE_REFRESH)


# ---------------------------------------------------------------------------
# Actual logic
# ---------------------------------------------------------------------------

async def _do_install(hass: HomeAssistant, component_id: str) -> None:
    domain_data = hass.data.get(DOMAIN, {})
    # Find the entry that has this component
    for entry_id, entry_data in domain_data.items():
        coordinator = entry_data.get("coordinator")
        github = entry_data.get("github")
        store = entry_data.get("store")

        if coordinator is None or coordinator.data is None:
            continue

        repo_data = coordinator.data.get(component_id)
        if repo_data is None:
            continue

        latest = repo_data.get("latest")
        if latest is None:
            raise HomeAssistantError(
                f"No version info available for {component_id}. Try refreshing."
            )

        repo: str = repo_data["repo"]
        ref: str = latest["download_ref"]

        _LOGGER.info("Installing %s (%s @ %s)", component_id, repo, ref)

        try:
            await github.download_and_install(hass, repo, component_id, ref)
        except Exception as exc:
            raise HomeAssistantError(f"Install failed: {exc}") from exc

        await store.async_set(
            component_id,
            {"installed_version": latest["version"]},
        )

        # Refresh coordinator so update entity state updates immediately
        await coordinator.async_request_refresh()
        return

    raise HomeAssistantError(
        f"Component '{component_id}' not found in Private HACS configuration."
    )


async def _do_uninstall(hass: HomeAssistant, component_id: str) -> None:
    domain_data = hass.data.get(DOMAIN, {})

    for entry_id, entry_data in domain_data.items():
        coordinator = entry_data.get("coordinator")
        github = entry_data.get("github")
        store = entry_data.get("store")

        if coordinator is None or coordinator.data is None:
            continue

        if component_id not in coordinator.data:
            continue

        try:
            await github.uninstall(hass, component_id)
        except Exception as exc:
            raise HomeAssistantError(f"Uninstall failed: {exc}") from exc

        await store.async_remove(component_id)
        await coordinator.async_request_refresh()
        return

    raise HomeAssistantError(
        f"Component '{component_id}' not found in Private HACS configuration."
    )


async def _do_refresh(hass: HomeAssistant) -> None:
    domain_data = hass.data.get(DOMAIN, {})
    for entry_data in domain_data.values():
        coordinator = entry_data.get("coordinator")
        if coordinator:
            await coordinator.async_request_refresh()
