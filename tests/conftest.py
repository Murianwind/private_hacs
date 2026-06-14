"""공통 픽스처 및 헬퍼."""
from __future__ import annotations

import sys
import os

# 저장소 루트를 sys.path에 추가 — 상대 임포트가 패키지 컨텍스트에서 동작하도록
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# custom_components.private_hacs.* 를 짧은 이름으로도 접근 가능하게 alias
import importlib
for _mod in ["const", "helpers", "store", "github", "coordinator", "services", "update"]:
    try:
        full = f"custom_components.private_hacs.{_mod}"
        mod = importlib.import_module(full)
        sys.modules[_mod] = mod
    except Exception:
        pass

import pytest
from unittest.mock import AsyncMock, MagicMock


# ──────────────────────────────────────────────
# GitHub API 응답 팩토리
# ──────────────────────────────────────────────

def make_release(tag: str, branch: str = "main", name: str = None, body: str = ""):
    return {
        "tag_name": tag,
        "name": name or tag,
        "html_url": f"https://github.com/Murianwind/private_hacs/releases/tag/{tag}",
        "target_commitish": branch,
        "body": body,
        "published_at": "2024-01-01T00:00:00Z",
        "prerelease": False,
    }

def make_branch_resp(sha: str, branch: str = "main"):
    return {"commit": {"sha": sha}, "name": branch}


# ──────────────────────────────────────────────
# RepositoryStore 목업
# ──────────────────────────────────────────────

def make_store(installed: dict | None = None):
    """installed: {(component_id, branch): {installed_version, installed_commit_sha}}"""
    store = MagicMock()
    installed = installed or {}

    def _get_branch(component_id, branch):
        return installed.get((component_id, branch), {})

    def _installed_version(component_id, branch):
        return installed.get((component_id, branch), {}).get("installed_version")

    store.get_branch = MagicMock(side_effect=_get_branch)
    store.installed_version = MagicMock(side_effect=_installed_version)
    store.async_set_branch = AsyncMock()
    store.async_remove_branch = AsyncMock()
    store.async_remove = AsyncMock()
    store.async_load = AsyncMock()
    store.async_save = AsyncMock()
    return store


# ──────────────────────────────────────────────
# hass 목업
# ──────────────────────────────────────────────

def make_hass(domain: str = "private_hacs"):
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(return_value=False)
    hass.config.path = MagicMock(return_value="/tmp/test_path")
    hass.config_entries.async_entries = MagicMock(return_value=[])
    hass.config_entries.async_update_entry = MagicMock()
    hass.data = {}
    return hass


# ──────────────────────────────────────────────
# repo item 팩토리
# ──────────────────────────────────────────────

def make_repo_item(
    repo: str = "Murianwind/private_hacs",
    component_id: str = "private_hacs",
    branch: str = "main",
    active: bool = True,
    update_mode: str = "release",
    name: str = "Private HACS",
):
    return {
        "repo": repo,
        "component_id": component_id,
        "branch": branch,
        "active": active,
        "update_mode": update_mode,
        "name": name,
    }


# ──────────────────────────────────────────────
# services.py 테스트용 hass + entry_data 셋업
# hass.data[DOMAIN][entry_id] 구조를 정확히 재현
# ──────────────────────────────────────────────

def make_hass_for_services(repos, store, github, coordinator=None):
    """
    services.py의 _get_entry_data(hass) 가 동작하도록
    hass.data[DOMAIN][entry_id] = entry_data 구조를 셋업합니다.
    """
    from custom_components.private_hacs.const import DOMAIN, CONF_REPOS

    coord = coordinator or MagicMock()
    coord.repos = list(repos)
    coord.data = {}
    coord.async_request_refresh = AsyncMock()
    coord.async_update_listeners = MagicMock()

    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {CONF_REPOS: list(repos)}

    entry_data = {
        "coordinator": coord,
        "github": github,
        "store": store,
    }

    hass = make_hass()
    hass.data[DOMAIN] = {"test_entry_id": entry_data}
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    hass.config_entries.async_update_entry = MagicMock(
        side_effect=lambda e, **kwargs: setattr(e, "data", kwargs.get("data", e.data))
    )

    return hass, entry, entry_data, coord
