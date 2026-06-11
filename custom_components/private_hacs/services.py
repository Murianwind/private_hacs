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
from .coordinator import make_entry_key
from .helpers import normalize_repo_config

_LOGGER = logging.getLogger(__name__)

_INSTALL       = "install"
_UNINSTALL     = "uninstall"
_REFRESH       = "refresh"
_ADD_REPO      = "add_repo"
_REMOVE_REPO   = "remove_repo"
_TOGGLE_BRANCH = "toggle_branch"
_SET_UPDATE_MODE = "set_update_mode"
_GET_REPO_INFO = "get_repo_info"
_GET_README    = "get_readme"
_GET_RELEASES  = "get_releases"

_SCHEMA_INSTALL = vol.Schema(
    {
        vol.Required("component_id"): cv.string,
        vol.Required("branch"): cv.string,
        vol.Optional("ref"): cv.string,
    }
)
_SCHEMA_UNINSTALL = vol.Schema(
    {
        vol.Required("component_id"): cv.string,
    }
)
_SCHEMA_EMPTY = vol.Schema({})
_SCHEMA_ADD_REPO = vol.Schema(
    {
        vol.Required("repo"): cv.string,
        vol.Required("name"): cv.string,
        vol.Required("component_id"): cv.string,
        vol.Optional("branch", default="main"): cv.string,
        vol.Optional("update_mode", default="release"): vol.In(["release", "commit"]),
    }
)
_SCHEMA_REMOVE_REPO = vol.Schema(
    {
        vol.Required("component_id"): cv.string,
        vol.Required("branch"): cv.string,
    }
)
_SCHEMA_TOGGLE_BRANCH = vol.Schema(
    {
        vol.Required("component_id"): cv.string,
        vol.Required("branch"): cv.string,
        vol.Required("active"): cv.boolean,
    }
)
_SCHEMA_SET_UPDATE_MODE = vol.Schema(
    {
        vol.Required("component_id"): cv.string,
        vol.Required("branch"): cv.string,
        vol.Required("update_mode"): vol.In(["release", "commit"]),
    }
)
_SCHEMA_GET_REPO_INFO = vol.Schema({vol.Required("repo"): cv.string})
_SCHEMA_GET_README    = vol.Schema(
    {
        vol.Required("repo"): cv.string,
        vol.Optional("branch", default="main"): cv.string,
    }
)
_SCHEMA_GET_RELEASES = vol.Schema(
    {
        vol.Required("component_id"): cv.string,
        vol.Required("branch"): cv.string,
    }
)


def async_register_services(hass: HomeAssistant) -> None:

    async def handle_install(call: ServiceCall) -> None:
        await _do_install(hass, call.data["component_id"], call.data["branch"], call.data.get("ref"))

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
            update_mode=call.data.get("update_mode", "release"),
        )

    async def handle_remove_repo(call: ServiceCall) -> None:
        await _do_remove_repo(hass, call.data["component_id"], call.data["branch"])

    async def handle_toggle_branch(call: ServiceCall) -> None:
        await _do_toggle_branch(
            hass, call.data["component_id"], call.data["branch"], call.data["active"]
        )

    async def handle_get_repo_info(call: ServiceCall) -> ServiceResponse:
        return await _do_get_repo_info(hass, call.data["repo"])

    async def handle_get_readme(call: ServiceCall) -> ServiceResponse:
        return await _do_get_readme(hass, call.data["repo"], call.data.get("branch", "main"))

    async def handle_get_releases(call: ServiceCall) -> ServiceResponse:
        return await _do_get_releases(hass, call.data["component_id"], call.data["branch"])

    async def handle_set_update_mode(call: ServiceCall) -> None:
        await _do_set_update_mode(
            hass, call.data["component_id"], call.data["branch"], call.data["update_mode"]
        )

    _register_once(hass, _INSTALL,         handle_install,         _SCHEMA_INSTALL)
    _register_once(hass, _UNINSTALL,       handle_uninstall,       _SCHEMA_UNINSTALL)
    _register_once(hass, _REFRESH,         handle_refresh,         _SCHEMA_EMPTY)
    _register_once(hass, _ADD_REPO,        handle_add_repo,        _SCHEMA_ADD_REPO)
    _register_once(hass, _REMOVE_REPO,     handle_remove_repo,     _SCHEMA_REMOVE_REPO)
    _register_once(hass, _TOGGLE_BRANCH,   handle_toggle_branch,   _SCHEMA_TOGGLE_BRANCH)
    _register_once(hass, _SET_UPDATE_MODE, handle_set_update_mode, _SCHEMA_SET_UPDATE_MODE)
    _register_once(hass, _GET_REPO_INFO, handle_get_repo_info, _SCHEMA_GET_REPO_INFO,
                   supports_response=SupportsResponse.ONLY)
    _register_once(hass, _GET_README,    handle_get_readme,    _SCHEMA_GET_README,
                   supports_response=SupportsResponse.ONLY)
    _register_once(hass, _GET_RELEASES,  handle_get_releases,  _SCHEMA_GET_RELEASES,
                   supports_response=SupportsResponse.ONLY)


def _register_once(hass, service, handler, schema, supports_response=SupportsResponse.NONE):
    if not hass.services.has_service(DOMAIN, service):
        hass.services.async_register(
            DOMAIN, service, handler,
            schema=schema, supports_response=supports_response,
        )


def async_unregister_services(hass: HomeAssistant) -> None:
    for svc in (
        _INSTALL, _UNINSTALL, _REFRESH, _ADD_REPO, _REMOVE_REPO,
        _TOGGLE_BRANCH, _SET_UPDATE_MODE, _GET_REPO_INFO, _GET_README, _GET_RELEASES,
    ):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_entry(hass: HomeAssistant) -> ConfigEntry | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


def _get_entry_data(hass: HomeAssistant) -> dict | None:
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

async def _do_install(
    hass: HomeAssistant, component_id: str, branch: str, ref: str | None = None
) -> None:
    ed = _require_entry_data(hass)
    coordinator = ed["coordinator"]
    github = ed["github"]
    store = ed["store"]

    entry_key = make_entry_key(component_id, branch)
    if coordinator.data is None or entry_key not in coordinator.data:
        raise HomeAssistantError(f"'{entry_key}'를 찾을 수 없습니다.")

    repo_data = coordinator.data[entry_key]
    latest = repo_data.get("latest")
    if latest is None:
        raise HomeAssistantError(f"'{entry_key}' 버전 정보가 없습니다. 새로고침 후 다시 시도하세요.")

    repo: str = repo_data["repo"]
    download_ref = ref if ref else latest["download_ref"]
    install_version = ref if ref else latest["version"]

    _LOGGER.info("Installing %s from %s @ %s", entry_key, repo, download_ref)

    try:
        await github.download_and_install(hass, repo, component_id, download_ref)
    except Exception as exc:
        raise HomeAssistantError(f"설치 실패: {exc}") from exc

    store_data: dict = {"installed_version": install_version}
    if ref:
        # 특정 태그/ref 지정 설치 — commit_sha 초기화
        store_data["installed_commit_sha"] = None
    else:
        # latest의 commit_sha 사용 (branch 타입일 때만 값이 있음)
        sha = latest.get("commit_sha")
        if sha:
            store_data["installed_commit_sha"] = sha
    await store.async_set_branch(component_id, branch, store_data)

    # 같은 component_id의 다른 브랜치 설치 기록 초기화
    # custom_components/{component_id}/ 는 하나뿐이므로
    # 다른 브랜치의 installed_version/sha를 남겨두면 UI에서 모두 설치됨으로 표시됨
    for other_branch in [
        r.get("branch", "main")
        for r in coordinator.repos
        if r["component_id"] == component_id and r.get("branch", "main") != branch
    ]:
        await store.async_set_branch(
            component_id, other_branch,
            {"installed_version": None, "installed_commit_sha": None}
        )

    await coordinator.async_request_refresh()


async def _do_uninstall(hass: HomeAssistant, component_id: str) -> None:
    """
    컴포넌트 파일을 삭제합니다.

    custom_components/{component_id}/ 디렉토리는 브랜치와 무관하게 하나이므로
    파일 삭제는 component_id 단위로 수행합니다.
    store의 설치 기록도 component_id 전체를 초기화합니다.
    저장소 등록(config entry의 repos)은 유지됩니다.
    """
    ed = _require_entry_data(hass)
    coordinator = ed["coordinator"]
    github = ed["github"]
    store = ed["store"]

    # component_id에 해당하는 entry_key가 하나라도 있는지 확인
    if coordinator.data is None or not any(
        d.get("component_id") == component_id for d in coordinator.data.values()
    ):
        raise HomeAssistantError(f"'{component_id}'를 찾을 수 없습니다.")

    try:
        await github.uninstall(hass, component_id)
    except Exception as exc:
        raise HomeAssistantError(f"삭제 실패: {exc}") from exc

    # 파일을 삭제했으므로 모든 브랜치의 설치 기록 초기화
    await store.async_remove(component_id)
    await coordinator.async_request_refresh()


async def _do_refresh(hass: HomeAssistant) -> None:
    ed = _get_entry_data(hass)
    if ed and ed.get("coordinator"):
        await ed["coordinator"].async_request_refresh()


async def _do_add_repo(
    hass: HomeAssistant, repo: str, name: str, component_id: str, branch: str,
    update_mode: str = "release",
) -> None:
    entry = _get_entry(hass)
    if entry is None:
        raise HomeAssistantError("Private HACS config entry를 찾을 수 없습니다.")

    # 저장소 존재 여부 사전 검증
    ed = _get_entry_data(hass)
    if ed:
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

    # active 필드 정규화
    current_repos: list[dict] = normalize_repo_config(list(entry.data.get(CONF_REPOS, [])))

    # 같은 component_id + branch 조합 중복 체크
    if any(r["component_id"] == component_id and r.get("branch", "main") == branch
           for r in current_repos):
        raise HomeAssistantError(
            f"'{component_id}' ({branch} 브랜치)는 이미 등록된 저장소입니다."
        )

    # 같은 component_id가 이미 있으면 새 브랜치는 비활성
    existing_same = [r for r in current_repos if r["component_id"] == component_id]
    new_active = len(existing_same) == 0

    _LOGGER.info(
        "add_repo: %s@%s, existing_same=%d, new_active=%s",
        component_id, branch, len(existing_same), new_active,
    )

    new_repo_cfg = {
        "repo": repo, "name": name,
        "component_id": component_id, "branch": branch,
        "active": new_active,
        "update_mode": update_mode,
    }
    current_repos.append(new_repo_cfg)

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_REPOS: current_repos}
    )

    ed = _get_entry_data(hass)
    if ed:
        coordinator = ed["coordinator"]
        coordinator.repos = current_repos

        if "async_add_entities" in ed:
            from .update import PrivateHacsUpdateEntity
            ed["async_add_entities"]([PrivateHacsUpdateEntity(coordinator, entry, new_repo_cfg)])

        await coordinator.async_request_refresh()


async def _do_remove_repo(hass: HomeAssistant, component_id: str, branch: str) -> None:
    entry = _get_entry(hass)
    if entry is None:
        raise HomeAssistantError("Private HACS config entry를 찾을 수 없습니다.")

    current_repos: list[dict] = normalize_repo_config(list(entry.data.get(CONF_REPOS, [])))

    # 삭제 대상 찾기
    target = next(
        (r for r in current_repos
         if r["component_id"] == component_id and r.get("branch", "main") == branch),
        None,
    )
    if target is None:
        raise HomeAssistantError(f"'{component_id}@{branch}'는 등록된 저장소가 아닙니다.")

    removing_active = target.get("active", True)
    new_repos = [r for r in current_repos if r is not target]

    # 활성 브랜치를 삭제하는데 같은 component_id의 다른 브랜치가 정확히 1개 남으면 자동 활성화
    siblings = [r for r in new_repos if r["component_id"] == component_id]
    if removing_active and len(siblings) == 1:
        auto_activate_branch = siblings[0].get("branch", "main")
        new_repos = [
            {**r, "active": True} if r["component_id"] == component_id else r
            for r in new_repos
        ]
        _LOGGER.info(
            "Auto-activating %s@%s after active branch %s@%s was removed",
            component_id, auto_activate_branch, component_id, branch,
        )
    else:
        auto_activate_branch = None

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_REPOS: new_repos}
    )

    ed = _get_entry_data(hass)
    if ed:
        coordinator = ed["coordinator"]
        coordinator.repos = new_repos

        entry_key = make_entry_key(component_id, branch)
        if coordinator.data:
            coordinator.data.pop(entry_key, None)
            # 자동 활성화 시 coordinator.data에도 즉시 반영
            if auto_activate_branch:
                auto_key = make_entry_key(component_id, auto_activate_branch)
                if auto_key in coordinator.data:
                    coordinator.data[auto_key]["active"] = True
        coordinator.async_update_listeners()

        entity = ed.get("update_entities", {}).get(entry_key)
        if entity:
            await entity.async_remove(force_remove=True)

    ent_reg = er.async_get(hass)
    uid = f"repo_{component_id}_{branch}"
    entity_id = ent_reg.async_get_entity_id("update", DOMAIN, uid)
    if entity_id:
        ent_reg.async_remove(entity_id)

    _LOGGER.info("Repo unregistered (store kept): %s@%s", component_id, branch)


async def _do_toggle_branch(
    hass: HomeAssistant, component_id: str, branch: str, active: bool
) -> None:
    """
    브랜치 활성/비활성 전환.
    활성화 시: 같은 component_id의 다른 모든 브랜치를 비활성화 후 설치.
    비활성화 시: 상태만 변경.
    """
    entry = _get_entry(hass)
    if entry is None:
        raise HomeAssistantError("Private HACS config entry를 찾을 수 없습니다.")

    # active 필드 정규화 후 처리
    current_repos: list[dict] = normalize_repo_config(list(entry.data.get(CONF_REPOS, [])))
    found = False
    new_repos = []
    for r in current_repos:
        if r["component_id"] == component_id and r.get("branch", "main") == branch:
            new_repos.append({**r, "active": active})
            found = True
        elif r["component_id"] == component_id and active:
            # 같은 component_id의 다른 브랜치는 모두 비활성화
            new_repos.append({**r, "active": False})
        else:
            new_repos.append(r)

    if not found:
        raise HomeAssistantError(f"'{component_id}@{branch}'를 찾을 수 없습니다.")

    # config entry에 저장
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_REPOS: new_repos}
    )

    ed = _get_entry_data(hass)
    if not ed:
        return

    coordinator = ed["coordinator"]
    coordinator.repos = new_repos

    # coordinator.data에 active 즉시 반영
    if coordinator.data:
        for r in new_repos:
            if r["component_id"] == component_id:
                ek = make_entry_key(component_id, r.get("branch", "main"))
                if ek in coordinator.data:
                    coordinator.data[ek]["active"] = r["active"]

    coordinator.async_update_listeners()
    _LOGGER.info(
        "Branch %s@%s set active=%s",
        component_id, branch, active,
    )

    # 활성화 시 refresh만 수행 — 실제 설치는 패널에서 별도 호출
    if active:
        await coordinator.async_request_refresh()


async def _do_set_update_mode(
    hass: HomeAssistant, component_id: str, branch: str, update_mode: str
) -> None:
    """브랜치의 update_mode(release/commit)를 변경합니다."""
    entry = _get_entry(hass)
    if entry is None:
        raise HomeAssistantError("Private HACS config entry를 찾을 수 없습니다.")

    current_repos: list[dict] = normalize_repo_config(list(entry.data.get(CONF_REPOS, [])))
    found = False
    new_repos = []
    for r in current_repos:
        if r["component_id"] == component_id and r.get("branch", "main") == branch:
            new_repos.append({**r, "update_mode": update_mode})
            found = True
        else:
            new_repos.append(r)

    if not found:
        raise HomeAssistantError(f"'{component_id}@{branch}'를 찾을 수 없습니다.")

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_REPOS: new_repos}
    )

    ed = _get_entry_data(hass)
    if ed:
        coordinator = ed["coordinator"]
        coordinator.repos = new_repos
        entry_key = make_entry_key(component_id, branch)
        if coordinator.data and entry_key in coordinator.data:
            coordinator.data[entry_key]["update_mode"] = update_mode
        coordinator.async_update_listeners()
        await coordinator.async_request_refresh()

    _LOGGER.info("update_mode for %s@%s set to %s", component_id, branch, update_mode)


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

    branches: list[str] = []
    try:
        branches = await github.get_branches(repo)
    except Exception as err:
        _LOGGER.debug("Could not list branches for %s: %s", repo, err)

    # 릴리즈 존재 여부 확인 (1개만 조회)
    has_releases = False
    try:
        releases = await github.get_releases(repo, max_count=1)
        has_releases = len(releases) > 0
    except Exception as err:
        _LOGGER.debug("Could not check releases for %s: %s", repo, err)

    return {
        "name": repo_info.get("name", repo.split("/")[1]),
        "description": repo_info.get("description") or "",
        "default_branch": repo_info.get("default_branch", "main"),
        "full_name": repo_info.get("full_name", repo),
        "component_ids": component_ids,
        "branches": branches,
        "has_releases": has_releases,
    }


async def _do_get_readme(hass: HomeAssistant, repo: str, branch: str) -> ServiceResponse:
    ed = _require_entry_data(hass)
    github = ed["github"]
    try:
        content = await github.get_readme(repo, branch)
        return {"content": content or "README 내용을 찾을 수 없습니다."}
    except Exception as exc:
        _LOGGER.error("Failed to fetch README for %s: %s", repo, exc)
        return {"content": f"README 로드 중 오류 발생: {exc}"}


async def _do_get_releases(
    hass: HomeAssistant, component_id: str, branch: str
) -> ServiceResponse:
    ed = _require_entry_data(hass)
    coordinator = ed["coordinator"]
    github = ed["github"]

    entry_key = make_entry_key(component_id, branch)
    if coordinator.data is None or entry_key not in coordinator.data:
        raise HomeAssistantError(f"'{entry_key}'를 찾을 수 없습니다.")

    repo: str = coordinator.data[entry_key]["repo"]
    try:
        releases = await github.get_releases(repo, max_count=10)
        return {"releases": releases}
    except Exception as exc:
        raise HomeAssistantError(f"릴리즈 목록 조회 실패: {exc}") from exc
