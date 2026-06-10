"""DataUpdateCoordinator for Private HACS."""
from __future__ import annotations

import json
import logging
import os
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DEFAULT_SCAN_INTERVAL_HOURS, DOMAIN
from .github import GitHubClient
from .store import RepositoryStore

_LOGGER = logging.getLogger(__name__)


def make_entry_key(component_id: str, branch: str) -> str:
    """Return the internal dict key for a (component_id, branch) pair."""
    return f"{component_id}@{branch}"


class PrivateHacsCoordinator(DataUpdateCoordinator):
    """Polls GitHub for the latest version of every registered repository."""

    def __init__(
        self,
        hass: HomeAssistant,
        repos: list[dict],
        github: GitHubClient,
        store: RepositoryStore,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=DEFAULT_SCAN_INTERVAL_HOURS),
        )
        self.repos = repos
        self.github = github
        self.store = store

    async def _async_update_data(self) -> dict[str, dict]:
        results: dict[str, dict] = {}

        # component_id별 설치 여부를 한 번만 확인 (같은 component_id 브랜치가 여러 개일 때 중복 방지)
        installed_cache: dict[str, bool] = {}
        # has_icon도 component_id별 1회만 확인
        has_icon_cache: dict[str, bool] = {}

        for item in self.repos:
            repo: str = item["repo"]
            component_id: str = item["component_id"]
            branch: str = item.get("branch", "main")
            active: bool = item.get("active", True)
            entry_key = make_entry_key(component_id, branch)

            # 설치 여부: 캐시 활용
            if component_id not in installed_cache:
                installed_cache[component_id] = await self._check_installed(component_id)
            is_installed = installed_cache[component_id]
            # has_icon도 component_id별 1회만 확인 (executor에서 blocking I/O)
            if component_id not in has_icon_cache:
                icon_path = self.hass.config.path(
                    "custom_components", component_id, "brand", "icon.png"
                )
                has_icon_cache[component_id] = await self.hass.async_add_executor_job(
                    os.path.isfile, icon_path
                )

            # 비활성 브랜치는 GitHub API 호출 최소화
            # prev에 latest가 있으면 재사용, 없으면 1회 조회
            if not active:
                prev = (self.data or {}).get(entry_key, {})
                store_entry = self.store.get_branch(component_id, branch)
                installed_version = self.store.installed_version(component_id, branch)

                latest = prev.get("latest")
                if latest is None:
                    # 최초 1회: latest_type 등 메타 정보 확보
                    try:
                        latest = await self.github.resolve_latest(repo, component_id, branch)
                    except ConfigEntryAuthFailed:
                        raise
                    except Exception as err:
                        _LOGGER.debug("Failed to fetch latest for inactive %s: %s", repo, err)
                        latest = None

                results[entry_key] = {
                    **prev,
                    "entry_key": entry_key,
                    "repo": repo,
                    "name": item.get("name", repo),
                    "component_id": component_id,
                    "branch": branch,
                    "active": False,
                    "latest": latest,
                    "installed_version": installed_version,
                    "installed_commit_sha": store_entry.get("installed_commit_sha"),
                    "is_installed": is_installed,
                    "has_update": False,
                    "has_icon": has_icon_cache.get(component_id, False),
                }
                continue

            try:
                latest = await self.github.resolve_latest(repo, component_id, branch)
            except ConfigEntryAuthFailed:
                raise  # 인증 실패는 HA가 처리하도록 전파
            except Exception as err:
                _LOGGER.warning("Failed to fetch version info for %s: %s", repo, err)
                latest = None

            installed_version, version_source = await self._resolve_installed_version(
                component_id, branch
            )
            store_entry = self.store.get_branch(component_id, branch)
            installed_commit_sha = store_entry.get("installed_commit_sha")

            if version_source == "manifest" and installed_version:
                await self.store.async_set_branch(
                    component_id, branch, {"installed_version": installed_version}
                )
                _LOGGER.debug(
                    "Auto-detected %s@%s v%s from manifest.json — persisted to store",
                    component_id, branch, installed_version,
                )
                version_source = "store"

            has_update = self._compute_has_update(latest, installed_version, installed_commit_sha)

            # branch 타입이고 설치됐는데 SHA가 없는 경우 자동 복구
            # has_update=False일 때만 — 현재 최신 커밋이 설치된 것으로 간주
            if (
                is_installed
                and installed_version
                and not installed_commit_sha
                and latest
                and latest.get("type") == "branch"
                and latest.get("commit_sha")
                and not has_update
            ):
                installed_commit_sha = latest["commit_sha"]
                await self.store.async_set_branch(
                    component_id, branch, {"installed_commit_sha": installed_commit_sha}
                )
                _LOGGER.debug(
                    "Auto-recovered installed_commit_sha for %s@%s: %s",
                    component_id, branch, installed_commit_sha[:7],
                )

            results[entry_key] = {
                "entry_key": entry_key,
                "repo": repo,
                "name": item.get("name", repo),
                "component_id": component_id,
                "branch": branch,
                "active": active,
                "latest": latest,
                "installed_version": installed_version,
                "installed_commit_sha": installed_commit_sha,
                "is_installed": is_installed,
                "version_source": version_source,
                "has_update": has_update,
                "has_icon": has_icon_cache.get(component_id, False),
            }

        return results

    # ------------------------------------------------------------------
    # Update detection
    # ------------------------------------------------------------------

    def _compute_has_update(
        self,
        latest: dict | None,
        installed_version: str | None,
        installed_commit_sha: str | None,
    ) -> bool:
        if not installed_version or latest is None:
            return False

        latest_type = latest.get("type")

        if latest_type in ("release", "tag"):
            # v 접두사 정규화 후 비교
            def _strip_v(v: str) -> str:
                return v.lstrip("v") if v else v
            return _strip_v(str(installed_version)) != _strip_v(str(latest.get("version", "")))

        if latest_type == "branch":
            remote_manifest_version = latest.get("remote_manifest_version")
            remote_commit_sha = latest.get("commit_sha")

            if remote_manifest_version:
                if remote_manifest_version != installed_version:
                    return True

            if remote_commit_sha and installed_commit_sha:
                return remote_commit_sha != installed_commit_sha

        return False

    # ------------------------------------------------------------------
    # Installed version resolution (store → manifest on disk)
    # ------------------------------------------------------------------

    async def _resolve_installed_version(
        self, component_id: str, branch: str
    ) -> tuple[str | None, str]:
        stored = self.store.installed_version(component_id, branch)
        if stored:
            return stored, "store"

        manifest_version = await self.hass.async_add_executor_job(
            self._read_manifest_version_sync, component_id
        )
        if manifest_version:
            return manifest_version, "manifest"

        return None, "none"

    def _read_manifest_version_sync(self, component_id: str) -> str | None:
        """Read version from manifest.json (blocking — run in executor)."""
        path = self.hass.config.path(
            "custom_components", component_id, "manifest.json"
        )
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            version = data.get("version")
            return str(version) if version else None
        except Exception as err:
            _LOGGER.debug("Could not read manifest.json for %s: %s", component_id, err)
            return None

    async def _check_installed(self, component_id: str) -> bool:
        """Check whether the component directory exists (blocking — run in executor)."""
        path = self.hass.config.path("custom_components", component_id)
        return await self.hass.async_add_executor_job(os.path.isdir, path)
