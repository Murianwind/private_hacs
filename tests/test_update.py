"""
tests/test_update.py
PrivateHacsUpdateEntity 단위 테스트 — Given/When/Then(BDD) 형식
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.private_hacs.coordinator import (
    PrivateHacsCoordinator, make_entry_key
)
from custom_components.private_hacs.update import PrivateHacsUpdateEntity
from custom_components.private_hacs.const import DOMAIN, CONF_REPOS
from conftest import make_store, make_repo_item


def _make_entity(hass, repo_cfg: dict, coord_data: dict | None = None):
    """PrivateHacsUpdateEntity 생성 헬퍼."""
    store = make_store()
    github = AsyncMock()
    coord = PrivateHacsCoordinator(hass=hass, repos=[repo_cfg], github=github, store=store)
    hass.config_entries.async_entries = MagicMock(return_value=[])

    if coord_data is not None:
        coord.data = coord_data

    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {}

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["test_entry_id"] = {"update_entities": {}}

    entity = PrivateHacsUpdateEntity(coord, entry, repo_cfg)
    entity.hass = hass
    return entity


def _repo_data_release(version="2.0.0", has_update=False):
    return {
        "installed_version": version,
        "has_update": has_update,
        "active": True,
        "update_mode": "release",
        "version_source": "store",
        "repo": "Murianwind/private_hacs",
        "branch": "main",
        "installed_commit_sha": None,
        "has_icon": False,
        "latest": {
            "type": "release",
            "version": "v2.1.0" if has_update else f"v{version}",
            "release_url": "https://github.com/Murianwind/private_hacs/releases/tag/v2.1.0",
            "release_summary": "업데이트 노트",
            "commit_sha": None,
        },
    }


def _repo_data_commit(sha="abc123abc123", new_sha=None):
    return {
        "installed_version": "2.0.0",
        "has_update": new_sha is not None and new_sha != sha,
        "active": True,
        "update_mode": "commit",
        "version_source": "store",
        "repo": "Murianwind/private_hacs",
        "branch": "test",
        "installed_commit_sha": sha,
        "has_icon": True,
        "latest": {
            "type": "branch",
            "version": (new_sha or sha)[:7],
            "release_url": "https://github.com/Murianwind/private_hacs/commits/test",
            "release_summary": None,
            "commit_sha": new_sha or sha,
        },
    }


# ══════════════════════════════════════════════════════════════════════
# installed_version / latest_version
# ══════════════════════════════════════════════════════════════════════

class TestVersionProperties:

    def test_given_installed__when_no_update__then_versions_match(self, hass):
        """
        Given: 설치됨, 업데이트 없음
        When:  installed_version / latest_version 읽기
        Then:  같은 버전 반환
        """
        repo_cfg = make_repo_item()
        entry_key = make_entry_key("private_hacs", "main")
        entity = _make_entity(hass, repo_cfg, {entry_key: _repo_data_release("2.0.0", False)})

        assert entity.installed_version == "2.0.0"
        assert entity.latest_version == "2.0.0"

    def test_given_update_available__when_active__then_latest_version_differs(self, hass):
        """
        Given: 업데이트 있음, 활성 브랜치
        When:  latest_version 읽기
        Then:  최신 버전 반환
        """
        repo_cfg = make_repo_item()
        entry_key = make_entry_key("private_hacs", "main")
        entity = _make_entity(hass, repo_cfg, {entry_key: _repo_data_release("2.0.0", True)})

        assert entity.installed_version == "2.0.0"
        assert entity.latest_version == "v2.1.0"

    def test_given_inactive_branch__when_update_available__then_latest_equals_installed(self, hass):
        """
        Given: 비활성 브랜치, 실제로 업데이트 있음
        When:  latest_version 읽기
        Then:  설치 버전 반환 (업데이트 알림 억제)
        """
        repo_cfg = make_repo_item(branch="test", active=False)
        entry_key = make_entry_key("private_hacs", "test")
        data = _repo_data_release("2.0.0", True)
        data["active"] = False
        entity = _make_entity(hass, repo_cfg, {entry_key: data})

        assert entity.latest_version == "2.0.0"

    def test_given_not_installed__when_read__then_installed_version_none(self, hass):
        """
        Given: 미설치 상태
        When:  installed_version 읽기
        Then:  None 반환
        """
        repo_cfg = make_repo_item()
        entry_key = make_entry_key("private_hacs", "main")
        data = _repo_data_release()
        data["installed_version"] = None
        entity = _make_entity(hass, repo_cfg, {entry_key: data})

        assert entity.installed_version is None


# ══════════════════════════════════════════════════════════════════════
# release_url
# ══════════════════════════════════════════════════════════════════════

class TestReleaseUrl:

    def test_given_release_type__when_read__then_returns_release_url(self, hass):
        """
        Given: 릴리즈 타입 저장소
        When:  release_url 읽기
        Then:  GitHub releases URL 반환
        """
        repo_cfg = make_repo_item()
        entry_key = make_entry_key("private_hacs", "main")
        entity = _make_entity(hass, repo_cfg, {entry_key: _repo_data_release()})

        assert "releases/tag" in entity.release_url

    def test_given_branch_type__when_read__then_returns_commits_url(self, hass):
        """
        Given: 커밋 추적 브랜치
        When:  release_url 읽기
        Then:  GitHub commits URL 반환
        """
        repo_cfg = make_repo_item(branch="test", update_mode="commit")
        entry_key = make_entry_key("private_hacs", "test")
        entity = _make_entity(hass, repo_cfg, {entry_key: _repo_data_commit()})

        assert "commits/test" in entity.release_url

    def test_given_no_latest__when_read__then_fallback_to_commits_url(self, hass):
        """
        Given: latest 없음 (초기 상태)
        When:  release_url 읽기
        Then:  커밋 로그 fallback URL
        """
        repo_cfg = make_repo_item()
        entry_key = make_entry_key("private_hacs", "main")
        data = _repo_data_release()
        data["latest"] = {}
        entity = _make_entity(hass, repo_cfg, {entry_key: data})

        assert "commits/main" in entity.release_url

    def test_given_no_repo__when_read__then_returns_none(self, hass):
        """
        Given: repo 정보 없음
        When:  release_url 읽기
        Then:  None 반환
        """
        repo_cfg = make_repo_item()
        entry_key = make_entry_key("private_hacs", "main")
        data = _repo_data_release()
        data["repo"] = None
        data["latest"] = {}
        entity = _make_entity(hass, repo_cfg, {entry_key: data})

        assert entity.release_url is None


# ══════════════════════════════════════════════════════════════════════
# extra_state_attributes
# ══════════════════════════════════════════════════════════════════════

class TestExtraStateAttributes:

    def test_given_release_branch__when_read__then_attributes_correct(self, hass):
        """
        Given: 릴리즈 추적 브랜치
        When:  extra_state_attributes 읽기
        Then:  branch, active, update_mode, latest_type 포함
        """
        repo_cfg = make_repo_item()
        entry_key = make_entry_key("private_hacs", "main")
        entity = _make_entity(hass, repo_cfg, {entry_key: _repo_data_release()})

        attrs = entity.extra_state_attributes
        assert attrs["branch"] == "main"
        assert attrs["active"] is True
        assert attrs["update_mode"] == "release"
        assert attrs["latest_type"] == "release"
        assert attrs["has_icon"] is False

    def test_given_commit_branch__when_read__then_sha_included(self, hass):
        """
        Given: 커밋 추적 브랜치, SHA 있음
        When:  extra_state_attributes 읽기
        Then:  installed_commit_sha 포함
        """
        repo_cfg = make_repo_item(branch="test", update_mode="commit")
        entry_key = make_entry_key("private_hacs", "test")
        entity = _make_entity(hass, repo_cfg, {entry_key: _repo_data_commit("abc123abc123")})

        attrs = entity.extra_state_attributes
        assert attrs["installed_commit_sha"] == "abc123abc123"
        assert attrs["update_mode"] == "commit"
        assert attrs["has_icon"] is True

    def test_given_no_coordinator_data__when_read__then_defaults_returned(self, hass):
        """
        Given: coordinator.data 없음 (초기 상태)
        When:  extra_state_attributes 읽기
        Then:  기본값 반환, 에러 없음
        """
        repo_cfg = make_repo_item()
        entity = _make_entity(hass, repo_cfg, None)

        attrs = entity.extra_state_attributes
        assert attrs["branch"] == "main"
        assert attrs["update_mode"] == "release"
        assert attrs["version_source"] == "none"


# ══════════════════════════════════════════════════════════════════════
# available / _is_active
# ══════════════════════════════════════════════════════════════════════

class TestAvailableAndActive:

    def test_given_any_state__when_available_read__then_always_true(self, hass):
        """
        Given: 어떤 상태든
        When:  available 읽기
        Then:  항상 True (패널 active 읽기 위한 설계)
        """
        repo_cfg = make_repo_item()
        entity = _make_entity(hass, repo_cfg, None)
        assert entity.available is True

    def test_given_active_in_coordinator__when_is_active_read__then_from_coordinator(self, hass):
        """
        Given: coordinator.data에 active=False
        When:  _is_active 읽기
        Then:  False 반환 (coordinator 값 우선)
        """
        repo_cfg = make_repo_item(active=True)  # repo_cfg는 True
        entry_key = make_entry_key("private_hacs", "main")
        data = _repo_data_release()
        data["active"] = False  # coordinator는 False
        entity = _make_entity(hass, repo_cfg, {entry_key: data})

        assert entity._is_active is False

    def test_given_no_coordinator_data__when_is_active_read__then_from_cache(self, hass):
        """
        Given: coordinator.data 없음
        When:  _is_active 읽기
        Then:  _active_cache(repo_cfg 값) 반환
        """
        repo_cfg = make_repo_item(active=False)
        entity = _make_entity(hass, repo_cfg, None)

        assert entity._is_active is False


# ══════════════════════════════════════════════════════════════════════
# release_summary / async_release_notes
# ══════════════════════════════════════════════════════════════════════

class TestReleaseNotes:

    def test_given_release_with_summary__when_read__then_returns_summary(self, hass):
        """
        Given: 릴리즈 노트 있음
        When:  release_summary 읽기
        Then:  노트 반환
        """
        repo_cfg = make_repo_item()
        entry_key = make_entry_key("private_hacs", "main")
        entity = _make_entity(hass, repo_cfg, {entry_key: _repo_data_release()})

        assert entity.release_summary == "업데이트 노트"

    @pytest.mark.asyncio
    async def test_given_release_notes_called__when_invoked__then_returns_summary(self, hass):
        """
        Given: 릴리즈 노트 있음
        When:  async_release_notes 호출
        Then:  노트 반환
        """
        repo_cfg = make_repo_item()
        entry_key = make_entry_key("private_hacs", "main")
        entity = _make_entity(hass, repo_cfg, {entry_key: _repo_data_release()})

        result = await entity.async_release_notes()
        assert result == "업데이트 노트"

    def test_given_commit_branch__when_summary_read__then_returns_none(self, hass):
        """
        Given: 커밋 추적 브랜치 (release_summary 없음)
        When:  release_summary 읽기
        Then:  None 반환
        """
        repo_cfg = make_repo_item(branch="test", update_mode="commit")
        entry_key = make_entry_key("private_hacs", "test")
        entity = _make_entity(hass, repo_cfg, {entry_key: _repo_data_commit()})

        assert entity.release_summary is None


# ══════════════════════════════════════════════════════════════════════
# async_setup_entry
# ══════════════════════════════════════════════════════════════════════

class TestAsyncSetupEntry:

    @pytest.mark.asyncio
    async def test_given_repos_registered__when_setup__then_entities_added(self, hass):
        """
        Given: 저장소 2개 등록
        When:  async_setup_entry 호출
        Then:  async_add_entities에 엔티티 2개 전달
        """
        from custom_components.private_hacs.update import async_setup_entry
        from custom_components.private_hacs.coordinator import PrivateHacsCoordinator

        repos = [make_repo_item(branch="main"), make_repo_item(branch="test")]
        store = make_store()
        github = AsyncMock()
        coord = PrivateHacsCoordinator(hass=hass, repos=repos, github=github, store=store)
        hass.config_entries.async_entries = MagicMock(return_value=[])

        entry = MagicMock()
        entry.entry_id = "test_entry_id"
        entry.data = {DOMAIN: repos, "repos": repos}
        entry.data.get = MagicMock(return_value=repos)

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["test_entry_id"] = {
            "coordinator": coord,
            "update_entities": {},
        }

        added = []
        def _add_entities(entities, **kwargs):
            added.extend(list(entities))

        await async_setup_entry(hass, entry, _add_entities)

        assert len(added) == 2


# ══════════════════════════════════════════════════════════════════════
# async_will_remove_from_hass
# ══════════════════════════════════════════════════════════════════════

class TestAsyncWillRemoveFromHass:

    @pytest.mark.asyncio
    async def test_given_entity_registered__when_removed__then_cleaned_from_dict(self, hass):
        """
        Given: update_entities에 엔티티 등록됨
        When:  async_will_remove_from_hass 호출
        Then:  update_entities에서 제거됨
        """
        repo_cfg = make_repo_item()
        entry_key = make_entry_key("private_hacs", "main")
        entity = _make_entity(hass, repo_cfg, {entry_key: _repo_data_release()})

        # 등록 확인
        assert entry_key in hass.data[DOMAIN]["test_entry_id"]["update_entities"]

        await entity.async_will_remove_from_hass()

        assert entry_key not in hass.data[DOMAIN]["test_entry_id"].get("update_entities", {})

class TestAsyncInstall:

    @pytest.mark.asyncio
    async def test_given_install_called__when_invoked__then_do_install_called(self, hass):
        """
        Given: 설치 요청
        When:  async_install 호출
        Then:  _do_install 호출됨
        """
        repo_cfg = make_repo_item()
        entry_key = make_entry_key("private_hacs", "main")
        entity = _make_entity(hass, repo_cfg, {entry_key: _repo_data_release()})

        mock_install = AsyncMock()
        # update.py 내부에서 `from .services import _do_install` 로 임포트하므로
        # services 모듈의 원본을 패치해야 함
        with patch("custom_components.private_hacs.services._do_install", mock_install):
            await entity.async_install(None, False)
            mock_install.assert_called_once()

    @pytest.mark.asyncio
    async def test_given_specific_version__when_install__then_ref_passed(self, hass):
        """
        Given: 특정 버전 지정 설치 (version="v1.0.0")
        When:  async_install("v1.0.0") 호출
        Then:  _do_install에 ref="v1.0.0" 전달
        """
        repo_cfg = make_repo_item()
        entry_key = make_entry_key("private_hacs", "main")
        entity = _make_entity(hass, repo_cfg, {entry_key: _repo_data_release()})

        mock_install = AsyncMock()
        with patch("custom_components.private_hacs.services._do_install", mock_install):
            await entity.async_install("v1.0.0", False)
            mock_install.assert_called_once_with(
                entity.hass, "private_hacs", "main", ref="v1.0.0"
            )
