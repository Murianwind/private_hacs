"""GitHub API helpers for Private HACS."""
from __future__ import annotations

import io
import logging
import os
import shutil
import zipfile

import aiohttp

from homeassistant.core import HomeAssistant

from .const import (
    GITHUB_API_BASE,
    GITHUB_API_RELEASE_LATEST,
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

    async def get_repo_info(self, repo: str) -> dict | None:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                GITHUB_API_REPO.format(repo),
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None

    async def get_latest_release(self, repo: str) -> dict | None:
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

    async def get_latest_commit_sha(self, repo: str, branch: str) -> str | None:
        """Return the latest commit SHA on the given branch."""
        url = f"{GITHUB_API_BASE}/repos/{repo}/commits/{branch}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("sha")
                return None

    async def get_remote_manifest_version(self, repo: str, component_id: str, branch: str) -> str | None:
        """Return the version field from the remote manifest.json on the given branch."""
        url = f"{GITHUB_API_BASE}/repos/{repo}/contents/custom_components/{component_id}/manifest.json?ref={branch}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={**self._headers(), "Accept": "application/vnd.github.raw+json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    try:
                        import json
                        data = await resp.json(content_type=None)
                        return str(data.get("version")) if data.get("version") else None
                    except Exception:
                        return None
                return None

    async def resolve_latest(self, repo: str, component_id: str, default_branch: str = "main") -> dict:
        """
        Resolve the latest version info.

        Priority:
          1. GitHub Release  → version = tag_name, type = "release"
          2. Git Tag         → version = tag_name, type = "tag"
          3. Branch + remote manifest version + commit SHA → type = "branch"
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
                "commit_sha": None,
                "remote_manifest_version": None,
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
                "commit_sha": None,
                "remote_manifest_version": None,
            }

        # 3. Branch — fetch commit SHA and remote manifest version
        commit_sha = await self.get_latest_commit_sha(repo, default_branch)
        remote_manifest_version = await self.get_remote_manifest_version(repo, component_id, default_branch)

        return {
            "version": default_branch,
            "type": "branch",
            "download_ref": default_branch,
            "release_url": f"https://github.com/{repo}/commits/{default_branch}",
            "release_summary": None,
            "commit_sha": commit_sha,
            "remote_manifest_version": remote_manifest_version,
        }

    async def download_and_install(
        self,
        hass: HomeAssistant,
        repo: str,
        component_id: str,
        ref: str,
    ) -> None:
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

        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise RuntimeError(f"Downloaded file is not a valid zip: {exc}") from exc

        target_prefix = self._find_component_prefix(zf, component_id)
        if target_prefix is None:
            raise RuntimeError(
                f"Could not find custom_components/{component_id}/ in the downloaded zip.\n"
                f"Make sure the repository has a custom_components/{component_id}/ directory."
            )

        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        os.makedirs(target_dir, exist_ok=True)

        extracted = 0
        for member in zf.namelist():
            if not member.startswith(target_prefix):
                continue
            relative = member[len(target_prefix):]
            if not relative:
                continue

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

    def _find_component_prefix(self, zf: zipfile.ZipFile, component_id: str) -> str | None:
        needle = f"custom_components/{component_id}/"
        for name in zf.namelist():
            parts = name.split("/", 1)
            if len(parts) < 2:
                continue
            remainder = parts[1]
            if remainder == needle or remainder.startswith(needle):
                root_prefix = parts[0] + "/"
                return root_prefix + needle
        return None

    async def uninstall(self, hass: HomeAssistant, component_id: str) -> None:
        config_dir: str = hass.config.config_dir
        target_dir = os.path.join(config_dir, "custom_components", component_id)
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
            _LOGGER.info("Uninstalled %s", component_id)

    async def get_contents(self, repo: str, path: str) -> list[dict] | None:
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

    async def validate_token(self) -> bool:
        if not self._token:
            return True
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{GITHUB_API_BASE}/user",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
