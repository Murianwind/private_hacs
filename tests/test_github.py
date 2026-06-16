"""
tests/test_github.py
GitHub API 클라이언트 단위 테스트

Given/When/Then(BDD Gherkin) 형식으로 작성.
모든 HTTP 호출은 aiohttp.ClientSession을 목업하여 실제 네트워크 없이 실행.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

from homeassistant.exceptions import ConfigEntryAuthFailed

# 테스트 대상
# sys.path는 conftest.py에서 설정됩니다.

from custom_components.private_hacs.github import GitHubClient, GitHubAuthError


# ──────────────────────────────────────────────
# 헬퍼: HTTP 응답 목업
# ──────────────────────────────────────────────

def _mock_response(status: int, json_data=None):
    """aiohttp 응답 목업 — async context manager 지원."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or [])
    resp.read = AsyncMock(return_value=b"")

    @asynccontextmanager
    async def _cm(*args, **kwargs):
        yield resp

    return _cm


def _make_client(responses: list):
    """순서대로 responses를 반환하는 GitHubClient 생성."""
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
        yield resp

    session.get = _get
    return GitHubClient(token="test_token", session=session)


RELEASES_WITH_MAIN = [
    {"tag_name": "v2.0.0", "target_commitish": "main", "html_url": "https://github.com/x/releases/tag/v2.0.0",
     "body": "release note", "published_at": "2024-01-01T00:00:00Z", "prerelease": False, "name": "v2.0.0"},
    {"tag_name": "v1.0.0", "target_commitish": "main", "html_url": "https://github.com/x/releases/tag/v1.0.0",
     "body": "", "published_at": "2023-01-01T00:00:00Z", "prerelease": False, "name": "v1.0.0"},
]

RELEASES_WITH_TEST = [
    {"tag_name": "v2.0.0-test", "target_commitish": "test",
     "html_url": "https://github.com/x/releases/tag/v2.0.0-test",
     "body": "", "published_at": "2024-01-02T00:00:00Z", "prerelease": True, "name": "v2.0.0-test"},
    {"tag_name": "v2.0.0", "target_commitish": "main",
     "html_url": "https://github.com/x/releases/tag/v2.0.0",
     "body": "", "published_at": "2024-01-01T00:00:00Z", "prerelease": False, "name": "v2.0.0"},
]

SHA_MAIN = "aaabbbccc111"
SHA_TEST = "dddeeefff222"

BRANCH_MAIN_RESP = {"commit": {"sha": SHA_MAIN}, "name": "main"}
BRANCH_TEST_RESP = {"commit": {"sha": SHA_TEST}, "name": "test"}


# ══════════════════════════════════════════════════════════════════════
# 1. 릴리즈가 있는 저장소 — main 브랜치 (릴리즈 추적)
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_resolve_latest__given_repo_with_releases__when_main_branch__then_returns_release_info():
    """
    Given: main 브랜치 대상 릴리즈가 있는 저장소
    When:  resolve_latest(branch="main") 호출
    Then:  type="release", version=태그명, release_url 포함 반환
    """
    client = _make_client([(200, RELEASES_WITH_MAIN)])
    result = await client.resolve_latest("Murianwind/private_hacs", "private_hacs", "main")

    assert result is not None
    assert result["type"] == "release"
    assert result["version"] == "v2.0.0"
    assert "releases/tag/v2.0.0" in result["release_url"]
    assert result["commit_sha"] is None


@pytest.mark.asyncio
async def test_resolve_latest__given_repo_with_mixed_releases__when_test_branch__then_returns_only_test_release():
    """
    Given: main + test 브랜치 각각 대상 릴리즈가 있는 저장소
    When:  resolve_latest(branch="test") 호출
    Then:  test 브랜치 릴리즈만 반환 (main 릴리즈 간섭 없음)
    """
    client = _make_client([(200, RELEASES_WITH_TEST)])
    result = await client.resolve_latest("Murianwind/private_hacs", "private_hacs", "test")

    assert result is not None
    assert result["type"] == "release"
    assert result["version"] == "v2.0.0-test"


# ══════════════════════════════════════════════════════════════════════
# 2. 릴리즈 없는 저장소 — 브랜치 HEAD 커밋 추적
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_resolve_latest__given_repo_without_releases_and_tags__when_main_branch__then_returns_branch_commit():
    """
    Given: 릴리즈도 태그도 없는 저장소
    When:  resolve_latest(branch="main") 호출
    Then:  type="branch", commit_sha 포함 반환
    """
    client = _make_client([
        (200, []),           # 릴리즈 없음
        (200, []),           # 태그 없음
        (200, BRANCH_MAIN_RESP),  # 브랜치 HEAD
    ])
    # _get_remote_manifest_version 목업
    client._get_remote_manifest_version = AsyncMock(return_value=None)

    result = await client.resolve_latest("Murianwind/private_hacs", "private_hacs", "main")

    assert result is not None
    assert result["type"] == "branch"
    assert result["commit_sha"] == SHA_MAIN
    assert "commits/main" in result["release_url"]


@pytest.mark.asyncio
async def test_resolve_branch_latest__given_any_repo__when_test_branch__then_returns_branch_head_sha():
    """
    Given: 릴리즈 존재 여부와 무관한 저장소
    When:  resolve_branch_latest(branch="test") 호출 (커밋 추적 모드)
    Then:  test 브랜치 HEAD SHA 반환
    """
    client = _make_client([(200, BRANCH_TEST_RESP)])
    client._get_remote_manifest_version = AsyncMock(return_value=None)

    result = await client.resolve_branch_latest("Murianwind/private_hacs", "private_hacs", "test")

    assert result is not None
    assert result["type"] == "branch"
    assert result["commit_sha"] == SHA_TEST
    assert "commits/test" in result["release_url"]


# ══════════════════════════════════════════════════════════════════════
# 3. 브랜치 간 릴리즈 간섭 방지
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_resolve_latest__given_only_main_releases__when_test_branch__then_falls_through_to_commit():
    """
    Given: main 브랜치 대상 릴리즈만 있는 저장소
    When:  resolve_latest(branch="test") 호출
    Then:  main 릴리즈 무시 → 태그 → 브랜치 HEAD 순 fallthrough
    """
    client = _make_client([
        (200, RELEASES_WITH_MAIN),  # main 릴리즈만 존재
        (200, []),                  # 태그 없음
        (200, BRANCH_TEST_RESP),    # test HEAD
    ])
    client._get_remote_manifest_version = AsyncMock(return_value=None)

    result = await client.resolve_latest("Murianwind/private_hacs", "private_hacs", "test")

    assert result is not None
    assert result["type"] == "branch"
    assert result["commit_sha"] == SHA_TEST


# ══════════════════════════════════════════════════════════════════════
# 4. 인증 실패 (401)
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_resolve_latest__given_invalid_token__when_called__then_raises_auth_error():
    """
    Given: 만료된 GitHub 토큰
    When:  resolve_latest 호출
    Then:  GitHubAuthError(ConfigEntryAuthFailed) 발생
    """
    client = _make_client([(401, {})])

    with pytest.raises(GitHubAuthError):
        await client.resolve_latest("Murianwind/private_hacs", "private_hacs", "main")


@pytest.mark.asyncio
async def test_resolve_branch_latest__given_invalid_token__when_called__then_raises_auth_error():
    """
    Given: 만료된 GitHub 토큰
    When:  resolve_branch_latest 호출
    Then:  GitHubAuthError 발생
    """
    client = _make_client([(401, {})])

    with pytest.raises(GitHubAuthError):
        await client.resolve_branch_latest("Murianwind/private_hacs", "private_hacs", "main")


# ══════════════════════════════════════════════════════════════════════
# 5. Rate Limit (403)
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_resolve_latest__given_rate_limited__when_called__then_returns_none_immediately():
    """
    Given: GitHub API Rate Limit 초과 (403)
    When:  resolve_latest 호출
    Then:  None 반환 (태그/브랜치 추가 호출 없음)
    """
    client = _make_client([(403, {})])
    result = await client.resolve_latest("Murianwind/private_hacs", "private_hacs", "main")

    assert result is None


# ══════════════════════════════════════════════════════════════════════
# 6. 저장소 없음 (404)
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_resolve_latest__given_nonexistent_repo__when_called__then_returns_none():
    """
    Given: 존재하지 않는 저장소
    When:  resolve_latest 호출
    Then:  None 반환 + 경고 로그
    """
    client = _make_client([
        (404, {}),  # 릴리즈 없음
        (404, {}),  # 태그 없음
        (404, {}),  # 브랜치 없음
    ])

    result = await client.resolve_latest("Murianwind/nonexistent", "nonexistent", "main")

    assert result is None


# ══════════════════════════════════════════════════════════════════════
# 7. 태그만 있는 저장소
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_resolve_latest__given_repo_with_tags_only__when_called__then_returns_tag_info():
    """
    Given: 릴리즈는 없고 태그만 있는 저장소
    When:  resolve_latest 호출
    Then:  type="tag", 최신 태그명 반환
    """
    client = _make_client([
        (200, []),                          # 릴리즈 없음
        (200, [{"name": "v1.5.0"}, {"name": "v1.0.0"}]),  # 태그 있음
    ])

    result = await client.resolve_latest("Murianwind/private_hacs", "private_hacs", "main")

    assert result is not None
    assert result["type"] == "tag"
    assert result["version"] == "v1.5.0"


# ══════════════════════════════════════════════════════════════════════
# 8. get_releases — target_commitish 포함 반환
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_releases__given_releases_exist__when_called__then_returns_with_target_commitish():
    """
    Given: 여러 릴리즈가 있는 저장소
    When:  get_releases 호출
    Then:  tag_name, target_commitish 포함한 목록 반환
    """
    client = _make_client([(200, RELEASES_WITH_TEST)])

    releases = await client.get_releases("Murianwind/private_hacs")

    assert len(releases) == 2
    assert releases[0]["tag_name"] == "v2.0.0-test"
    assert releases[0]["target_commitish"] == "test"
    assert releases[1]["tag_name"] == "v2.0.0"
    assert releases[1]["target_commitish"] == "main"


# ══════════════════════════════════════════════════════════════════════
# 9. get_repo_info — 인증 실패
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_repo_info__given_invalid_token__when_called__then_raises_auth_error():
    """
    Given: 만료된 GitHub 토큰
    When:  get_repo_info 호출
    Then:  GitHubAuthError 발생
    """
    client = _make_client([(401, {})])

    with pytest.raises(GitHubAuthError):
        await client.get_repo_info("Murianwind/private_hacs")


@pytest.mark.asyncio
async def test_get_repo_info__given_valid_token__when_called__then_returns_repo_data():
    """
    Given: 유효한 토큰, 존재하는 저장소
    When:  get_repo_info 호출
    Then:  저장소 메타데이터 반환
    """
    repo_data = {
        "name": "private_hacs",
        "description": "Private HACS",
        "default_branch": "main",
        "full_name": "Murianwind/private_hacs",
    }
    client = _make_client([(200, repo_data)])

    result = await client.get_repo_info("Murianwind/private_hacs")

    assert result is not None
    assert result["name"] == "private_hacs"
    assert result["default_branch"] == "main"
