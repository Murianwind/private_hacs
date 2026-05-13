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
        repo              str        "owner/repo"
        name              str        friendly name
        component_id      str
        branch            str        default branch
        latest            dict|None  from GitHubClient.resolve_latest()
        installed_version str|None   resolved version (store → manifest → None)
        is_installed      bool       directory physically exists
        version_source    str        "store" | "manifest" | "none"
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

    # ------------------------------------------------------------------
    # Main update
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, dict]:
        results: dict[str, dict] = {}

        for item in self.repos:
            repo: str = item["repo"]
            component_id: str = item["component_id"]
            branch: str = item.get("branch", "main")

            # ── GitHub latest version ──────────────────────────────────
            try:
                repo_info = await self.github.get_repo_info(repo)
                default_branch = (
                    repo_info.get("default_branch", branch) if repo_info else branch
                )
                latest = await self.github.resolve_latest(repo, default_branch)
            except Exception as err:
                _LOGGER.warning("Failed to fetch info for %s: %s", repo, err)
                latest = None

            # ── Installed version (store → manifest fallback) ──────────
            installed_version, version_source = self._resolve_installed_version(
                component_id
            )

            # ── Persist manifest version into store if not yet tracked ─
            if version_source == "manifest" and installed_version:
                await self.store.async_set(
                    component_id, {"installed_version": installed_version}
                )
                _LOGGER.info(
                    "Auto-detected %s v%s from manifest.json — saved to store",
                    component_id,
                    installed_version,
                )
                version_source = "store"  # now persisted

            is_installed = self._check_installed(component_id)

            results[component_id] = {
                "repo": repo,
                "name": item.get("name", repo),
                "component_id": component_id,
                "branch": branch,
                "latest": latest,
                "installed_version": installed_version,
                "is_installed": is_installed,
                "version_source": version_source,
            }

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_installed_version(
        self, component_id: str
    ) -> tuple[str | None, str]:
        """
        Return (version, source) where source is one of:
          "store"    — previously saved by Private HACS after install
          "manifest" — read live from the component's manifest.json
          "none"     — component not installed or no version info
        """
        # 1. Check store first (most reliable; set by us after install)
        stored = self.store.installed_version(component_id)
        if stored:
            return stored, "store"

        # 2. Fall back to manifest.json on disk
        manifest_version = self._read_manifest_version(component_id)
        if manifest_version:
            return manifest_version, "manifest"

        return None, "none"

    def _read_manifest_version(self, component_id: str) -> str | None:
        """
        Read `version` from custom_components/<component_id>/manifest.json.
        Returns None if the file doesn't exist or has no version field.
        """
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
            _LOGGER.debug(
                "Could not read manifest.json for %s: %s", component_id, err
            )
            return None

    def _check_installed(self, component_id: str) -> bool:
        """Return True if the component directory physically exists."""
        config_dir: str = self.hass.config.config_dir
        path = os.path.join(config_dir, "custom_components", component_id)
        return os.path.isdir(path)
