"""
tests/test_coordinator.py
coordinator 핵심 로직 단위 테스트 — Given/When/Then(BDD) 형식

DataUpdateCoordinator는 HA 이벤트 루프가 필요하므로
순수 로직 메서드(_compute_has_update, _resolve_installed_version 등)는
인스턴스 없이 직접 테스트한다.
_async_update_data는 pytest-homeassistant-custom-component의 hass 픽스처를 사용한다.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.private_hacs.coordinator import (
    PrivateHacsCoordinator,
    make_entry_key,
    UPDATE_MODE_RELEASE,
    UPDATE_MODE_COMMIT,
    _strip_v,
)
from custom_components.private_hacs.github import GitHubAuthError
from homeassistant.exceptions import ConfigEntryAuthFailed
from conftest import make_store, make_repo_item, make_github_client


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
# _compute_has_update — 인스턴스 없이 직접 테스트 (언바운드 호출)
# ══════════════════════════════════════════════════════════════════════

def _compute(latest, installed_version, installed_commit_sha):
    """PrivateHacsCoordinator._compute_has_update 를 인스턴스 없이 호출."""
    return PrivateHacsCoordinator._compute_has_update(
        None, latest, installed_version, installed_commit_sha
    )


class TestComputeHasUpdate:

    def test_given_release_type_and_version_matches__when_computed__then_no_update(self):
        """
        Given: 릴리즈 타입, 설치 버전 == 최신 버전
        When:  _compute_has_update 호출
        Then:  False 반환
        """
        latest = {"type": "release", "version": "v2.0.0"}
        assert _compute(latest, "2.0.0", None) is False

    def test_given_release_type_and_version_differs__when_computed__then_has_update(self):
        """
        Given: 릴리즈 타입, 설치 버전 != 최신 버전
        When:  _compute_has_update 호출
        Then:  True 반환
        """
        latest = {"type": "release", "version": "v2.1.0"}
        assert _compute(latest, "2.0.0", None) is True

    def test_given_release_type_with_v_prefix_mismatch__when_computed__then_normalizes_correctly(self):
        """
        Given: installed='3.0.7' vs latest='v3.0.7' (v 접두사 불일치)
        When:  _compute_has_update 호출
        Then:  False (같은 버전으로 정규화)
        """
        latest = {"type": "release", "version": "v3.0.7"}
        assert _compute(latest, "3.0.7", None) is False

    def test_given_branch_type_and_sha_matches__when_computed__then_no_update(self):
        """
        Given: 브랜치 타입, 설치 SHA == 최신 SHA
        When:  _compute_has_update 호출
        Then:  False 반환
        """
        sha = "abc123"
        latest = {"type": "branch", "commit_sha": sha, "remote_manifest_version": None}
        assert _compute(latest, "2.0.0", sha) is False

    def test_given_branch_type_and_sha_differs__when_computed__then_has_update(self):
        """
        Given: 브랜치 타입, 설치 SHA != 최신 SHA
        When:  _compute_has_update 호출
        Then:  True 반환
        """
        latest = {"type": "branch", "commit_sha": "newsha999", "remote_manifest_version": None}
        assert _compute(latest, "2.0.0", "oldsha111") is True

    def test_given_branch_type_and_no_installed_sha__when_computed__then_no_update(self):
        """
        Given: 브랜치 타입, installed_commit_sha 없음
        When:  _compute_has_update 호출
        Then:  False (SHA 없이 비교 불가)
        """
        latest = {"type": "branch", "commit_sha": "newsha999", "remote_manifest_version": None}
        assert _compute(latest, "2.0.0", None) is False

    def test_given_branch_type_with_manifest_version_differs__when_computed__then_has_update(self):
        """
        Given: 브랜치 타입, remote_manifest_version != installed_version
        When:  _compute_has_update 호출
        Then:  True 반환
        """
        latest = {"type": "branch", "commit_sha": None, "remote_manifest_version": "2.2.0"}
        assert _compute(latest, "2.1.0", None) is True

    def test_given_no_installed_version__when_computed__then_no_update(self):
        """
        Given: installed_version 없음 (미설치)
        When:  _compute_has_update 호출
        Then:  False 반환
        """
        latest = {"type": "release", "version": "v2.0.0"}
        assert _compute(latest, None, None) is False

    def test_given_latest_none__when_computed__then_no_update(self):
        """
        Given: latest 없음 (API 실패)
        When:  _compute_has_update 호출
        Then:  False 반환
        """
        assert _compute(None, "2.0.0", None) is False


# ══════════════════════════════════════════════════════════════════════
# _resolve_installed_version — hass 픽스처 사용
# ══════════════════════════════════════════════════════════════════════

class TestResolveInstalledVersion:

    @pytest.mark.asyncio
    async def test_given_version_in_store__when_active_branch__then_returns_store_version(self, hass):
        """
        Given: store에 installed_version 기록 있음
        When:  활성 브랜치의 _resolve_installed_version 호출
        Then:  store 버전 반환, source="store"
        """
        store = make_store({("private_hacs", "main"): {"installed_version": "2.0.0"}})
        coord = PrivateHacsCoordinator(hass=hass, repos=[], github=AsyncMock(), store=store)

        version, source = await coord._resolve_installed_version("private_hacs", "main", active=True)

        assert version == "2.0.0"
        assert source == "store"

    @pytest.mark.asyncio
    async def test_given_no_store__when_inactive_branch__then_manifest_not_read(self, hass):
        """
        Given: store 기록 없음, 비활성 브랜치
        When:  _resolve_installed_version 호출
        Then:  manifest 읽기 차단 → None, source="none"
        """
        store = make_store()
        coord = PrivateHacsCoordinator(hass=hass, repos=[], github=AsyncMock(), store=store)

        version, source = await coord._resolve_installed_version(
            "private_hacs", "test", active=False
        )

        assert version is None
        assert source == "none"

    @pytest.mark.asyncio
    async def test_given_no_store_but_manifest_exists__when_active_branch__then_returns_manifest_version(self, hass):
        """
        Given: store 기록 없음, manifest.json 있음, 활성 브랜치
        When:  _resolve_installed_version 호출
        Then:  manifest 버전 반환, source="manifest"
        """
        store = make_store()
        coord = PrivateHacsCoordinator(hass=hass, repos=[], github=AsyncMock(), store=store)

        with patch.object(coord, "_read_manifest_version_sync", return_value="2.1.0"):
            version, source = await coord._resolve_installed_version(
                "private_hacs", "main", active=True
            )

        assert version == "2.1.0"
        assert source == "manifest"


# ══════════════════════════════════════════════════════════════════════
# _async_update_data — hass 픽스처 사용
# ══════════════════════════════════════════════════════════════════════

def _make_coord(hass, repos, github, store=None):
    coord = PrivateHacsCoordinator(
        hass=hass, repos=list(repos),
        github=github, store=store or make_store()
    )
    hass.config_entries.async_entries = MagicMock(return_value=[])
    # 실제 파일시스템 없이 테스트하므로 설치 여부는 store에 버전이 있으면 True로 간주
    original_check = coord._check_installed
    async def _patched_check(component_id):
        s = coord.store
        # store에 해당 component_id 브랜치 중 installed_version이 있으면 True
        for r in coord.repos:
            if r.get("component_id") == component_id:
                branch = r.get("branch", "main")
                if s.installed_version(component_id, branch):
                    return True
        return False
    coord._check_installed = _patched_check
    return coord


def _release_latest(version="v2.0.0"):
    return {
        "type": "release", "version": version, "download_ref": version,
        "release_url": f"https://github.com/x/releases/tag/{version}",
        "release_summary": None, "commit_sha": None, "remote_manifest_version": None,
    }


def _commit_latest(sha="abc123abc123", branch="main"):
    return {
        "type": "branch", "version": sha[:7], "download_ref": branch,
        "release_url": f"https://github.com/x/commits/{branch}",
        "release_summary": None, "commit_sha": sha, "remote_manifest_version": None,
    }


class TestAsyncUpdateDataRelease:

    @pytest.mark.asyncio
    async def test_given_repo_with_release__when_polled__then_data_contains_release_info(self, hass):
        """
        Given: 릴리즈 있는 저장소, update_mode=release
        When:  _async_update_data 실행
        Then:  latest.type="release" 포함
        """
        github = AsyncMock()
        github.resolve_latest = AsyncMock(return_value=_release_latest())
        repos = [make_repo_item(update_mode="release")]
        coord = _make_coord(hass, repos, github)

        result = await coord._async_update_data()

        key = make_entry_key("private_hacs", "main")
        assert result[key]["latest"]["type"] == "release"
        assert result[key]["latest"]["version"] == "v2.0.0"

    @pytest.mark.asyncio
    async def test_given_installed_version_and_new_release__when_polled__then_has_update_true(self, hass):
        """
        Given: 설치 버전 2.0.0, 최신 릴리즈 v2.1.0
        When:  _async_update_data 실행
        Then:  has_update=True
        """
        store = make_store({("private_hacs", "main"): {"installed_version": "2.0.0"}})
        github = AsyncMock()
        github.resolve_latest = AsyncMock(return_value=_release_latest("v2.1.0"))
        repos = [make_repo_item(update_mode="release")]
        coord = _make_coord(hass, repos, github, store)

        result = await coord._async_update_data()
        assert result[make_entry_key("private_hacs", "main")]["has_update"] is True

    @pytest.mark.asyncio
    async def test_given_installed_version_matches_release__when_polled__then_has_update_false(self, hass):
        """
        Given: 설치 버전 2.0.0, 최신 릴리즈 v2.0.0 (동일)
        When:  _async_update_data 실행
        Then:  has_update=False
        """
        store = make_store({("private_hacs", "main"): {"installed_version": "2.0.0"}})
        github = AsyncMock()
        github.resolve_latest = AsyncMock(return_value=_release_latest("v2.0.0"))
        repos = [make_repo_item(update_mode="release")]
        coord = _make_coord(hass, repos, github, store)

        result = await coord._async_update_data()
        assert result[make_entry_key("private_hacs", "main")]["has_update"] is False


class TestAsyncUpdateDataCommit:

    @pytest.mark.asyncio
    async def test_given_repo_with_commit_mode__when_polled__then_uses_resolve_branch_latest(self, hass):
        """
        Given: update_mode=commit 브랜치
        When:  _async_update_data 실행
        Then:  resolve_branch_latest 호출, resolve_latest 미호출
        """
        github = AsyncMock()
        github.resolve_branch_latest = AsyncMock(return_value=_commit_latest())
        repos = [make_repo_item(branch="test", update_mode="commit")]
        coord = _make_coord(hass, repos, github)

        await coord._async_update_data()

        github.resolve_branch_latest.assert_called_once()
        github.resolve_latest.assert_not_called()

    @pytest.mark.asyncio
    async def test_given_new_commit_sha__when_polled__then_has_update_true(self, hass):
        """
        Given: 설치 SHA=old, 최신 SHA=new
        When:  _async_update_data 실행 (commit 모드)
        Then:  has_update=True
        """
        store = make_store({
            ("private_hacs", "test"): {
                "installed_version": "2.0.0", "installed_commit_sha": "oldsha111",
            }
        })
        github = AsyncMock()
        github.resolve_branch_latest = AsyncMock(return_value=_commit_latest("newsha999", "test"))
        repos = [make_repo_item(branch="test", update_mode="commit")]
        coord = _make_coord(hass, repos, github, store)

        result = await coord._async_update_data()
        assert result[make_entry_key("private_hacs", "test")]["has_update"] is True

    @pytest.mark.asyncio
    async def test_given_same_commit_sha__when_polled__then_has_update_false(self, hass):
        """
        Given: 설치 SHA == 최신 SHA
        When:  _async_update_data 실행 (commit 모드)
        Then:  has_update=False
        """
        sha = "abc123abc123"
        store = make_store({
            ("private_hacs", "test"): {
                "installed_version": "2.0.0", "installed_commit_sha": sha,
            }
        })
        github = AsyncMock()
        github.resolve_branch_latest = AsyncMock(return_value=_commit_latest(sha, "test"))
        repos = [make_repo_item(branch="test", update_mode="commit")]
        coord = _make_coord(hass, repos, github, store)

        result = await coord._async_update_data()
        assert result[make_entry_key("private_hacs", "test")]["has_update"] is False


class TestAutoSwitchUpdateMode:

    @pytest.mark.asyncio
    async def test_given_release_mode_but_no_releases__when_polled__then_auto_switches_to_commit(self, hass):
        """
        Given: update_mode=release 이지만 결과가 branch 타입
        When:  _async_update_data 실행
        Then:  update_mode가 commit으로 자동 전환
        """
        github = AsyncMock()
        github.resolve_latest = AsyncMock(return_value=_commit_latest())
        repo_item = make_repo_item(update_mode="release")
        repos = [repo_item]
        coord = _make_coord(hass, repos, github)

        result = await coord._async_update_data()
        key = make_entry_key("private_hacs", "main")

        assert result[key]["update_mode"] == UPDATE_MODE_COMMIT
        assert repos[0]["update_mode"] == UPDATE_MODE_COMMIT


class TestInactiveBranch:

    @pytest.mark.asyncio
    async def test_given_inactive_branch__when_polled__then_has_update_always_false(self, hass):
        """
        Given: active=False 브랜치, 실제로 업데이트 있음
        When:  _async_update_data 실행
        Then:  has_update=False
        """
        store = make_store({("private_hacs", "test"): {"installed_version": "1.0.0"}})
        github = AsyncMock()
        github.resolve_latest = AsyncMock(return_value=_release_latest("v2.0.0"))
        repos = [make_repo_item(branch="test", active=False)]
        coord = _make_coord(hass, repos, github, store)

        result = await coord._async_update_data()
        assert result[make_entry_key("private_hacs", "test")]["has_update"] is False

    @pytest.mark.asyncio
    async def test_given_inactive_branch_no_store__when_polled__then_not_reads_manifest(self, hass):
        """
        Given: active=False, store 기록 없음
        When:  _async_update_data 실행
        Then:  installed_version=None (manifest 자동 감지 차단)
        """
        store = make_store()
        github = AsyncMock()
        github.resolve_latest = AsyncMock(return_value=_release_latest())
        repos = [make_repo_item(branch="test", active=False)]
        coord = _make_coord(hass, repos, github, store)

        result = await coord._async_update_data()
        assert result[make_entry_key("private_hacs", "test")]["installed_version"] is None


class TestShaAutoRecovery:

    @pytest.mark.asyncio
    async def test_given_installed_without_sha__when_polled__then_sha_auto_recovered(self, hass):
        """
        Given: installed_version 있음, installed_commit_sha 없음
        When:  _async_update_data 실행 (commit 모드)
        Then:  remote SHA로 자동 복구, store 저장
        """
        remote_sha = "abc123abc123"
        store = make_store({
            ("private_hacs", "main"): {
                "installed_version": "2.0.0", "installed_commit_sha": None,
            }
        })
        github = AsyncMock()
        github.resolve_branch_latest = AsyncMock(return_value=_commit_latest(remote_sha))
        repos = [make_repo_item(update_mode="commit")]
        coord = _make_coord(hass, repos, github, store)

        # _make_coord의 _patched_check는 store에 installed_version이 있으면 True 반환
        # store에 installed_version=2.0.0 이 있으므로 is_installed=True
        result = await coord._async_update_data()

        key = make_entry_key("private_hacs", "main")
        assert result[key]["installed_commit_sha"] == remote_sha
        store.async_set_branch.assert_called()


class TestAuthFailurePropagation:

    @pytest.mark.asyncio
    async def test_given_auth_error_from_github__when_polled__then_propagates_to_coordinator(self, hass):
        """
        Given: GitHub 401 → GitHubAuthError
        When:  _async_update_data 실행
        Then:  ConfigEntryAuthFailed 전파
        """
        github = AsyncMock()
        github.resolve_latest = AsyncMock(side_effect=GitHubAuthError("토큰 만료"))
        repos = [make_repo_item()]
        coord = _make_coord(hass, repos, github)

        with pytest.raises(ConfigEntryAuthFailed):
            await coord._async_update_data()


class TestRefresh:

    @pytest.mark.asyncio
    async def test_given_new_commit_after_poll__when_polled_again__then_sha_updated(self, hass):
        """
        Given: 1차 폴링 SHA=old, 이후 새 커밋 푸시
        When:  2차 _async_update_data 실행
        Then:  has_update=True
        """
        sha_old = "oldsha111"
        sha_new = "newsha999"
        store = make_store({
            ("private_hacs", "main"): {
                "installed_version": "2.0.0", "installed_commit_sha": sha_old,
            }
        })
        github = AsyncMock()
        github.resolve_branch_latest = AsyncMock(return_value=_commit_latest(sha_old))
        repos = [make_repo_item(update_mode="commit")]
        coord = _make_coord(hass, repos, github, store)

        result1 = await coord._async_update_data()
        assert result1[make_entry_key("private_hacs", "main")]["has_update"] is False

        github.resolve_branch_latest = AsyncMock(return_value=_commit_latest(sha_new))
        result2 = await coord._async_update_data()
        assert result2[make_entry_key("private_hacs", "main")]["has_update"] is True


class TestMultiBranch:

    @pytest.mark.asyncio
    async def test_given_two_branches_same_component__when_polled__then_each_tracked_independently(self, hass):
        """
        Given: main(활성) + test(비활성) 브랜치
        When:  _async_update_data 실행
        Then:  main has_update=True, test has_update=False(비활성 고정)
        """
        store = make_store({
            ("private_hacs", "main"): {"installed_version": "2.0.0"},
            ("private_hacs", "test"): {"installed_version": "1.0.0"},
        })
        github = AsyncMock()
        github.resolve_latest = AsyncMock(return_value=_release_latest("v2.1.0"))
        repos = [
            make_repo_item(branch="main", active=True, update_mode="release"),
            make_repo_item(branch="test", active=False, update_mode="release"),
        ]
        coord = _make_coord(hass, repos, github, store)

        result = await coord._async_update_data()

        assert result[make_entry_key("private_hacs", "main")]["has_update"] is True
        assert result[make_entry_key("private_hacs", "test")]["has_update"] is False
