"""GitHub API client for Private HACS."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shutil
import tempfile
import zipfile

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

_LOGGER = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


class GitHubAuthError(ConfigEntryAuthFailed):
    """GitHub 인증 실패 — 토큰이 만료되었거나 유효하지 않습니다."""


class GitHubClient:
    """Authenticated GitHub API client using HA's shared aiohttp session."""

    def __init__(self, token: str | None, session: aiohttp.ClientSession) -> None:
        self._token = token
        self._session = session

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "HomeAssistant-PrivateHACS",
        }
        if self._token:
            headers["Authorization"] = f"token {self._token}"
        return headers

    # ------------------------------------------------------------------
    # Repository info
    # ------------------------------------------------------------------

    async def get_repo_info(self, repo: str) -> dict | None:
        url = f"{_GITHUB_API}/repos/{repo}"
        async with self._session.get(url, headers=self._headers()) as resp:
            if resp.status == 200:
                return await resp.json()
            elif resp.status == 401:
                raise GitHubAuthError(
                    "GitHub 토큰이 만료되었거나 유효하지 않습니다. 토큰을 재설정해주세요."
                )
            elif resp.status == 403:
                _LOGGER.warning("get_repo_info %s — 접근 거부(403). 토큰 권한을 확인하세요.", repo)
            else:
                _LOGGER.debug("get_repo_info %s → %s", repo, resp.status)
            return None

    async def get_branches(self, repo: str) -> list[str]:
        """Return list of branch names for the repo."""
        url = f"{_GITHUB_API}/repos/{repo}/branches?per_page=100"
        async with self._session.get(url, headers=self._headers()) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return [b["name"] for b in data if isinstance(b, dict) and "name" in b]

    async def get_contents(self, repo: str, path: str = "") -> list | dict | None:
        url = f"{_GITHUB_API}/repos/{repo}/contents/{path}"
        async with self._session.get(url, headers=self._headers()) as resp:
            if resp.status == 200:
                return await resp.json()
            return None

    # ------------------------------------------------------------------
    # 설치된 SHA를 모를 때, 로컬 파일을 원격 HEAD와 비교해 확정 시도
    # ------------------------------------------------------------------

    @staticmethod
    def _git_blob_sha(content: bytes) -> str:
        """Git이 사용하는 blob SHA-1을 계산합니다 (git hash-object와 동일한 결과)."""
        header = f"blob {len(content)}\0".encode()
        return hashlib.sha1(header + content).hexdigest()

    async def get_tree(self, repo: str, ref: str) -> dict[str, str] | None:
        """
        ref(브랜치/커밋)의 전체 파일 트리를 {경로: blob_sha} 형태로 반환합니다.
        Git Trees API(recursive=1) 한 번으로 전체 구조를 가져옵니다.
        """
        url = f"{_GITHUB_API}/repos/{repo}/git/trees/{ref}?recursive=1"
        async with self._session.get(url, headers=self._headers()) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            if data.get("truncated"):
                _LOGGER.debug("get_tree %s@%s: 응답이 잘렸습니다(파일 too many)", repo, ref)
            return {
                item["path"]: item["sha"]
                for item in data.get("tree", [])
                if item.get("type") == "blob"
            }

    async def verify_installed_sha(
        self, hass: HomeAssistant, repo: str, component_id: str, head_sha: str
    ) -> bool:
        """
        디스크에 설치된 컴포넌트 파일들이 원격 head_sha 커밋과
        100% 동일한지 확인합니다.

        방법: head_sha 커밋의 git tree에서 custom_components/{component_id}/
        하위 파일들의 blob SHA 목록을 가져오고, 로컬 파일의 blob SHA를
        직접 계산(git hash-object 알고리즘)해서 전부 일치하는지 비교합니다.

        전부 일치하면 True — 이 경우에만 installed_commit_sha를 head_sha로
        안전하게 확정할 수 있습니다. 하나라도 다르거나 파일이 없으면 False를
        반환하여, 호출 측이 "알 수 없음" 상태를 유지하고 업데이트로 표시하게
        합니다. 즉, 모호할 때는 항상 "업데이트 필요"로 안전하게 처리합니다.
        """
        remote_tree = await self.get_tree(repo, head_sha)
        if remote_tree is None:
            return False

        prefix = f"custom_components/{component_id}/"
        remote_files = {
            path[len(prefix):]: sha
            for path, sha in remote_tree.items()
            if path.startswith(prefix)
        }
        if not remote_files:
            return False

        local_dir = hass.config.path("custom_components", component_id)

        def _read_and_hash_all() -> dict[str, str] | None:
            local_hashes: dict[str, str] = {}
            for rel_path in remote_files:
                full_path = os.path.join(local_dir, *rel_path.split("/"))
                if not os.path.isfile(full_path):
                    return None
                try:
                    with open(full_path, "rb") as f:
                        content = f.read()
                except OSError:
                    return None
                local_hashes[rel_path] = self._git_blob_sha(content)
            return local_hashes

        local_hashes = await hass.async_add_executor_job(_read_and_hash_all)
        if local_hashes is None:
            return False

        return all(
            local_hashes.get(rel_path) == sha
            for rel_path, sha in remote_files.items()
        )

    async def get_readme(self, repo: str, branch: str = "main") -> str | None:
        """Fetch README content (decoded from base64)."""
        url = f"{_GITHUB_API}/repos/{repo}/readme?ref={branch}"
        async with self._session.get(url, headers=self._headers()) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("encoding") == "base64":
                    return base64.b64decode(data["content"]).decode("utf-8")
            elif resp.status == 401:
                _LOGGER.warning("get_readme %s — 인증 실패(401). 토큰을 확인하세요.", repo)
            elif resp.status == 403:
                _LOGGER.warning("get_readme %s — 접근 거부(403). 토큰 권한을 확인하세요.", repo)
            elif resp.status != 404:
                _LOGGER.debug("get_readme %s → %s", repo, resp.status)
            return None

    async def get_releases(self, repo: str, max_count: int = 10) -> list[dict]:
        """Return up to max_count releases (tag_name, name, published_at, html_url)."""
        url = f"{_GITHUB_API}/repos/{repo}/releases?per_page={max_count}"
        async with self._session.get(url, headers=self._headers()) as resp:
            if resp.status != 200:
                return []
            releases = await resp.json()
            return [
                {
                    "tag_name": r["tag_name"],
                    "name": r.get("name") or r["tag_name"],
                    "published_at": (r.get("published_at") or "")[:10],
                    "html_url": r.get("html_url", ""),
                    "prerelease": r.get("prerelease", False),
                    "target_commitish": r.get("target_commitish"),
                }
                for r in releases
                if isinstance(r, dict)
            ]

    # ------------------------------------------------------------------
    # Version resolution: release → tag → branch
    # ------------------------------------------------------------------

    async def resolve_branch_latest(
        self, repo: str, component_id: str, branch: str
    ) -> dict | None:
        """
        Branch HEAD만 조회합니다 (update_mode=commit 전용).
        릴리즈/태그를 건너뛰고 바로 브랜치 커밋 SHA를 반환합니다.
        """
        url = f"{_GITHUB_API}/repos/{repo}/branches/{branch}"
        async with self._session.get(url, headers=self._headers()) as resp:
            if resp.status == 200:
                data = await resp.json()
                commit_sha: str = data["commit"]["sha"]
                remote_version = await self._get_remote_manifest_version(
                    repo, commit_sha, component_id
                )
                return {
                    "type": "branch",
                    "version": remote_version or commit_sha[:7],
                    "download_ref": branch,
                    "release_url": f"https://github.com/{repo}/commits/{branch}",
                    "release_summary": None,
                    "commit_sha": commit_sha,
                    "remote_manifest_version": remote_version,
                }
            elif resp.status == 401:
                raise GitHubAuthError(
                    "GitHub 토큰이 만료되었거나 유효하지 않습니다. 토큰을 재설정해주세요."
                )
            # debug 레벨은 HA 기본 로그 설정에서 보이지 않아 실패가 조용히
            # 묻히고, 화면에는 예전 값이 "최신"인 것처럼 남는다. rate limit(403)
            # 등 원인을 확인할 수 있도록 warning으로 승격하고 응답 본문을 남긴다.
            try:
                body = await resp.text()
            except Exception:
                body = "<응답 본문 읽기 실패>"
            if resp.status == 403:
                remaining = resp.headers.get("X-RateLimit-Remaining")
                reset = resp.headers.get("X-RateLimit-Reset")
                _LOGGER.warning(
                    "resolve_branch_latest %s@%s — 접근 거부(403). "
                    "RateLimit-Remaining=%s RateLimit-Reset=%s: %s",
                    repo, branch, remaining, reset, body[:300],
                )
            else:
                _LOGGER.warning(
                    "resolve_branch_latest %s@%s → HTTP %s: %s",
                    repo, branch, resp.status, body[:300],
                )
            return None

    async def has_any_release_or_tag(self, repo: str) -> bool:
        """
        저장소에 릴리즈 또는 태그가 하나라도 있는지 확인합니다(목록 1개만 요청).
        결과는 한 번 확인되면 store에 캐시되어 재사용되므로(coordinator 참고),
        이 메서드 자체는 폴링마다 호출되지 않는다 — 캐시가 없을 때만 호출된다.
        """
        url = f"{_GITHUB_API}/repos/{repo}/releases?per_page=1"
        async with self._session.get(url, headers=self._headers()) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data:
                    return True
        url = f"{_GITHUB_API}/repos/{repo}/tags?per_page=1"
        async with self._session.get(url, headers=self._headers()) as resp:
            if resp.status == 200:
                data = await resp.json()
                return bool(data)
        return False

    async def resolve_latest(
        self, repo: str, component_id: str, branch: str = "main"
    ) -> dict | None:
        """
        Resolve the latest available version for the given branch.

        Priority:
          1. GitHub Release targeting this branch (target_commitish == branch)
          2. Git Tag (브랜치 무관 — 태그는 저장소 전체의 버전으로 간주)
          3. Branch HEAD → type="branch"
        """
        def _check_auth(status: int) -> None:
            if status == 401:
                raise GitHubAuthError("GitHub 토큰이 유효하지 않습니다. 토큰을 재설정해주세요.")

        try:
            # 1. Release — 현재 브랜치를 타겟으로 하는 최신 릴리즈 필터링
            url = f"{_GITHUB_API}/repos/{repo}/releases?per_page=20"
            async with self._session.get(url, headers=self._headers()) as resp:
                _check_auth(resp.status)
                if resp.status == 403:
                    _LOGGER.warning("resolve_latest %s — Rate Limit 또는 접근 거부(403).", repo)
                    return None
                if resp.status == 200:
                    releases = await resp.json()
                    branch_releases = [
                        r for r in releases
                        if isinstance(r, dict) and r.get("target_commitish") == branch
                    ]
                    if branch_releases:
                        data = branch_releases[0]
                        return {
                            "type": "release",
                            "version": data["tag_name"],
                            "download_ref": data["tag_name"],
                            "release_url": data["html_url"],
                            "release_summary": (data.get("body") or "")[:255] or None,
                            "commit_sha": None,
                            "remote_manifest_version": None,
                        }

            # 2. Tag (브랜치 무관)
            url = f"{_GITHUB_API}/repos/{repo}/tags"
            async with self._session.get(url, headers=self._headers()) as resp:
                _check_auth(resp.status)
                if resp.status == 403:
                    _LOGGER.warning("resolve_latest(tags) %s — 접근 거부(403).", repo)
                    return None
                if resp.status == 200:
                    tags = await resp.json()
                    if tags:
                        tag_name = tags[0]["name"]
                        return {
                            "type": "tag",
                            "version": tag_name,
                            "download_ref": tag_name,
                            "release_url": f"https://github.com/{repo}/releases/tag/{tag_name}",
                            "release_summary": None,
                            "commit_sha": None,
                            "remote_manifest_version": None,
                        }

            # 3. Branch HEAD
            url = f"{_GITHUB_API}/repos/{repo}/branches/{branch}"
            async with self._session.get(url, headers=self._headers()) as resp:
                _check_auth(resp.status)
                if resp.status == 200:
                    data = await resp.json()
                    commit_sha: str = data["commit"]["sha"]
                    remote_version = await self._get_remote_manifest_version(
                        repo, commit_sha, component_id
                    )
                    return {
                        "type": "branch",
                        "version": remote_version or commit_sha[:7],
                        "download_ref": branch,
                        "release_url": f"https://github.com/{repo}/commits/{branch}",
                        "release_summary": None,
                        "commit_sha": commit_sha,
                        "remote_manifest_version": remote_version,
                    }

        except GitHubAuthError:
            raise
        except Exception as err:
            _LOGGER.warning("Error resolving latest for %s@%s: %s", repo, branch, err)

        _LOGGER.warning("resolve_latest: no version info found for %s@%s", repo, branch)
        return None

    async def _get_remote_manifest_version(
        self, repo: str, ref: str, component_id: str
    ) -> str | None:
        """Return version from remote manifest.json at the given ref."""
        url = (
            f"{_GITHUB_API}/repos/{repo}/contents"
            f"/custom_components/{component_id}/manifest.json?ref={ref}"
        )
        async with self._session.get(url, headers=self._headers()) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            if data.get("encoding") != "base64":
                return None
            try:
                manifest = json.loads(base64.b64decode(data["content"]).decode("utf-8"))
                version = manifest.get("version")
                return str(version) if version else None
            except Exception as err:
                _LOGGER.debug("Could not parse remote manifest for %s: %s", repo, err)
                return None

    # ------------------------------------------------------------------
    # Install / uninstall
    # ------------------------------------------------------------------

    async def download_and_install(
        self, hass: HomeAssistant, repo: str, component_id: str, ref: str
    ) -> None:
        """
        Download the repo archive for `ref` and extract
        custom_components/<component_id>/ into HA's config directory.

        Tries /archive/refs/heads/<ref>.zip first (branch),
        then /archive/refs/tags/<ref>.zip (tag/release).
        """
        content = await self._download_archive(repo, ref)

        dest_dir = hass.config.path("custom_components", component_id)
        await hass.async_add_executor_job(
            self._extract_component, content, component_id, dest_dir
        )

    async def _download_archive(self, repo: str, ref: str) -> bytes:
        """Download zip archive, trying branch URL then tag URL."""
        urls = [
            f"https://github.com/{repo}/archive/refs/heads/{ref}.zip",
            f"https://github.com/{repo}/archive/refs/tags/{ref}.zip",
        ]
        for url in urls:
            async with self._session.get(
                url, headers=self._headers(), allow_redirects=True
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
        raise RuntimeError(
            f"Could not download archive for {repo}@{ref} "
            f"(tried branch and tag URLs)"
        )

    @staticmethod
    def _extract_component(content: bytes, component_id: str, dest_dir: str) -> None:
        """Extract custom_components/<component_id>/ from zip to dest_dir (blocking)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = os.path.join(tmp_dir, "repo.zip")
            with open(zip_path, "wb") as f:
                f.write(content)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_dir)

            # GitHub archives have a single top-level directory
            extracted_roots = [
                d for d in os.listdir(tmp_dir)
                if os.path.isdir(os.path.join(tmp_dir, d)) and d != "__MACOSX"
            ]
            if not extracted_roots:
                raise RuntimeError("No extracted directory found in archive")

            source_dir = os.path.join(
                tmp_dir, extracted_roots[0], "custom_components", component_id
            )
            if not os.path.isdir(source_dir):
                raise RuntimeError(
                    f"custom_components/{component_id}/ not found in archive"
                )

            if os.path.exists(dest_dir):
                shutil.rmtree(dest_dir)
            shutil.copytree(source_dir, dest_dir)

    async def uninstall(self, hass: HomeAssistant, component_id: str) -> None:
        """Remove custom_components/<component_id>/ from HA config (blocking-safe)."""
        dest_dir = hass.config.path("custom_components", component_id)
        await hass.async_add_executor_job(self._remove_dir, dest_dir)

    @staticmethod
    def _remove_dir(path: str) -> None:
        if os.path.isdir(path):
            shutil.rmtree(path)
            _LOGGER.info("Uninstalled component at %s", path)

    # ------------------------------------------------------------------
    # Token validation
    # ------------------------------------------------------------------

    async def validate_token(self) -> bool:
        """Return True if the token is valid (or no token is set)."""
        if not self._token:
            return True  # Public-only mode — always valid
        async with self._session.get(
            f"{_GITHUB_API}/user", headers=self._headers()
        ) as resp:
            return resp.status == 200
