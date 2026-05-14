"""GitHub API helpers for Private HACS."""
from __future__ import annotations

import io
import logging
import os
import shutil
import zipfile
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant

from .const import (
    GITHUB_API_BASE,
    GITHUB_API_RELEASE_LATEST,
    GITHUB_API_RELEASES,
    GITHUB_API_REPO,
    GITHUB_API_TAGS,
    GITHUB_ARCHIVE_ZIP,
)

_LOGGER = logging.getLogger(__name__)


class GitHubClient:
    """Authenticated GitHub API client."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token

    def _headers(self) -> dict:
        h = {"Accept": "application/vnd.github+json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    # ------------------------------------------------------------------
    # Repository metadata
    # ------------------------------------------------------------------

    async def get_repo_info(self, repo: str) -> dict | None:
        """Return basic repo metadata (name, description, default_branch, etc.)."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                GITHUB_API_REPO.format(repo),
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None

    # ------------------------------------------------------------------
    # Latest version detection (release → tag → branch)
    # ------------------------------------------------------------------

    async def get_latest_release(self, repo: str) -> dict | None:
        """Return latest GitHub release dict, or None if not found."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                GITHUB_API_RELEASE_LATEST.format(repo),
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None

    async def get_latest_tag(self, repo: str) -> str | None:
        """Return the most recent tag name, or None."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                GITHUB_API_TAGS.format(repo),
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    tags = await resp.json()
                    if tags:
                        return tags[0].get("name")
                return None

    async def resolve_latest(self, repo: str, default_branch: str = "main") -> dict:
        """
        Resolve the latest version info.

        Priority:
          1. GitHub Release  → version = tag_name, type = "release"
          2. Git Tag         → version = tag_name, type = "tag"
          3. Branch HEAD     → version = branch name, type = "branch"

        Returns a dict with keys:
          version, type, download_ref, release_url, release_summary
        """
        # 1. Try release
        release = await self.get_latest_release(repo)
        if release:
            body = release.get("body", "")
            return {
                "version": release.get("tag_name", "unknown"),
                "type": "release",
                "download_ref": release.get("tag_name"),
                "release_url": release.get("html_url", ""),
                "release_summary": body[:255] if body else None,
            }

        # 2. Try tag
        tag = await self.get_latest_tag(repo)
        if tag:
            return {
                "version": tag,
                "type": "tag",
                "download_ref": tag,
                "release_url": f"https://github.com/{repo}/releases/tag/{tag}",
                "release_summary": None,
            }

        # 3. Fall back to branch
        return {
            "version": default_branch,
            "type": "branch",
            "download_ref": default_branch,
            "release_url": f"https://github.com/{repo}/tree/{default_branch}",
            "release_summary": None,
        }

    # ------------------------------------------------------------------
    # Download & install
    # ------------------------------------------------------------------

    async def download_and_install(
        self,
        hass: HomeAssistant,
        repo: str,
        component_id: str,
        ref: str,
    ) -> None:
        """
        Download the zipball for `ref` and extract the custom_components/<component_id>
        directory into HA's custom_components folder.

        Raises RuntimeError on failure.
        """
        url = GITHUB_ARCHIVE_ZIP.format(repo, ref)
        config_dir: str = hass.config.config_dir
        target_dir = os.path.join(config_dir, "custom_components", component_id)

        _LOGGER.info("Downloading %s @ %s from %s", repo, ref, url)

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=120),
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"Download failed: GitHub returned {resp.status} for {url}"
                    )
                data = await resp.read()

        # Parse zip in memory
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise RuntimeError(f"Downloaded file is not a valid zip: {exc}") from exc

        # GitHub zipball root is "<owner>-<repo>-<sha>/"
        # Find the custom_components/<component_id> path inside the zip
        target_prefix = self._find_component_prefix(zf, component_id)
        if target_prefix is None:
            raise RuntimeError(
                f"Could not find custom_components/{component_id}/ in the downloaded zip.\n"
                f"Make sure the repository has a custom_components/{component_id}/ directory."
            )

        # Remove existing installation
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        os.makedirs(target_dir, exist_ok=True)

        # Extract matching files
        extracted = 0
        for member in zf.namelist():
            if not member.startswith(target_prefix):
                continue
            relative = member[len(target_prefix):]
            if not relative:
                continue  # skip the directory entry itself

            dest = os.path.join(target_dir, relative)

            if member.endswith("/"):
                os.makedirs(dest, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(member) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted += 1

        if extracted == 0:
            raise RuntimeError(
                f"Zip contained the path {target_prefix} but no files were extracted."
            )

        _LOGGER.info("Installed %d files into %s", extracted, target_dir)

    def _find_component_prefix(
        self, zf: zipfile.ZipFile, component_id: str
    ) -> str | None:
        """
        Return the zip path prefix that corresponds to
        custom_components/<component_id>/.

        GitHub zips have a top-level directory like "owner-repo-abc1234/".
        """
        needle = f"custom_components/{component_id}/"
        for name in zf.namelist():
            # Strip the leading "<root>/" part
            parts = name.split("/", 1)
            if len(parts) < 2:
                continue
            remainder = parts[1]
            if remainder == needle or remainder.startswith(needle):
                root_prefix = parts[0] + "/"
                return root_prefix + needle
        return None

    async def uninstall(
        self,
        hass: HomeAssistant,
        component_id: str,
    ) -> None:
        """Remove the installed custom_components/<component_id> directory."""
        config_dir: str = hass.config.config_dir
        target_dir = os.path.join(config_dir, "custom_components", component_id)
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
            _LOGGER.info("Uninstalled %s", component_id)

    async def get_contents(self, repo: str, path: str) -> list[dict] | None:
        """Return contents of a path in the repository."""
        url = f"{GITHUB_API_BASE}/repos/{repo}/contents/{path}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None

    async def get_contents(self, repo: str, path: str) -> list[dict] | None:
        """Return contents of a path in the repository."""
        url = f"{GITHUB_API_BASE}/repos/{repo}/contents/{path}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None

    # ------------------------------------------------------------------
    # Token validation
    # ------------------------------------------------------------------

    async def validate_token(self) -> bool:
        if not self._token:
            return True  # No token = public-only mode, still valid
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{GITHUB_API_BASE}/user",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
