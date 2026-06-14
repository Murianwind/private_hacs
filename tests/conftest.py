"""공통 픽스처 및 헬퍼."""
from __future__ import annotations

import sys
import os

# 저장소 루트를 sys.path에 추가
# custom_components/private_hacs/ 가 패키지로 인식되도록
# import 시 custom_components.private_hacs.coordinator 형태로 사용
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# custom_components.private_hacs 를 짧은 이름으로 접근하기 위한 alias
# 테스트 파일에서 `from custom_components.private_hacs.coordinator import ...` 사용
import importlib, types

def _alias(short: str) -> None:
    """custom_components.private_hacs.<short> 를 <short> 이름으로도 접근 가능하게."""
    full = f"custom_components.private_hacs.{short}"
    mod = importlib.import_module(full)
    sys.modules[short] = mod

for _mod in ["const", "helpers", "store", "github", "coordinator", "services", "update"]:
    try:
        _alias(_mod)
    except Exception:
        pass

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


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

def make_tag(name: str):
    return {"name": name}


# ──────────────────────────────────────────────
# GitHubClient 목업
# ──────────────────────────────────────────────

def make_github_client(
    releases: list[dict] | None = None,
    tags: list[dict] | None = None,
    branch_sha: str | None = None,
    branch_name: str = "main",
    manifest_version: str | None = None,
    repo_info: dict | None = None,
    branches: list[str] | None = None,
):
    client = AsyncMock()
    client.resolve_latest = AsyncMock()
    client.resolve_branch_latest = AsyncMock()
    client.get_repo_info = AsyncMock(return_value=repo_info or {
        "name": "private_hacs",
        "description": "test",
        "default_branch": "main",
        "full_name": "Murianwind/private_hacs",
    })
    client.get_branches = AsyncMock(return_value=branches or ["main", "test"])
    client.get_releases = AsyncMock(return_value=[
        {
            "tag_name": r["tag_name"],
            "name": r.get("name", r["tag_name"]),
            "published_at": (r.get("published_at") or "")[:10],
            "html_url": r.get("html_url", ""),
            "prerelease": r.get("prerelease", False),
            "target_commitish": r.get("target_commitish"),
        }
        for r in (releases or [])
    ])
    return client


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
# Coordinator 헬퍼
# ──────────────────────────────────────────────

def make_hass():
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(return_value=False)
    hass.config.path = MagicMock(return_value="/tmp/test_path")
    hass.config_entries.async_entries = MagicMock(return_value=[])
    hass.config_entries.async_update_entry = MagicMock()
    return hass


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
