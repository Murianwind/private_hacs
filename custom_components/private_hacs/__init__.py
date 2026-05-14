"""Private HACS — manage private GitHub repositories like HACS."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_GITHUB_TOKEN, CONF_REPOS, DOMAIN
from .coordinator import PrivateHacsCoordinator
from .github import GitHubClient
from .panel import async_remove_panel, async_setup_panel
from .services import async_register_services, async_unregister_services
from .store import RepositoryStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["update"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Private HACS from a config entry."""
    token: str | None = entry.data.get(CONF_GITHUB_TOKEN)
    repos: list[dict] = entry.data.get(CONF_REPOS, [])

    # [수정] Home Assistant의 aiohttp 세션을 가져와 GitHubClient에 전달합니다.
    session = async_get_clientsession(hass)
    github = GitHubClient(token, session)
    
    store = RepositoryStore(hass)
    await store.async_load()

    coordinator = PrivateHacsCoordinator(hass, repos, github, store)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "github": github,
        "store": store,
    }

    # Platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Services (register once; guarded internally)
    async_register_services(hass)

    # Sidebar panel
    await async_setup_panel(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    # If no more entries, remove services + panel
    if not hass.data.get(DOMAIN):
        async_unregister_services(hass)
        await async_remove_panel(hass)

    return unload_ok
