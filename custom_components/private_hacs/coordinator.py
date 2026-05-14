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
                _LOGGER.warning("Failed to fetch version info for %s: %s", repo, err)
                latest = None

            installed_version, version_source = await self._resolve_installed_version(
                component_id
            )
            installed_commit_sha = self.store.get(component_id).get("installed_commit_sha")

            # Persist manifest-detected version to store so it survives restarts
            if version_source == "manifest" and installed_version:
                await self.store.async_set(
                    component_id, {"installed_version": installed_version}
                )
                _LOGGER.info(
                    "Auto-detected %s v%s from manifest.json — persisted to store",
                    component_id,
                    installed_version,
                )
                version_source = "store"

            is_installed = await self._check_installed(component_id)
            has_update = self._compute_has_update(latest, installed_version, installed_commit_sha)

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

    # ------------------------------------------------------------------
    # Update detection
    # ------------------------------------------------------------------

    def _compute_has_update(
        self,
        latest: dict | None,
        installed_version: str | None,
        installed_commit_sha: str | None,
    ) -> bool:
        """
        Determine whether an update is available.

        - release / tag: compare version strings
        - branch: compare remote manifest version first,
                  then fall back to commit SHA comparison
        """
        if not installed_version or latest is None:
            return False

        latest_type = latest.get("type")

        if latest_type in ("release", "tag"):
            return installed_version != latest.get("version")

        if latest_type == "branch":
            remote_manifest_version = latest.get("remote_manifest_version")
            remote_commit_sha = latest.get("commit_sha")

            # Prefer manifest version comparison when available
            if remote_manifest_version:
                if remote_manifest_version != installed_version:
                    return True

            # Fall back to commit SHA comparison
            if remote_commit_sha and installed_commit_sha:
                return remote_commit_sha != installed_commit_sha

        return False

    # ------------------------------------------------------------------
    # Installed version resolution (store → manifest on disk)
    # ------------------------------------------------------------------

    async def _resolve_installed_version(
        self, component_id: str
    ) -> tuple[str | None, str]:
        stored = self.store.installed_version(component_id)
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
