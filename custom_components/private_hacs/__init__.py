"""Private HACS — manage private GitHub repositories like HACS."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

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

    github = GitHubClient(token)
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

    # 수정됨: 저장소를 추가/제거할 때마다 전체 컴포넌트가 재시작되어 패널이 닫히는 현상을 
    # 막기 위해 _async_reload_listener 관련 코드를 삭제했습니다.
    # services.py에서 이미 in-memory(coordinator) 업데이트를 처리하므로 리로드가 필요 없습니다.

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
