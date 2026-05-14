"""Service handlers for Private HACS."""
from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import CONF_GITHUB_TOKEN, CONF_REPOS, DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_INSTALL = "install"
SERVICE_UNINSTALL = "uninstall"
SERVICE_REFRESH = "refresh"
SERVICE_ADD_REPO = "add_repo"
SERVICE_REMOVE_REPO = "remove_repo"
SERVICE_GET_REPO_INFO = "get_repo_info"
# 요구사항 3 구현을 위해 추가된 서비스 상수
SERVICE_GET_README = "get_readme"

SCHEMA_COMPONENT = vol.Schema({vol.Required("component_id"): cv.string})
SCHEMA_EMPTY = vol.Schema({})
SCHEMA_ADD_REPO = vol.Schema(
    {
        vol.Required("repo"): cv.string,
        vol.Required("name"): cv.string,
        vol.Required("component_id"): cv.string,
        vol.Optional("branch", default="main"): cv.string,
    }
)
SCHEMA_REMOVE_REPO = vol.Schema({vol.Required("component_id"): cv.string})
SCHEMA_GET_REPO_INFO = vol.Schema({vol.Required("repo"): cv.string})
# README 조회를 위한 스키마
SCHEMA_GET_README = vol.Schema({
    vol.Required("repo"): cv.string,
    vol.Optional("branch", default="main"): cv.string,
})


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

    # README 조회를 위한 서비스 핸들러 등록
    async def handle_get_readme(call: ServiceCall) -> ServiceResponse:
        return await _do_get_readme(hass, call.data["repo"], call.data.get("branch", "main"))

    _register_once(hass, SERVICE_INSTALL, handle_install, SCHEMA_COMPONENT)
    _register_once(hass, SERVICE_UNINSTALL, handle_uninstall, SCHEMA_COMPONENT)
    _register_once(hass, SERVICE_REFRESH, handle_refresh, SCHEMA_EMPTY)
    _register_once(hass, SERVICE_ADD_REPO, handle_add_repo, SCHEMA_ADD_REPO)
    _register_once(hass, SERVICE_REMOVE_REPO, handle_remove_repo, SCHEMA_REMOVE_REPO)
    _register_once(
        hass, SERVICE_GET_REPO_INFO, handle_get_repo_info, SCHEMA_GET_REPO_INFO,
        supports_response=SupportsResponse.ONLY,
    )
    # README 서비스 등록 (응답 전용)
    _register_once(
        hass, SERVICE_GET_README, handle_get_readme, SCHEMA_GET_README,
        supports_response=SupportsResponse.ONLY,
    )


def _register_once(hass, service, handler, schema, supports_response=SupportsResponse.NONE) -> None:
    if not hass.services.has_service(DOMAIN, service):
        hass.services.async_register(
            DOMAIN, service, handler, schema=schema,
            supports_response=supports_response,
        )


def async_unregister_services(hass: HomeAssistant) -> None:
    for svc in (
        SERVICE_INSTALL, SERVICE_UNINSTALL, SERVICE_REFRESH,
        SERVICE_ADD_REPO, SERVICE_REMOVE_REPO, SERVICE_GET_REPO_INFO,
        SERVICE_GET_README,
    ):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)


def _get_entry(hass: HomeAssistant) -> ConfigEntry | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


def _get_entry_data(hass: HomeAssistant) -> dict | None:
    domain_data = hass.data.get(DOMAIN, {})
    for entry_data in domain_data.values():
        return entry_data
    return None


async def _do_install(hass: HomeAssistant, component_id: str) -> None:
    ed = _get_entry_data(hass)
    if ed is None:
        raise HomeAssistantError("Private HACS가 로드되지 않았습니다.")

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
    _LOGGER.info("Installing %s (%s @ %s)", component_id, repo, ref)

    try:
        await github.download_and_install(hass, repo, component_id, ref)
    except Exception as exc:
        raise HomeAssistantError(f"설치 실패: {exc}") from exc

    await store.async_set(component_id, {"installed_version": latest["version"]})
    await coordinator.async_request_refresh()


async def _do_uninstall(hass: HomeAssistant, component_id: str) -> None:
    """컴포넌트 삭제 로직 (요구사항 4 반영)"""
    ed = _get_entry_data(hass)
    if ed is None:
        raise HomeAssistantError("Private HACS가 로드되지 않았습니다.")

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

    current_repos.append({
        "repo": repo,
        "name": name,
        "component_id": component_id,
        "branch": branch,
    })

    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_REPOS: current_repos},
    )

    ed = _get_entry_data(hass)
    if ed:
        ed["coordinator"].repos = current_repos
        await ed["coordinator"].async_request_refresh()

    _LOGGER.info("Repo added: %s (%s)", name, repo)


async def _do_remove_repo(hass: HomeAssistant, component_id: str) -> None:
    """등록 해제 로직 (요구사항 4 반영)"""
    entry = _get_entry(hass)
    if entry is None:
        raise HomeAssistantError("Private HACS config entry를 찾을 수 없습니다.")

    current_repos: list[dict] = list(entry.data.get(CONF_REPOS, []))
    new_repos = [r for r in current_repos if r["component_id"] != component_id]

    if len(new_repos) == len(current_repos):
        raise HomeAssistantError(f"'{component_id}'는 등록된 저장소가 아닙니다.")

    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_REPOS: new_repos},
    )

    ed = _get_entry_data(hass)
    if ed:
        coordinator = ed["coordinator"]
        coordinator.repos = new_repos
        if coordinator.data and component_id in coordinator.data:
            del coordinator.data[component_id]
        coordinator.async_update_listeners()

    _LOGGER.info("Repo removed: %s", component_id)


async def _do_get_repo_info(hass: HomeAssistant, repo: str) -> ServiceResponse:
    ed = _get_entry_data(hass)
    if ed is None:
        raise HomeAssistantError("Private HACS가 로드되지 않았습니다.")

    github = ed["github"]

    try:
        repo_info = await github.get_repo_info(repo)
    except Exception as exc:
        raise HomeAssistantError(f"저장소 조회 실패: {exc}") from exc

    if repo_info is None:
        raise HomeAssistantError(f"저장소 '{repo}'를 찾을 수 없습니다.")

    component_ids: list[str] = []
    try:
        contents = await github.get_contents(repo, "custom_components")
        if contents:
            component_ids = [f["name"] for f in contents if f.get("type") == "dir"]
    except Exception:
        pass

    return {
        "name": repo_info.get("name", repo.split("/")[1]),
        "description": repo_info.get("description") or "",
        "default_branch": repo_info.get("default_branch", "main"),
        "full_name": repo_info.get("full_name", repo),
        "component_ids": component_ids,
    }

# 요구사항 3을 처리하는 백엔드 함수
async def _do_get_readme(hass: HomeAssistant, repo: str, branch: str) -> ServiceResponse:
    """저장소의 README 내용을 가져와 반환합니다."""
    ed = _get_entry_data(hass)
    if ed is None:
        raise HomeAssistantError("Private HACS가 로드되지 않았습니다.")

    github = ed["github"]
    try:
        content = await github.get_readme(repo, branch)
        return {"content": content or "README 내용을 찾을 수 없습니다."}
    except Exception as exc:
        _LOGGER.error("README fetch error: %s", exc)
        return {"content": f"README 로드 중 오류 발생: {exc}"}
