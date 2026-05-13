"""DataUpdateCoordinator for Private HACS."""
from __future__ import annotations

import logging
import os
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL_HOURS, DOMAIN
from .github import GitHubClient
from .store import RepositoryStore

_LOGGER = logging.getLogger(__name__)


class PrivateHacsCoordinator(DataUpdateCoordinator):
    """
    Polls GitHub for the latest version of every registered repository.

    coordinator.data → dict[component_id, RepoData]

    RepoData keys:
        repo          str   "owner/repo"
        name          str   friendly name
        component_id  str
        branch        str   default branch
        latest        dict  from GitHubClient.resolve_latest()
        installed     str | None  from RepositoryStore
        is_installed  bool
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
                # Fetch repo metadata for default_branch
                repo_info = await self.github.get_repo_info(repo)
                default_branch = (
                    repo_info.get("default_branch", branch) if repo_info else branch
                )

                latest = await self.github.resolve_latest(repo, default_branch)
            except Exception as err:
                _LOGGER.warning("Failed to fetch info for %s: %s", repo, err)
                latest = None

            installed_version = self.store.installed_version(component_id)
            is_installed = self._check_installed(component_id)

            results[component_id] = {
                "repo": repo,
                "name": item.get("name", repo),
                "component_id": component_id,
                "branch": branch,
                "latest": latest,
                "installed_version": installed_version,
                "is_installed": is_installed,
            }

        return results

    def _check_installed(self, component_id: str) -> bool:
        """Check if the component directory physically exists."""
        config_dir: str = self.hass.config.config_dir
        path = os.path.join(config_dir, "custom_components", component_id)
        return os.path.isdir(path)
