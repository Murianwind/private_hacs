"""GitHub API client for Private HACS."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
import tempfile
import zipfile

import aiohttp

_LOGGER = logging.getLogger(__name__)

class GitHubClient:
    """GitHub API client with token auth."""

    def __init__(self, token: str, session: aiohttp.ClientSession) -> None:
        self.token = token
        self.session = session
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

    async def get_repo_info(self, repo: str) -> dict | None:
        """Get basic repository information."""
        url = f"{self.base_url}/repos/{repo}"
        async with self.session.get(url, headers=self.headers) as resp:
            if resp.status == 200:
                return await resp.json()
            _LOGGER.error("Failed to get repo info for %s: %s", repo, resp.status)
            return None

    async def resolve_latest(self, repo: str, component_id: str, branch: str = "main") -> dict | None:
        """
        Resolve latest version. 
        1. Try latest release.
        2. If no release, try latest tag.
        3. If no tag, use the specified branch head.
        """
        # 1. Release
        url = f"{self.base_url}/repos/{repo}/releases/latest"
        async with self.session.get(url, headers=self.headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                return {
                    "type": "release",
                    "version": data["tag_name"],
                    "download_ref": data["tag_name"],
                    "release_url": data["html_url"],
                    "release_summary": data.get("body"),
                }

        # 2. Tag
        url = f"{self.base_url}/repos/{repo}/tags"
        async with self.session.get(url, headers=self.headers) as resp:
            if resp.status == 200:
                tags = await resp.json()
                if tags:
                    tag = tags[0]
                    return {
                        "type": "tag",
                        "version": tag["name"],
                        "download_ref": tag["name"],
                        "release_url": f"https://github.com/{repo}/tree/{tag['name']}",
                        "release_summary": f"Tag: {tag['name']}",
                    }

        # 3. Branch
        url = f"{self.base_url}/repos/{repo}/branches/{branch}"
        async with self.session.get(url, headers=self.headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                commit_sha = data["commit"]["sha"]
                
                # Try to get version from manifest.json on this branch
                remote_manifest_version = await self._get_remote_manifest_version(repo, commit_sha, component_id)
                
                return {
                    "type": "branch",
                    "version": remote_manifest_version or commit_sha[:7],
                    "download_ref": branch,
                    "commit_sha": commit_sha,
                    "remote_manifest_version": remote_manifest_version,
                }
        
        return None

    async def _get_remote_manifest_version(self, repo: str, ref: str, component_id: str) -> str | None:
        """Fetch manifest.json from remote to get version."""
        url = f"{self.base_url}/repos/{repo}/contents/custom_components/{component_id}/manifest.json?ref={ref}"
        async with self.session.get(url, headers=self.headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("encoding") == "base64":
                    content = base64.b64decode(data["content"]).decode("utf-8")
                    try:
                        import json
                        manifest = json.loads(content)
                        return manifest.get("version")
                    except Exception:
                        pass
        return None

    async def get_contents(self, repo: str, path: str = "") -> list | dict | None:
        """Get contents of a path."""
        url = f"{self.base_url}/repos/{repo}/contents/{path}"
        async with self.session.get(url, headers=self.headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return None

    # 요구사항 3 구현을 위해 새로 추가된 메서드
    async def get_readme(self, repo: str, branch: str = "main") -> str | None:
        """Fetch README.md content from the repository."""
        url = f"{self.base_url}/repos/{repo}/readme?ref={branch}"
        async with self.session.get(url, headers=self.headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("encoding") == "base64":
                    return base64.b64decode(data["content"]).decode("utf-8")
            elif resp.status == 404:
                _LOGGER.debug("README not found for %s", repo)
            else:
                _LOGGER.error("Failed to get README for %s: %s", repo, resp.status)
        return None

    async def download_and_install(self, hass, repo: str, component_id: str, ref: str) -> None:
        """Download zip from GitHub and extract custom_components/component_id to local."""
        download_url = f"https://github.com/{repo}/archive/refs/heads/{ref}.zip"
        if ref != "main" and not ref.startswith("v") and "." not in ref: # branch가 아닐 가능성이 높을 때 (tag/release)
             download_url = f"https://github.com/{repo}/archive/refs/tags/{ref}.zip"
        
        # 실제 ref가 무엇인지에 따라 GitHub의 zip 생성 경로가 달라질 수 있으므로 확인이 필요할 수 있음.
        # 여기서는 단순화하여 시도하고, 실패 시 tags 시도.
        
        async with self.session.get(download_url, headers=self.headers) as resp:
            if resp.status != 200:
                # tags 시도
                download_url = f"https://github.com/{repo}/archive/refs/tags/{ref}.zip"
                async with self.session.get(download_url, headers=self.headers) as tag_resp:
                    if tag_resp.status != 200:
                         raise Exception(f"Download failed: {tag_resp.status}")
                    content = await tag_resp.read()
            else:
                content = await resp.read()

        def _extract():
            with tempfile.TemporaryDirectory() as tmp_dir:
                zip_path = os.path.join(tmp_dir, "repo.zip")
                with open(zip_path, "wb") as f:
                    f.write(content)
                
                with zipfile.ZipFile(zip_path, "r") as z:
                    z.extractall(tmp_dir)
                
                # 압축 해제된 폴더 찾기 (보통 repo-branch 형식)
                extracted_root = None
                for d in os.listdir(tmp_dir):
                    if os.path.isdir(os.path.join(tmp_dir, d)) and d != "__MACOSX":
                        extracted_root = os.path.join(tmp_dir, d)
                        break
                
                if not extracted_root:
                    raise Exception("Extracted root not found")

                source_dir = os.path.join(extracted_root, "custom_components", component_id)
                if not os.path.exists(source_dir):
                    raise Exception(f"Component directory not found in zip: custom_components/{component_id}")

                dest_dir = os.path.join(hass.config.config_dir, "custom_components", component_id)
                if os.path.exists(dest_dir):
                    shutil.rmtree(dest_dir)
                
                os.makedirs(os.path.dirname(dest_dir), exist_ok=True)
                shutil.copytree(source_dir, dest_dir)

        await hass.async_add_executor_job(_extract)

    async def uninstall(self, hass, component_id: str) -> None:
        """Remove the component directory from local filesystem."""
        dest_dir = os.path.join(hass.config.config_dir, "custom_components", component_id)
        
        def _remove():
            if os.path.exists(dest_dir):
                shutil.rmtree(dest_dir)
        
        await hass.async_add_executor_job(_remove)
