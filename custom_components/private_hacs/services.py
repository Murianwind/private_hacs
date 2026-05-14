"""Service handlers for Private HACS."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import CONF_REPOS, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Service names
_INSTALL = "install"
_UNINSTALL = "uninstall"
_REFRESH = "refresh"
_ADD_REPO = "add_repo"
_REMOVE_REPO = "remove_repo"
_GET_REPO_INFO = "get_repo_info"
_GET_README = "get_readme"

_SCHEMA_COMPONENT = vol.Schema({vol.Required("component_id"): cv.string})
_SCHEMA_EMPTY = vol.Schema({})
_SCHEMA_ADD_REPO = vol.Schema(
    {
        vol.Required("repo"): cv.string,
        vol.Required("name"): cv.string,
        vol.Required("component_id"): cv.string,
        vol.Optional("branch", default="main"): cv.string,
    }
)
_SCHEMA_REMOVE_REPO = vol.Schema({vol.Required("component_id"): cv.string})
_SCHEMA_GET_REPO_INFO = vol.Schema({vol.Required("repo"): cv.string})
_SCHEMA_GET_README = vol.Schema(
    {
        vol.Required("repo"): cv.string,
        vol.Optional("branch", default="main"): cv.string,
    }
)


def async_register_services(hass: HomeAssistant) -> None:
    """Register all Private HACS services (idempotent)."""

    async def handle_install(call: ServiceCall) -> None:
        await _do_install(hass, call.data["component_id"])

    async def handle_uninstall(call: ServiceCall) -> None:
        await _do_uninstall(hass, call.data["component_id"])

    async def handle_refresh(call: ServiceCall) -> None:
        await _do_refresh(hass)

    async def handle_add_repo(call: ServiceCall) -> None:
        await _do_add_repo(
            hass,
            repo=call.data["repo"],
            name=call.data["name"],
            component_id=call.data["component_id"],
            branch=call.data.get("branch", "main"),
        )

    async def handle_remove_repo(call: ServiceCall) -> None:
        await _do_remove_repo(hass, call.data["component_id"])

    async def handle_get_repo_info(call: ServiceCall) -> ServiceResponse:
        return await _do_get_repo_info(hass, call.data["repo"])

    async def handle_get_readme(call: ServiceCall) -> ServiceResponse:
        return await _do_get_readme(hass, call.data["repo"], call.data.get("branch", "main"))

    _register_once(hass, _INSTALL, handle_install, _SCHEMA_COMPONENT)
    _register_once(hass, _UNINSTALL, handle_uninstall, _SCHEMA_COMPONENT)
    _register_once(hass, _REFRESH, handle_refresh, _SCHEMA_EMPTY)
    _register_once(hass, _ADD_REPO, handle_add_repo, _SCHEMA_ADD_REPO)
    _register_once(hass, _REMOVE_REPO, handle_remove_repo, _SCHEMA_REMOVE_REPO)
    _register_once(
        hass, _GET_REPO_INFO, handle_get_repo_info, _SCHEMA_GET_REPO_INFO,
        supports_response=SupportsResponse.ONLY,
    )
    _register_once(
        hass, _GET_README, handle_get_readme, _SCHEMA_GET_README,
        supports_response=SupportsResponse.ONLY,
    )


def _register_once(
    hass: HomeAssistant,
    service: str,
    handler,
    schema,
    supports_response: SupportsResponse = SupportsResponse.NONE,
) -> None:
    if not hass.services.has_service(DOMAIN, service):
        hass.services.async_register(
            DOMAIN, service, handler,
            schema=schema, supports_response=supports_response,
        )


def async_unregister_services(hass: HomeAssistant) -> None:
    for svc in (_INSTALL, _UNINSTALL, _REFRESH, _ADD_REPO, _REMOVE_REPO, _GET_REPO_INFO, _GET_README):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_entry(hass: HomeAssistant) -> ConfigEntry | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


def _get_entry_data(hass: HomeAssistant) -> dict | None:
    """Return runtime data for the (single) config entry, or None."""
    for entry_data in hass.data.get(DOMAIN, {}).values():
        return entry_data
    return None


def _require_entry_data(hass: HomeAssistant) -> dict:
    ed = _get_entry_data(hass)
    if ed is None:
        raise HomeAssistantError("Private HACS가 로드되지 않았습니다.")
    return ed


# ------------------------------------------------------------------
# Service implementations
# ------------------------------------------------------------------

async def _do_install(hass: HomeAssistant, component_id: str) -> None:
    ed = _require_entry_data(hass)
    coordinator = ed["coordinator"]
    github = ed["github"]
    store = ed["store"]

    if coordinator.data is None or component_id not in coordinator.data:
        raise HomeAssistantError(
            f"'{component_id}'를 찾을 수 없습니다. 먼저 저장소를 등록하세요."
        )

    repo_data = coordinator.data[component_id]
    latest = repo_data.get("latest")
    if latest is None:
        raise HomeAssistantError(
            f"'{component_id}' 버전 정보가 없습니다. 새로고침 후 다시 시도하세요."
        )

    repo: str = repo_data["repo"]
    ref: str = latest["download_ref"]
    _LOGGER.info("Installing %s from %s @ %s", component_id, repo, ref)

    try:
        await github.download_and_install(hass, repo, component_id, ref)
    except Exception as exc:
        raise HomeAssistantError(f"설치 실패: {exc}") from exc

    # Persist version and commit SHA so update detection works correctly
    store_data: dict = {"installed_version": latest["version"]}
    if latest.get("commit_sha"):
        store_data["installed_commit_sha"] = latest["commit_sha"]
    await store.async_set(component_id, store_data)

    await coordinator.async_request_refresh()


async def _do_uninstall(hass: HomeAssistant, component_id: str) -> None:
    ed = _require_entry_data(hass)
    coordinator = ed["coordinator"]
    github = ed["github"]
    store = ed["store"]

    if coordinator.data is None or component_id not in coordinator.data:
        raise HomeAssistantError(f"'{component_id}'를 찾을 수 없습니다.")

    try:
        await github.uninstall(hass, component_id)
    except Exception as exc:
        raise HomeAssistantError(f"삭제 실패: {exc}") from exc

    await store.async_remove(component_id)
    await coordinator.async_request_refresh()


async def _do_refresh(hass: HomeAssistant) -> None:
    ed = _get_entry_data(hass)
    if ed and ed.get("coordinator"):
        await ed["coordinator"].async_request_refresh()


async def _do_add_repo(
    hass: HomeAssistant,
    repo: str,
    name: str,
    component_id: str,
    branch: str,
) -> None:
    entry = _get_entry(hass)
    if entry is None:
        raise HomeAssistantError("Private HACS config entry를 찾을 수 없습니다.")

    current_repos: list[dict] = list(entry.data.get(CONF_REPOS, []))
    if any(r["component_id"] == component_id for r in current_repos):
        raise HomeAssistantError(f"'{component_id}'는 이미 등록된 저장소입니다.")

    new_repo_cfg = {"repo": repo, "name": name, "component_id": component_id, "branch": branch}
    current_repos.append(new_repo_cfg)

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_REPOS: current_repos}
    )

    ed = _get_entry_data(hass)
    if ed:
        coordinator = ed["coordinator"]
        coordinator.repos = current_repos

        # Dynamically add the update entity without requiring a restart
        if "async_add_entities" in ed:
            from .update import PrivateHacsUpdateEntity
            ed["async_add_entities"]([PrivateHacsUpdateEntity(coordinator, entry, new_repo_cfg)])

        await coordinator.async_request_refresh()

    _LOGGER.info("Repo registered: %s (%s)", name, repo)


async def _do_remove_repo(hass: HomeAssistant, component_id: str) -> None:
    """
    Remove a repo registration.
    Installed files and store data are intentionally kept so that
    re-registering the same repo restores the previous install state.
    """
    entry = _get_entry(hass)
    if entry is None:
        raise HomeAssistantError("Private HACS config entry를 찾을 수 없습니다.")

    current_repos: list[dict] = list(entry.data.get(CONF_REPOS, []))
    new_repos = [r for r in current_repos if r["component_id"] != component_id]

    if len(new_repos) == len(current_repos):
        raise HomeAssistantError(f"'{component_id}'는 등록된 저장소가 아닙니다.")

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_REPOS: new_repos}
    )

    ed = _get_entry_data(hass)
    if ed:
        coordinator = ed["coordinator"]
        coordinator.repos = new_repos

        # Remove coordinator data for this component
        if coordinator.data:
            coordinator.data.pop(component_id, None)
        coordinator.async_update_listeners()

        # Gracefully remove the live entity
        entity = ed.get("update_entities", {}).get(component_id)
        if entity:
            await entity.async_remove(force_remove=True)

    # Clean up entity registry entries (both old and new unique_id formats)
    ent_reg = er.async_get(hass)
    for uid in (f"repo_{component_id}", f"{DOMAIN}_{component_id}"):
        entity_id = ent_reg.async_get_entity_id("update", DOMAIN, uid)
        if entity_id:
            ent_reg.async_remove(entity_id)

    # NOTE: store data is NOT removed here — preserved for re-registration
    _LOGGER.info("Repo unregistered (files and store data kept): %s", component_id)


async def _do_get_repo_info(hass: HomeAssistant, repo: str) -> ServiceResponse:
    ed = _require_entry_data(hass)
    github = ed["github"]

    try:
        repo_info = await github.get_repo_info(repo)
    except Exception as exc:
        raise HomeAssistantError(f"저장소 조회 실패: {exc}") from exc

    if repo_info is None:
        raise HomeAssistantError(
            f"저장소 '{repo}'를 찾을 수 없습니다. "
            "주소가 올바른지, Private 저장소라면 토큰이 설정됐는지 확인하세요."
        )

    component_ids: list[str] = []
    try:
        contents = await github.get_contents(repo, "custom_components")
        if isinstance(contents, list):
            component_ids = [f["name"] for f in contents if f.get("type") == "dir"]
    except Exception as err:
        _LOGGER.debug("Could not list custom_components for %s: %s", repo, err)

    return {
        "name": repo_info.get("name", repo.split("/")[1]),
        "description": repo_info.get("description") or "",
        "default_branch": repo_info.get("default_branch", "main"),
        "full_name": repo_info.get("full_name", repo),
        "component_ids": component_ids,
    }


async def _do_get_readme(
    hass: HomeAssistant, repo: str, branch: str
) -> ServiceResponse:
    ed = _require_entry_data(hass)
    github = ed["github"]
    try:
        content = await github.get_readme(repo, branch)
        return {"content": content or "README 내용을 찾을 수 없습니다."}
    except Exception as exc:
        _LOGGER.error("Failed to fetch README for %s: %s", repo, exc)
        return {"content": f"README 로드 중 오류 발생: {exc}"}
