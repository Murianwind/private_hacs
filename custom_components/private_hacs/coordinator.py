"""DataUpdateCoordinator for Private HACS."""
from __future__ import annotations

import json
import logging
import os
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DEFAULT_SCAN_INTERVAL_HOURS, DOMAIN
from .github import GitHubClient
from .store import RepositoryStore

_LOGGER = logging.getLogger(__name__)


class PrivateHacsCoordinator(DataUpdateCoordinator):
    """
    Polls GitHub for the latest version of every registered repository.

    coordinator.data → dict[component_id, RepoData]

    RepoData keys:
        repo                    str
        name                    str
        component_id            str
        branch                  str
        latest                  dict|None
        installed_version       str|None
        installed_commit_sha    str|None   (저장된 commit SHA)
        is_installed            bool
        version_source          str        "store" | "manifest" | "none"
        has_update              bool       업데이트 여부 (commit 기반 포함)
    """

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

        for item in self.repos:
            repo: str = item["repo"]
            component_id: str = item["component_id"]
            branch: str = item.get("branch", "main")

            try:
                repo_info = await self.github.get_repo_info(repo)
                default_branch = (
                    repo_info.get("default_branch", branch) if repo_info else branch
                )
                latest = await self.github.resolve_latest(repo, component_id, default_branch)
            except Exception as err:
                _LOGGER.warning("Failed to fetch info for %s: %s", repo, err)
                latest = None

            installed_version, version_source = self._resolve_installed_version(component_id)
            installed_commit_sha = self.store.get(component_id).get("installed_commit_sha")

            # manifest 버전을 store에 자동 저장
            if version_source == "manifest" and installed_version:
                await self.store.async_set(
                    component_id, {"installed_version": installed_version}
                )
                _LOGGER.info(
                    "Auto-detected %s v%s from manifest.json — saved to store",
                    component_id,
                    installed_version,
                )
                version_source = "store"

            is_installed = self._check_installed(component_id)
            has_update = self._compute_has_update(
                latest, installed_version, installed_commit_sha
            )

            results[component_id] = {
                "repo": repo,
                "name": item.get("name", repo),
                "component_id": component_id,
                "branch": branch,
                "latest": latest,
                "installed_version": installed_version,
                "installed_commit_sha": installed_commit_sha,
                "is_installed": is_installed,
                "version_source": version_source,
                "has_update": has_update,
            }

        return results

    def _compute_has_update(
        self,
        latest: dict | None,
        installed_version: str | None,
        installed_commit_sha: str | None,
    ) -> bool:
        """
        업데이트 여부를 판단합니다.

        - 미설치: False
        - release/tag 타입: 버전 문자열 비교
        - branch 타입:
            1. remote manifest version vs installed version 비교
            2. 동일하거나 없으면 commit SHA 비교
        """
        if not installed_version:
            return False
        if latest is None:
            return False

        latest_type = latest.get("type")
        latest_version = latest.get("version")

        if latest_type in ("release", "tag"):
            # 버전 문자열이 다르면 업데이트
            return installed_version != latest_version

        if latest_type == "branch":
            remote_manifest_version = latest.get("remote_manifest_version")
            remote_commit_sha = latest.get("commit_sha")

            # remote manifest 버전이 있으면 버전 비교 우선
            if remote_manifest_version:
                if remote_manifest_version != installed_version:
                    return True

            # 버전이 같거나 없으면 commit SHA 비교
            if remote_commit_sha and installed_commit_sha:
                return remote_commit_sha != installed_commit_sha

            # commit SHA가 없으면 (저장 안 된 경우) 업데이트 없음으로 처리
            return False

        return False

    def _resolve_installed_version(self, component_id: str) -> tuple[str | None, str]:
        stored = self.store.installed_version(component_id)
        if stored:
            return stored, "store"

        manifest_version = self._read_manifest_version(component_id)
        if manifest_version:
            return manifest_version, "manifest"

        return None, "none"

    def _read_manifest_version(self, component_id: str) -> str | None:
        config_dir: str = self.hass.config.config_dir
        manifest_path = os.path.join(
            config_dir, "custom_components", component_id, "manifest.json"
        )
        if not os.path.isfile(manifest_path):
            return None
        try:
            with open(manifest_path, encoding="utf-8") as f:
                data = json.load(f)
            version = data.get("version")
            return str(version) if version else None
        except Exception as err:
            _LOGGER.debug("Could not read manifest.json for %s: %s", component_id, err)
            return None

    def _check_installed(self, component_id: str) -> bool:
        config_dir: str = self.hass.config.config_dir
        path = os.path.join(config_dir, "custom_components", component_id)
        return os.path.isdir(path)
