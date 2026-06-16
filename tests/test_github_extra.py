"""
tests/test_github_extra.py
GitHubClient 추가 메서드 테스트 — Given/When/Then(BDD) 형식

get_branches, get_readme, get_releases, download_and_install,
_extract_component, uninstall, validate_token 커버리지 확보.
"""
from __future__ import annotations

import base64
import io
import os
import zipfile
import tempfile
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.private_hacs.github import GitHubClient, GitHubAuthError


def _make_client(responses: list):
    """순서대로 HTTP 응답을 반환하는 GitHubClient."""
    session = MagicMock()
    call_count = [0]

    @asynccontextmanager
    async def _get(*args, **kwargs):
        idx = call_count[0]
        call_count[0] += 1
        status, data = responses[idx] if idx < len(responses) else (404, {})
        resp = MagicMock()
        resp.status = status
        resp.json = AsyncMock(return_value=data)
        resp.read = AsyncMock(return_value=data if isinstance(data, bytes) else b"")
        yield resp

    session.get = _get
    return GitHubClient(token="test_token", session=session)


# ══════════════════════════════════════════════════════════════════════
# get_branches
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_branches__given_valid_repo__when_called__then_returns_branch_names():
    """
    Given: 브랜치 목록 응답 있음
    When:  get_branches 호출
    Then:  브랜치 이름 목록 반환
    """
    client = _make_client([(200, [{"name": "main"}, {"name": "test"}, {"name": "dev"}])])
    result = await client.get_branches("Murianwind/private_hacs")
    assert result == ["main", "test", "dev"]


@pytest.mark.asyncio
async def test_get_branches__given_api_error__when_called__then_returns_empty_list():
    """
    Given: API 오류 (404)
    When:  get_branches 호출
    Then:  빈 목록 반환
    """
    client = _make_client([(404, {})])
    result = await client.get_branches("Murianwind/private_hacs")
    assert result == []


# ══════════════════════════════════════════════════════════════════════
# get_readme
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_readme__given_readme_exists__when_called__then_returns_decoded_content():
    """
    Given: README가 base64로 인코딩된 응답
    When:  get_readme 호출
    Then:  디코딩된 텍스트 반환
    """
    content = "# Private HACS\n테스트 README"
    encoded = base64.b64encode(content.encode()).decode()
    client = _make_client([(200, {"encoding": "base64", "content": encoded})])
    result = await client.get_readme("Murianwind/private_hacs", "main")
    assert result == content


@pytest.mark.asyncio
async def test_get_readme__given_no_readme__when_called__then_returns_none():
    """
    Given: README 없음 (404)
    When:  get_readme 호출
    Then:  None 반환
    """
    client = _make_client([(404, {})])
    result = await client.get_readme("Murianwind/private_hacs", "main")
    assert result is None


@pytest.mark.asyncio
async def test_get_readme__given_auth_error__when_called__then_returns_none_and_logs():
    """
    Given: 인증 실패 (401)
    When:  get_readme 호출
    Then:  None 반환 (예외 없이)
    """
    client = _make_client([(401, {})])
    result = await client.get_readme("Murianwind/private_hacs", "main")
    assert result is None


# ══════════════════════════════════════════════════════════════════════
# get_releases
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_releases__given_releases_exist__when_called__then_returns_list():
    """
    Given: 릴리즈 목록 응답
    When:  get_releases 호출
    Then:  tag_name, target_commitish 포함한 목록 반환
    """
    releases = [
        {"tag_name": "v2.0.0", "name": "v2.0.0", "published_at": "2024-01-01T00:00:00Z",
         "html_url": "https://github.com/x/releases/tag/v2.0.0",
         "prerelease": False, "target_commitish": "main"},
        {"tag_name": "v1.0.0", "name": "v1.0.0", "published_at": "2023-01-01T00:00:00Z",
         "html_url": "https://github.com/x/releases/tag/v1.0.0",
         "prerelease": False, "target_commitish": "main"},
    ]
    client = _make_client([(200, releases)])
    result = await client.get_releases("Murianwind/private_hacs")
    assert len(result) == 2
    assert result[0]["tag_name"] == "v2.0.0"
    assert result[0]["target_commitish"] == "main"


@pytest.mark.asyncio
async def test_get_releases__given_no_releases__when_called__then_returns_empty():
    """
    Given: 릴리즈 없음
    When:  get_releases 호출
    Then:  빈 목록 반환
    """
    client = _make_client([(200, [])])
    result = await client.get_releases("Murianwind/private_hacs")
    assert result == []


@pytest.mark.asyncio
async def test_get_releases__given_auth_error__when_called__then_returns_empty():
    """
    Given: 인증 실패 (401)
    When:  get_releases 호출
    Then:  빈 목록 반환 (get_releases는 예외 없이 빈 목록 반환)
    """
    client = _make_client([(401, {})])
    result = await client.get_releases("Murianwind/private_hacs")
    assert result == []


# ══════════════════════════════════════════════════════════════════════
# _extract_component (동기 메서드 직접 테스트)
# ══════════════════════════════════════════════════════════════════════

def _make_test_zip(component_id: str = "private_hacs") -> bytes:
    """테스트용 zip 파일 생성 — GitHub archive 구조 재현."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"repo-main/custom_components/{component_id}/__init__.py", "# test")
        zf.writestr(f"repo-main/custom_components/{component_id}/manifest.json",
                    '{"domain": "private_hacs", "version": "2.0.0"}')
    return buf.getvalue()


def test_extract_component__given_valid_zip__when_extracted__then_files_copied():
    """
    Given: 올바른 GitHub archive zip
    When:  _extract_component 호출
    Then:  custom_components/private_hacs/ 파일이 dest_dir에 복사됨
    """
    with tempfile.TemporaryDirectory() as dest_dir:
        content = _make_test_zip("private_hacs")
        GitHubClient._extract_component(content, "private_hacs", dest_dir)
        assert os.path.isfile(os.path.join(dest_dir, "__init__.py"))
        assert os.path.isfile(os.path.join(dest_dir, "manifest.json"))


def test_extract_component__given_missing_component_dir__when_extracted__then_raises():
    """
    Given: zip 안에 custom_components/wrong_id/ 경로 없음
    When:  _extract_component 호출
    Then:  RuntimeError 발생
    """
    with tempfile.TemporaryDirectory() as dest_dir:
        content = _make_test_zip("private_hacs")
        with pytest.raises(RuntimeError, match="not found in archive"):
            GitHubClient._extract_component(content, "wrong_id", dest_dir)


def test_extract_component__given_existing_dest__when_extracted__then_replaced():
    """
    Given: dest_dir에 이미 파일 존재
    When:  _extract_component 호출
    Then:  기존 파일 삭제 후 새 파일로 교체
    """
    with tempfile.TemporaryDirectory() as base:
        dest_dir = os.path.join(base, "private_hacs")
        os.makedirs(dest_dir)
        old_file = os.path.join(dest_dir, "old_file.py")
        with open(old_file, "w") as f:
            f.write("old")

        content = _make_test_zip("private_hacs")
        GitHubClient._extract_component(content, "private_hacs", dest_dir)

        assert not os.path.isfile(old_file)
        assert os.path.isfile(os.path.join(dest_dir, "__init__.py"))


# ══════════════════════════════════════════════════════════════════════
# download_and_install
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_download_and_install__given_branch_zip__when_installed__then_extract_called():
    """
    Given: 브랜치 zip 다운로드 성공
    When:  download_and_install 호출
    Then:  _extract_component가 executor로 호출됨
    """
    content = _make_test_zip()
    client = _make_client([(200, content)])

    hass = MagicMock()
    hass.config.path = MagicMock(return_value="/tmp/custom_components/private_hacs")
    hass.async_add_executor_job = AsyncMock()

    await client.download_and_install(hass, "Murianwind/private_hacs", "private_hacs", "main")

    hass.async_add_executor_job.assert_called_once()


@pytest.mark.asyncio
async def test_download_and_install__given_both_urls_fail__when_installed__then_raises():
    """
    Given: branch URL + tag URL 모두 실패
    When:  download_and_install 호출
    Then:  RuntimeError 발생
    """
    client = _make_client([(404, b""), (404, b"")])

    hass = MagicMock()
    hass.config.path = MagicMock(return_value="/tmp/custom_components/private_hacs")
    hass.async_add_executor_job = AsyncMock()

    with pytest.raises(RuntimeError, match="Could not download"):
        await client.download_and_install(hass, "Murianwind/private_hacs", "private_hacs", "main")


# ══════════════════════════════════════════════════════════════════════
# uninstall / _remove_dir
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_uninstall__given_installed_component__when_called__then_remove_dir_called():
    """
    Given: 컴포넌트 설치됨
    When:  uninstall 호출
    Then:  _remove_dir이 executor로 호출됨
    """
    client = GitHubClient(token="test", session=MagicMock())
    hass = MagicMock()
    hass.config.path = MagicMock(return_value="/tmp/custom_components/private_hacs")
    hass.async_add_executor_job = AsyncMock()

    await client.uninstall(hass, "private_hacs")

    hass.async_add_executor_job.assert_called_once()


def test_remove_dir__given_existing_dir__when_called__then_removed():
    """
    Given: 디렉토리 존재
    When:  _remove_dir 호출
    Then:  디렉토리 삭제됨
    """
    with tempfile.TemporaryDirectory() as base:
        target = os.path.join(base, "component")
        os.makedirs(target)
        assert os.path.isdir(target)

        GitHubClient._remove_dir(target)

        assert not os.path.isdir(target)


def test_remove_dir__given_nonexistent_dir__when_called__then_no_error():
    """
    Given: 존재하지 않는 경로
    When:  _remove_dir 호출
    Then:  에러 없이 통과
    """
    GitHubClient._remove_dir("/tmp/nonexistent_private_hacs_test_dir")


# ══════════════════════════════════════════════════════════════════════
# validate_token
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_validate_token__given_valid_token__when_called__then_returns_true():
    """
    Given: 유효한 토큰 (200 응답)
    When:  validate_token 호출
    Then:  True 반환
    """
    client = _make_client([(200, {"login": "Murianwind"})])
    result = await client.validate_token()
    assert result is True


@pytest.mark.asyncio
async def test_validate_token__given_invalid_token__when_called__then_returns_false():
    """
    Given: 만료된 토큰 (401 응답)
    When:  validate_token 호출
    Then:  False 반환
    """
    client = _make_client([(401, {})])
    result = await client.validate_token()
    assert result is False


# ══════════════════════════════════════════════════════════════════════
# get_tree / verify_installed_sha — SHA를 모를 때 파일 비교로 확정
# ══════════════════════════════════════════════════════════════════════

class TestGetTree:

    @pytest.mark.asyncio
    async def test_given_valid_ref__when_called__then_returns_path_to_sha_map(self):
        """
        Given: 정상적인 git tree 응답 (custom_components/private_hacs/ 하위 파일들)
        When:  get_tree 호출
        Then:  {경로: blob_sha} 딕셔너리 반환 (blob만, tree/dir 제외)
        """
        tree_response = {
            "tree": [
                {"path": "custom_components", "type": "tree", "sha": "dirsha1"},
                {"path": "custom_components/private_hacs", "type": "tree", "sha": "dirsha2"},
                {"path": "custom_components/private_hacs/__init__.py", "type": "blob", "sha": "blobsha1"},
                {"path": "custom_components/private_hacs/manifest.json", "type": "blob", "sha": "blobsha2"},
            ],
            "truncated": False,
        }
        client = _make_client([(200, tree_response)])
        result = await client.get_tree("Murianwind/private_hacs", "abc123")

        assert result == {
            "custom_components/private_hacs/__init__.py": "blobsha1",
            "custom_components/private_hacs/manifest.json": "blobsha2",
        }

    @pytest.mark.asyncio
    async def test_given_api_error__when_called__then_returns_none(self):
        """
        Given: API 오류 (404 — ref 없음)
        When:  get_tree 호출
        Then:  None 반환
        """
        client = _make_client([(404, {})])
        result = await client.get_tree("Murianwind/private_hacs", "nonexistent")
        assert result is None


class TestGitBlobSha:

    def test_given_known_content__when_hashed__then_matches_git_hash_object(self):
        """
        Given: 알려진 내용 ("test content\n")
        When:  _git_blob_sha 호출
        Then:  실제 git hash-object 결과와 동일한 SHA-1 반환
              (이 값은 `echo -n "test content" | git hash-object --stdin` 등으로 검증 가능한 표준 git blob SHA)
        """
        # "test content\n" 의 잘 알려진 git blob SHA
        content = b"test content\n"
        result = GitHubClient._git_blob_sha(content)
        assert result == "d670460b4b4aece5915caf5c68d12f560a9fe3e4"
        assert len(result) == 40

    def test_given_empty_content__when_hashed__then_returns_known_empty_blob_sha(self):
        """
        Given: 빈 파일
        When:  _git_blob_sha 호출
        Then:  git의 잘 알려진 빈 blob SHA 반환
        """
        result = GitHubClient._git_blob_sha(b"")
        assert result == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


class TestVerifyInstalledSha:

    def _make_client_for_verify(self, tree_response):
        return _make_client([(200, tree_response)])

    @pytest.mark.asyncio
    async def test_given_local_files_match_remote_tree__when_verified__then_returns_true(self):
        """
        Given: 로컬 파일 내용이 원격 HEAD의 blob SHA와 정확히 일치
        When:  verify_installed_sha 호출
        Then:  True 반환 (SHA를 안전하게 확정할 수 있음)
        """
        content_init = b"# init\n"
        content_manifest = b'{"domain": "private_hacs"}\n'
        sha_init = GitHubClient._git_blob_sha(content_init)
        sha_manifest = GitHubClient._git_blob_sha(content_manifest)

        tree_response = {
            "tree": [
                {"path": "custom_components/private_hacs/__init__.py", "type": "blob", "sha": sha_init},
                {"path": "custom_components/private_hacs/manifest.json", "type": "blob", "sha": sha_manifest},
            ],
            "truncated": False,
        }
        client = self._make_client_for_verify(tree_response)

        with tempfile.TemporaryDirectory() as base:
            comp_dir = os.path.join(base, "private_hacs")
            os.makedirs(comp_dir)
            with open(os.path.join(comp_dir, "__init__.py"), "wb") as f:
                f.write(content_init)
            with open(os.path.join(comp_dir, "manifest.json"), "wb") as f:
                f.write(content_manifest)

            hass = MagicMock()
            hass.config.path = MagicMock(return_value=comp_dir)
            hass.async_add_executor_job = AsyncMock(
                side_effect=lambda fn, *a: fn(*a)
            )

            result = await client.verify_installed_sha(
                hass, "Murianwind/private_hacs", "private_hacs", "abc123"
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_given_local_file_differs__when_verified__then_returns_false(self):
        """
        Given: 로컬 파일 내용이 원격 HEAD와 다름 (로컬이 더 오래된 버전)
        When:  verify_installed_sha 호출
        Then:  False 반환 (SHA를 확정할 수 없음 — 안전하게 모름 상태 유지)
        """
        remote_sha = "remoteblobsha1234567890"
        tree_response = {
            "tree": [
                {"path": "custom_components/private_hacs/__init__.py", "type": "blob", "sha": remote_sha},
            ],
            "truncated": False,
        }
        client = self._make_client_for_verify(tree_response)

        with tempfile.TemporaryDirectory() as base:
            comp_dir = os.path.join(base, "private_hacs")
            os.makedirs(comp_dir)
            with open(os.path.join(comp_dir, "__init__.py"), "wb") as f:
                f.write(b"# old content, different from remote\n")

            hass = MagicMock()
            hass.config.path = MagicMock(return_value=comp_dir)
            hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))

            result = await client.verify_installed_sha(
                hass, "Murianwind/private_hacs", "private_hacs", "abc123"
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_given_local_file_missing__when_verified__then_returns_false(self):
        """
        Given: 원격 트리에는 있는 파일이 로컬 디스크에 없음
        When:  verify_installed_sha 호출
        Then:  False 반환
        """
        tree_response = {
            "tree": [
                {"path": "custom_components/private_hacs/__init__.py", "type": "blob", "sha": "somesha"},
                {"path": "custom_components/private_hacs/missing_file.py", "type": "blob", "sha": "anothersha"},
            ],
            "truncated": False,
        }
        client = self._make_client_for_verify(tree_response)

        with tempfile.TemporaryDirectory() as base:
            comp_dir = os.path.join(base, "private_hacs")
            os.makedirs(comp_dir)
            # __init__.py만 만들고 missing_file.py는 만들지 않음
            with open(os.path.join(comp_dir, "__init__.py"), "wb") as f:
                f.write(b"x")

            hass = MagicMock()
            hass.config.path = MagicMock(return_value=comp_dir)
            hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))

            result = await client.verify_installed_sha(
                hass, "Murianwind/private_hacs", "private_hacs", "abc123"
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_given_get_tree_fails__when_verified__then_returns_false(self):
        """
        Given: get_tree가 None 반환 (API 오류)
        When:  verify_installed_sha 호출
        Then:  False 반환 (검증 불가 — 모름 상태 유지)
        """
        client = _make_client([(404, {})])
        hass = MagicMock()

        result = await client.verify_installed_sha(
            hass, "Murianwind/private_hacs", "private_hacs", "abc123"
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_given_no_files_for_component__when_verified__then_returns_false(self):
        """
        Given: 원격 트리에 해당 component_id 경로가 전혀 없음
        When:  verify_installed_sha 호출
        Then:  False 반환
        """
        tree_response = {
            "tree": [
                {"path": "README.md", "type": "blob", "sha": "somesha"},
            ],
            "truncated": False,
        }
        client = self._make_client_for_verify(tree_response)
        hass = MagicMock()

        result = await client.verify_installed_sha(
            hass, "Murianwind/private_hacs", "private_hacs", "abc123"
        )
        assert result is False
