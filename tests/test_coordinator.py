"""
tests/test_coordinator.py
PrivateHacsCoordinator 단위 테스트

coordinator._compute_has_update, _resolve_installed_version,
_async_update_data 핵심 로직을 검증한다.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

# sys.path는 conftest.py에서 설정됩니다.

from coordinator import (
    PrivateHacsCoordinator,
    make_entry_key,
    UPDATE_MODE_RELEASE,
    UPDATE_MODE_COMMIT,
    _strip_v,
)
from conftest import make_hass, make_store, make_repo_item, make_github_client
from github import GitHubAuthError


# ══════════════════════════════════════════════════════════════════════
# _strip_v 유틸리티
# ══════════════════════════════════════════════════════════════════════

def test_strip_v__given_version_with_v_prefix__when_called__then_removes_prefix():
    """
    Given: 'v' 접두사가 있는 버전 문자열
    When:  _strip_v 호출
    Then:  'v' 없는 버전 반환
    """
    assert _strip_v("v2.0.0") == "2.0.0"
    assert _strip_v("2.0.0") == "2.0.0"
    assert _strip_v("v1.0") == "1.0"
    assert _strip_v("") == ""


# ══════════════════════════════════════════════════════════════════════
# _compute_has_update
# ══════════════════════════════════════════════════════════════════════

def _make_coordinator():
    hass = make_hass()
    store = make_store()
    github = make_github_client()
    coord = PrivateHacsCoordinator(hass=hass, repos=[], github=github, store=store)
    return coord


class TestComputeHasUpdate:

    def test_given_release_type_and_version_matches__when_computed__then_no_update(self):
        """
        Given: 릴리즈 타입, 설치 버전 == 최신 버전
        When:  _compute_has_update 호출
        Then:  False 반환
        """
        coord = _make_coordinator()
        latest = {"type": "release", "version": "v2.0.0"}
        assert coord._compute_has_update(latest, "2.0.0", None) is False

    def test_given_release_type_and_version_differs__when_computed__then_has_update(self):
        """
        Given: 릴리즈 타입, 설치 버전 != 최신 버전
        When:  _compute_has_update 호출
        Then:  True 반환
        """
        coord = _make_coordinator()
        latest = {"type": "release", "version": "v2.1.0"}
        assert coord._compute_has_update(latest, "2.0.0", None) is True

    def test_given_release_type_with_v_prefix_mismatch__when_computed__then_normalizes_correctly(self):
        """
        Given: 릴리즈 타입, installed='3.0.7' vs latest='v3.0.7' (v 접두사 불일치)
        When:  _compute_has_update 호출
        Then:  False (같은 버전으로 정규화)
        """
        coord = _make_coordinator()
        latest = {"type": "release", "version": "v3.0.7"}
        assert coord._compute_has_update(latest, "3.0.7", None) is False

    def test_given_branch_type_and_sha_matches__when_computed__then_no_update(self):
        """
        Given: 브랜치 타입, 설치 SHA == 최신 SHA
        When:  _compute_has_update 호출
        Then:  False 반환
        """
        coord = _make_coordinator()
        sha = "abc123"
        latest = {"type": "branch", "commit_sha": sha, "remote_manifest_version": None}
        assert coord._compute_has_update(latest, "2.0.0", sha) is False

    def test_given_branch_type_and_sha_differs__when_computed__then_has_update(self):
        """
        Given: 브랜치 타입, 설치 SHA != 최신 SHA
        When:  _compute_has_update 호출
        Then:  True 반환
        """
        coord = _make_coordinator()
        latest = {"type": "branch", "commit_sha": "newsha999", "remote_manifest_version": None}
        assert coord._compute_has_update(latest, "2.0.0", "oldsha111") is True

    def test_given_branch_type_and_no_installed_sha__when_computed__then_no_update(self):
        """
        Given: 브랜치 타입, installed_commit_sha 없음 (SHA 미저장)
        When:  _compute_has_update 호출
        Then:  False (SHA 없이 비교 불가)
        """
        coord = _make_coordinator()
        latest = {"type": "branch", "commit_sha": "newsha999", "remote_manifest_version": None}
        assert coord._compute_has_update(latest, "2.0.0", None) is False

    def test_given_branch_type_with_manifest_version_differs__when_computed__then_has_update(self):
        """
        Given: 브랜치 타입, remote_manifest_version != installed_version
        When:  _compute_has_update 호출
        Then:  True 반환
        """
        coord = _make_coordinator()
        latest = {"type": "branch", "commit_sha": None, "remote_manifest_version": "2.2.0"}
        assert coord._compute_has_update(latest, "2.1.0", None) is True

    def test_given_no_installed_version__when_computed__then_no_update(self):
        """
        Given: installed_version 없음 (미설치 상태)
        When:  _compute_has_update 호출
        Then:  False 반환
        """
        coord = _make_coordinator()
        latest = {"type": "release", "version": "v2.0.0"}
        assert coord._compute_has_update(latest, None, None) is False

    def test_given_latest_none__when_computed__then_no_update(self):
        """
        Given: latest 없음 (API 실패 상태)
        When:  _compute_has_update 호출
        Then:  False 반환
        """
        coord = _make_coordinator()
        assert coord._compute_has_update(None, "2.0.0", None) is False


# ══════════════════════════════════════════════════════════════════════
# _resolve_installed_version
# ══════════════════════════════════════════════════════════════════════

class TestResolveInstalledVersion:

    @pytest.mark.asyncio
    async def test_given_version_in_store__when_active_branch__then_returns_store_version(self):
        """
        Given: store에 installed_version 기록 있음
        When:  활성 브랜치의 _resolve_installed_version 호출
        Then:  store의 버전 반환, source="store"
        """
        hass = make_hass()
        store = make_store({("private_hacs", "main"): {"installed_version": "2.0.0"}})
        coord = PrivateHacsCoordinator(hass=hass, repos=[], github=AsyncMock(), store=store)

        version, source = await coord._resolve_installed_version("private_hacs", "main", active=True)

        assert version == "2.0.0"
        assert source == "store"

    @pytest.mark.asyncio
    async def test_given_no_store__when_inactive_branch__then_manifest_not_read(self):
        """
        Given: store에 기록 없음, 비활성 브랜치
        When:  _resolve_installed_version 호출
        Then:  manifest.json 읽기 차단 → None, source="none"
        """
        hass = make_hass()
        store = make_store()
        coord = PrivateHacsCoordinator(hass=hass, repos=[], github=AsyncMock(), store=store)

        version, source = await coord._resolve_installed_version(
            "private_hacs", "test", active=False
        )

        assert version is None
        assert source == "none"
        # executor 호출 없어야 함 (manifest 읽기 차단)
        hass.async_add_executor_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_given_no_store_but_manifest_exists__when_active_branch__then_returns_manifest_version(self):
        """
        Given: store 기록 없음, 디스크에 manifest.json 있음, 활성 브랜치
        When:  _resolve_installed_version 호출
        Then:  manifest 버전 반환, source="manifest"
        """
        hass = make_hass()
        hass.async_add_executor_job = AsyncMock(return_value="2.1.0")
        store = make_store()
        coord = PrivateHacsCoordinator(hass=hass, repos=[], github=AsyncMock(), store=store)

        with patch.object(coord, "_read_manifest_version_sync", return_value="2.1.0"):
            hass.async_add_executor_job = AsyncMock(return_value="2.1.0")
            version, source = await coord._resolve_installed_version(
                "private_hacs", "main", active=True
            )

        assert version == "2.1.0"
        assert source == "manifest"


# ══════════════════════════════════════════════════════════════════════
# _async_update_data — 릴리즈 추적 (update_mode=release)
# ══════════════════════════════════════════════════════════════════════

class TestAsyncUpdateDataRelease:

    @pytest.mark.asyncio
    async def test_given_repo_with_release__when_polled__then_data_contains_release_info(self):
        """
        Given: 릴리즈 있는 저장소, update_mode=release
        When:  _async_update_data 실행
        Then:  latest.type="release", version 포함 데이터 반환
        """
        hass = make_hass()
        store = make_store()
        github = AsyncMock()
        github.resolve_latest = AsyncMock(return_value={
            "type": "release", "version": "v2.0.0",
            "download_ref": "v2.0.0",
            "release_url": "https://github.com/x/releases/tag/v2.0.0",
            "release_summary": "노트", "commit_sha": None,
            "remote_manifest_version": None,
        })

        repos = [make_repo_item(update_mode="release")]
        coord = PrivateHacsCoordinator(hass=hass, repos=repos, github=github, store=store)

        result = await coord._async_update_data()

        entry_key = make_entry_key("private_hacs", "main")
        assert entry_key in result
        assert result[entry_key]["latest"]["type"] == "release"
        assert result[entry_key]["latest"]["version"] == "v2.0.0"

    @pytest.mark.asyncio
    async def test_given_installed_version_and_new_release__when_polled__then_has_update_true(self):
        """
        Given: 설치 버전 2.0.0, 최신 릴리즈 v2.1.0
        When:  _async_update_data 실행
        Then:  has_update=True
        """
        hass = make_hass()
        store = make_store({("private_hacs", "main"): {"installed_version": "2.0.0"}})
        github = AsyncMock()
        github.resolve_latest = AsyncMock(return_value={
            "type": "release", "version": "v2.1.0",
            "download_ref": "v2.1.0",
            "release_url": "https://github.com/x/releases/tag/v2.1.0",
            "release_summary": None, "commit_sha": None,
            "remote_manifest_version": None,
        })

        repos = [make_repo_item(update_mode="release")]
        coord = PrivateHacsCoordinator(hass=hass, repos=repos, github=github, store=store)

        result = await coord._async_update_data()
        entry_key = make_entry_key("private_hacs", "main")

        assert result[entry_key]["has_update"] is True

    @pytest.mark.asyncio
    async def test_given_installed_version_matches_release__when_polled__then_has_update_false(self):
        """
        Given: 설치 버전 2.0.0, 최신 릴리즈 v2.0.0 (동일)
        When:  _async_update_data 실행
        Then:  has_update=False
        """
        hass = make_hass()
        store = make_store({("private_hacs", "main"): {"installed_version": "2.0.0"}})
        github = AsyncMock()
        github.resolve_latest = AsyncMock(return_value={
            "type": "release", "version": "v2.0.0",
            "download_ref": "v2.0.0",
            "release_url": "https://github.com/x/releases/tag/v2.0.0",
            "release_summary": None, "commit_sha": None,
            "remote_manifest_version": None,
        })

        repos = [make_repo_item(update_mode="release")]
        coord = PrivateHacsCoordinator(hass=hass, repos=repos, github=github, store=store)

        result = await coord._async_update_data()
        entry_key = make_entry_key("private_hacs", "main")

        assert result[entry_key]["has_update"] is False


# ══════════════════════════════════════════════════════════════════════
# _async_update_data — 커밋 추적 (update_mode=commit)
# ══════════════════════════════════════════════════════════════════════

class TestAsyncUpdateDataCommit:

    @pytest.mark.asyncio
    async def test_given_repo_with_commit_mode__when_polled__then_uses_resolve_branch_latest(self):
        """
        Given: update_mode=commit 브랜치
        When:  _async_update_data 실행
        Then:  resolve_branch_latest 호출 (resolve_latest 아님)
        """
        hass = make_hass()
        store = make_store()
        github = AsyncMock()
        github.resolve_branch_latest = AsyncMock(return_value={
            "type": "branch", "version": "abc1234",
            "download_ref": "test",
            "release_url": "https://github.com/x/commits/test",
            "release_summary": None, "commit_sha": "abc123400000",
            "remote_manifest_version": None,
        })

        repos = [make_repo_item(branch="test", update_mode="commit")]
        coord = PrivateHacsCoordinator(hass=hass, repos=repos, github=github, store=store)

        await coord._async_update_data()

        github.resolve_branch_latest.assert_called_once_with(
            "Murianwind/private_hacs", "private_hacs", "test"
        )
        github.resolve_latest.assert_not_called()

    @pytest.mark.asyncio
    async def test_given_new_commit_sha__when_polled__then_has_update_true(self):
        """
        Given: 설치 SHA=old, 최신 SHA=new
        When:  _async_update_data 실행 (commit 모드)
        Then:  has_update=True
        """
        hass = make_hass()
        store = make_store({
            ("private_hacs", "test"): {
                "installed_version": "2.0.0",
                "installed_commit_sha": "oldsha111",
            }
        })
        github = AsyncMock()
        github.resolve_branch_latest = AsyncMock(return_value={
            "type": "branch", "version": "newsha",
            "download_ref": "test",
            "release_url": "https://github.com/x/commits/test",
            "release_summary": None, "commit_sha": "newsha999",
            "remote_manifest_version": None,
        })

        repos = [make_repo_item(branch="test", update_mode="commit")]
        coord = PrivateHacsCoordinator(hass=hass, repos=repos, github=github, store=store)

        result = await coord._async_update_data()
        entry_key = make_entry_key("private_hacs", "test")

        assert result[entry_key]["has_update"] is True

    @pytest.mark.asyncio
    async def test_given_same_commit_sha__when_polled__then_has_update_false(self):
        """
        Given: 설치 SHA == 최신 SHA
        When:  _async_update_data 실행 (commit 모드)
        Then:  has_update=False
        """
        hass = make_hass()
        sha = "abc123abc123"
        store = make_store({
            ("private_hacs", "test"): {
                "installed_version": "2.0.0",
                "installed_commit_sha": sha,
            }
        })
        github = AsyncMock()
        github.resolve_branch_latest = AsyncMock(return_value={
            "type": "branch", "version": "abc123",
            "download_ref": "test",
            "release_url": "https://github.com/x/commits/test",
            "release_summary": None, "commit_sha": sha,
            "remote_manifest_version": None,
        })

        repos = [make_repo_item(branch="test", update_mode="commit")]
        coord = PrivateHacsCoordinator(hass=hass, repos=repos, github=github, store=store)

        result = await coord._async_update_data()
        entry_key = make_entry_key("private_hacs", "test")

        assert result[entry_key]["has_update"] is False


# ══════════════════════════════════════════════════════════════════════
# update_mode 자동 전환 (릴리즈 없는 저장소)
# ══════════════════════════════════════════════════════════════════════

class TestAutoSwitchUpdateMode:

    @pytest.mark.asyncio
    async def test_given_release_mode_but_no_releases__when_polled__then_auto_switches_to_commit(self):
        """
        Given: update_mode=release 이지만 실제 릴리즈 없어 branch 타입 반환
        When:  _async_update_data 실행
        Then:  update_mode가 commit으로 자동 전환, repos 리스트 갱신
        """
        hass = make_hass()
        store = make_store()
        github = AsyncMock()
        github.resolve_latest = AsyncMock(return_value={
            "type": "branch", "version": "abc1234",
            "download_ref": "main",
            "release_url": "https://github.com/x/commits/main",
            "release_summary": None, "commit_sha": "abc123400000",
            "remote_manifest_version": None,
        })

        repo_item = make_repo_item(update_mode="release")
        repos = [repo_item]
        coord = PrivateHacsCoordinator(hass=hass, repos=repos, github=github, store=store)

        result = await coord._async_update_data()
        entry_key = make_entry_key("private_hacs", "main")

        assert result[entry_key]["update_mode"] == UPDATE_MODE_COMMIT
        assert repos[0]["update_mode"] == UPDATE_MODE_COMMIT


# ══════════════════════════════════════════════════════════════════════
# 비활성 브랜치
# ══════════════════════════════════════════════════════════════════════

class TestInactiveBranch:

    @pytest.mark.asyncio
    async def test_given_inactive_branch__when_polled__then_has_update_always_false(self):
        """
        Given: active=False 브랜치, 실제로 업데이트 있음
        When:  _async_update_data 실행
        Then:  has_update=False (비활성 브랜치는 업데이트 알림 없음)
        """
        hass = make_hass()
        store = make_store({
            ("private_hacs", "test"): {"installed_version": "1.0.0"}
        })
        github = AsyncMock()
        github.resolve_latest = AsyncMock(return_value={
            "type": "release", "version": "v2.0.0",
            "download_ref": "v2.0.0",
            "release_url": "https://github.com/x/releases/tag/v2.0.0",
            "release_summary": None, "commit_sha": None,
            "remote_manifest_version": None,
        })

        repos = [make_repo_item(branch="test", active=False, update_mode="release")]
        coord = PrivateHacsCoordinator(hass=hass, repos=repos, github=github, store=store)

        result = await coord._async_update_data()
        entry_key = make_entry_key("private_hacs", "test")

        assert result[entry_key]["has_update"] is False

    @pytest.mark.asyncio
    async def test_given_inactive_branch_no_store__when_polled__then_not_reads_manifest(self):
        """
        Given: active=False, store 기록 없음
        When:  _async_update_data 실행
        Then:  installed_version=None (manifest 자동 감지 차단)
        """
        hass = make_hass()
        store = make_store()
        github = AsyncMock()
        github.resolve_latest = AsyncMock(return_value={
            "type": "release", "version": "v2.0.0",
            "download_ref": "v2.0.0",
            "release_url": "https://github.com/x/releases/tag/v2.0.0",
            "release_summary": None, "commit_sha": None,
            "remote_manifest_version": None,
        })

        repos = [make_repo_item(branch="test", active=False)]
        coord = PrivateHacsCoordinator(hass=hass, repos=repos, github=github, store=store)

        result = await coord._async_update_data()
        entry_key = make_entry_key("private_hacs", "test")

        assert result[entry_key]["installed_version"] is None


# ══════════════════════════════════════════════════════════════════════
# SHA 자동 복구
# ══════════════════════════════════════════════════════════════════════

class TestShaAutoRecovery:

    @pytest.mark.asyncio
    async def test_given_installed_without_sha__when_polled__then_sha_auto_recovered(self):
        """
        Given: installed_version 있음, installed_commit_sha 없음 (구버전 설치)
        When:  _async_update_data 실행 (commit 모드)
        Then:  remote SHA로 installed_commit_sha 자동 복구, store 저장
        """
        hass = make_hass()
        remote_sha = "abc123abc123"
        store = make_store({
            ("private_hacs", "main"): {
                "installed_version": "2.0.0",
                "installed_commit_sha": None,
            }
        })
        github = AsyncMock()
        github.resolve_branch_latest = AsyncMock(return_value={
            "type": "branch", "version": "abc123",
            "download_ref": "main",
            "release_url": "https://github.com/x/commits/main",
            "release_summary": None, "commit_sha": remote_sha,
            "remote_manifest_version": None,
        })

        repos = [make_repo_item(update_mode="commit")]
        coord = PrivateHacsCoordinator(hass=hass, repos=repos, github=github, store=store)

        result = await coord._async_update_data()
        entry_key = make_entry_key("private_hacs", "main")

        assert result[entry_key]["installed_commit_sha"] == remote_sha
        store.async_set_branch.assert_called()


# ══════════════════════════════════════════════════════════════════════
# 인증 실패 전파
# ══════════════════════════════════════════════════════════════════════

class TestAuthFailurePropagation:

    @pytest.mark.asyncio
    async def test_given_auth_error_from_github__when_polled__then_propagates_to_coordinator(self):
        """
        Given: GitHub 401 → GitHubAuthError 발생
        When:  _async_update_data 실행
        Then:  ConfigEntryAuthFailed 전파 (HA 재인증 트리거)
        """
        from homeassistant.exceptions import ConfigEntryAuthFailed

        hass = make_hass()
        store = make_store()
        github = AsyncMock()
        github.resolve_latest = AsyncMock(side_effect=GitHubAuthError("토큰 만료"))

        repos = [make_repo_item()]
        coord = PrivateHacsCoordinator(hass=hass, repos=repos, github=github, store=store)

        with pytest.raises(ConfigEntryAuthFailed):
            await coord._async_update_data()


# ══════════════════════════════════════════════════════════════════════
# 새로고침 시 갱신
# ══════════════════════════════════════════════════════════════════════

class TestRefresh:

    @pytest.mark.asyncio
    async def test_given_new_commit_after_poll__when_polled_again__then_sha_updated(self):
        """
        Given: 1차 폴링 SHA=old, 이후 새 커밋 푸시
        When:  2차 _async_update_data 실행
        Then:  최신 SHA로 갱신, has_update=True
        """
        hass = make_hass()
        store = make_store({
            ("private_hacs", "main"): {
                "installed_version": "2.0.0",
                "installed_commit_sha": "oldsha111",
            }
        })
        github = AsyncMock()

        # 1차: 같은 SHA
        github.resolve_branch_latest = AsyncMock(return_value={
            "type": "branch", "version": "oldsha",
            "download_ref": "main",
            "release_url": "https://github.com/x/commits/main",
            "release_summary": None, "commit_sha": "oldsha111",
            "remote_manifest_version": None,
        })

        repos = [make_repo_item(update_mode="commit")]
        coord = PrivateHacsCoordinator(hass=hass, repos=repos, github=github, store=store)
        result1 = await coord._async_update_data()
        entry_key = make_entry_key("private_hacs", "main")
        assert result1[entry_key]["has_update"] is False

        # 2차: 새 SHA
        github.resolve_branch_latest = AsyncMock(return_value={
            "type": "branch", "version": "newsha",
            "download_ref": "main",
            "release_url": "https://github.com/x/commits/main",
            "release_summary": None, "commit_sha": "newsha999",
            "remote_manifest_version": None,
        })
        result2 = await coord._async_update_data()
        assert result2[entry_key]["has_update"] is True


# ══════════════════════════════════════════════════════════════════════
# 다중 브랜치 — component_id별 캐시
# ══════════════════════════════════════════════════════════════════════

class TestMultiBranch:

    @pytest.mark.asyncio
    async def test_given_two_branches_same_component__when_polled__then_each_tracked_independently(self):
        """
        Given: 동일 component_id의 main(활성) + test(비활성) 브랜치
        When:  _async_update_data 실행
        Then:  각 브랜치 독립 추적, test는 has_update=False 고정
        """
        hass = make_hass()
        store = make_store({
            ("private_hacs", "main"): {"installed_version": "2.0.0"},
            ("private_hacs", "test"): {"installed_version": "1.0.0"},
        })
        github = AsyncMock()
        github.resolve_latest = AsyncMock(return_value={
            "type": "release", "version": "v2.1.0",
            "download_ref": "v2.1.0",
            "release_url": "https://github.com/x/releases/tag/v2.1.0",
            "release_summary": None, "commit_sha": None,
            "remote_manifest_version": None,
        })

        repos = [
            make_repo_item(branch="main", active=True, update_mode="release"),
            make_repo_item(branch="test", active=False, update_mode="release"),
        ]
        coord = PrivateHacsCoordinator(hass=hass, repos=repos, github=github, store=store)

        result = await coord._async_update_data()

        main_key = make_entry_key("private_hacs", "main")
        test_key = make_entry_key("private_hacs", "test")

        assert result[main_key]["has_update"] is True   # 활성 브랜치: 업데이트 감지
        assert result[test_key]["has_update"] is False  # 비활성 브랜치: 항상 False
