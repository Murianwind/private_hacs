"""Private HACS — manage private GitHub repositories like HACS."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
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
    token: str | None = entry.data.get(CONF_GITHUB_TOKEN)
    repos: list[dict] = entry.data.get(CONF_REPOS, [])

    session = async_get_clientsession(hass)
    github = GitHubClient(token=token, session=session)

    store = RepositoryStore(hass)
    await store.async_load()

    coordinator = PrivateHacsCoordinator(hass, repos, github, store)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "github": github,
        "store": store,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_services(hass)
    await async_setup_panel(hass)

    # 레거시 unique_id 형식 엔티티 정리
    # 구형: repo_{component_id} (branch 없음)
    # 신형: repo_{component_id}_{branch}
    _async_cleanup_legacy_entities(hass, entry, repos)

    return True


def _async_cleanup_legacy_entities(
    hass: HomeAssistant, entry: ConfigEntry, repos: list[dict]
) -> None:
    """
    구형 unique_id(repo_{component_id}) 형식의 엔티티를 entity registry에서 제거.
    신형(repo_{component_id}_{branch})과 중복되어 패널에 정체불명 항목으로 표시되는 문제 방지.
    """
    ent_reg = er.async_get(hass)
    valid_uids: set[str] = set()

    for repo in repos:
        cid = repo["component_id"]
        branch = repo.get("branch", "main")
        valid_uids.add(f"repo_{cid}_{branch}")

    # update 플랫폼에서 private_hacs가 소유한 모든 엔티티 순회
    stale = [
        entity for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
        if entity.domain == "update"
        and entity.unique_id not in valid_uids
    ]

    for entity in stale:
        _LOGGER.info(
            "Removing legacy/stale entity %s (unique_id=%s)",
            entity.entity_id, entity.unique_id,
        )
        ent_reg.async_remove(entity.entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    if not hass.data.get(DOMAIN):
        async_unregister_services(hass)
        await async_remove_panel(hass)

    return unload_ok
