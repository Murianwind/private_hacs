"""
tests/test_services.py
서비스 핸들러 단위 테스트 — Given/When/Then(BDD) 형식
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from custom_components.private_hacs.services import (
    _do_install, _do_uninstall, _do_add_repo,
    _do_remove_repo, _do_set_update_mode,
)
from custom_components.private_hacs.const import DOMAIN, CONF_REPOS
from homeassistant.exceptions import HomeAssistantError
from conftest import make_store, make_repo_item, make_hass_for_services


# ══════════════════════════════════════════════════════════════════════
# _do_install
# ══════════════════════════════════════════════════════════════════════

class TestDoInstall:

    def _make_coord(self, repos, entry_key, latest):
        coord = MagicMock()
        coord.repos = list(repos)
        coord.data = {entry_key: {"latest": latest, "repo": "Murianwind/private_hacs"}}
        coord.async_request_refresh = AsyncMock()
        return coord

    @pytest.mark.asyncio
    async def test_given_release_repo__when_install__then_store_saves_version(self):
        """
        Given: 릴리즈 저장소, latest=v2.0.0
        When:  _do_install 호출
        Then:  store에 installed_version="v2.0.0" 저장
        """
        repos = [make_repo_item()]
        latest = {
            "type": "release", "version": "v2.0.0", "download_ref": "v2.0.0",
            "release_url": "https://github.com/x/releases/tag/v2.0.0",
            "release_summary": None, "commit_sha": None, "remote_manifest_version": None,
        }
        store = make_store()
        github = AsyncMock()
        github.download_and_install = AsyncMock()
        coord = self._make_coord(repos, "private_hacs@main", latest)

        hass, entry, ed, _ = make_hass_for_services(repos, store, github, coord)

        await _do_install(hass, "private_hacs", "main")

        store.async_set_branch.assert_called()
        saved = store.async_set_branch.call_args_list[0][0][2]
        assert saved["installed_version"] == "v2.0.0"

    @pytest.mark.asyncio
    async def test_given_commit_repo__when_install__then_store_saves_sha(self):
        """
        Given: 커밋 추적 저장소, commit_sha 있음
        When:  _do_install 호출
        Then:  store에 installed_commit_sha 저장
        """
        sha = "abc123abc123"
        repos = [make_repo_item(update_mode="commit")]
        latest = {
            "type": "branch", "version": "abc123", "download_ref": "main",
            "release_url": "https://github.com/x/commits/main",
            "release_summary": None, "commit_sha": sha, "remote_manifest_version": None,
        }
        store = make_store()
        github = AsyncMock()
        github.download_and_install = AsyncMock()
        coord = self._make_coord(repos, "private_hacs@main", latest)

        hass, entry, ed, _ = make_hass_for_services(repos, store, github, coord)

        await _do_install(hass, "private_hacs", "main")

        saved = store.async_set_branch.call_args_list[0][0][2]
        assert saved.get("installed_commit_sha") == sha

    @pytest.mark.asyncio
    async def test_given_two_branches__when_one_installed__then_other_branch_store_cleared(self):
        """
        Given: main + test 두 브랜치, test 설치 요청
        When:  _do_install("test") 호출
        Then:  main의 installed_version/sha가 None으로 초기화
        """
        repos = [make_repo_item(branch="main"), make_repo_item(branch="test", update_mode="commit")]
        sha = "newsha999"
        latest = {
            "type": "branch", "version": "newsha", "download_ref": "test",
            "release_url": "https://github.com/x/commits/test",
            "release_summary": None, "commit_sha": sha, "remote_manifest_version": None,
        }
        store = make_store({("private_hacs", "main"): {"installed_version": "2.0.0", "installed_commit_sha": "oldsha"}})
        github = AsyncMock()
        github.download_and_install = AsyncMock()
        coord = self._make_coord(repos, "private_hacs@test", latest)

        hass, entry, ed, _ = make_hass_for_services(repos, store, github, coord)

        await _do_install(hass, "private_hacs", "test")

        # main 브랜치 초기화 호출 확인
        clear_calls = [
            c for c in store.async_set_branch.call_args_list
            if c[0][1] == "main" and c[0][2].get("installed_version") is None
        ]
        assert len(clear_calls) >= 1

    @pytest.mark.asyncio
    async def test_given_specific_ref__when_install__then_uses_ref_version(self):
        """
        Given: ref="v1.0.0" 지정 설치
        When:  _do_install(ref="v1.0.0")
        Then:  installed_version="v1.0.0", installed_commit_sha=None
        """
        repos = [make_repo_item()]
        latest = {
            "type": "release", "version": "v2.0.0", "download_ref": "v2.0.0",
            "release_url": "https://github.com/x/releases/tag/v2.0.0",
            "release_summary": None, "commit_sha": None, "remote_manifest_version": None,
        }
        store = make_store()
        github = AsyncMock()
        github.download_and_install = AsyncMock()
        coord = self._make_coord(repos, "private_hacs@main", latest)

        hass, entry, ed, _ = make_hass_for_services(repos, store, github, coord)

        await _do_install(hass, "private_hacs", "main", ref="v1.0.0")

        saved = store.async_set_branch.call_args_list[0][0][2]
        assert saved["installed_version"] == "v1.0.0"
        assert saved.get("installed_commit_sha") is None

    @pytest.mark.asyncio
    async def test_given_missing_entry_key__when_install__then_raises_error(self):
        """
        Given: coordinator.data에 entry_key 없음
        When:  _do_install 호출
        Then:  HomeAssistantError 발생
        """
        repos = [make_repo_item()]
        store = make_store()
        github = AsyncMock()
        coord = MagicMock()
        coord.repos = list(repos)
        coord.data = {}  # 비어있음
        coord.async_request_refresh = AsyncMock()

        hass, _, _, _ = make_hass_for_services(repos, store, github, coord)

        with pytest.raises(HomeAssistantError):
            await _do_install(hass, "private_hacs", "main")


# ══════════════════════════════════════════════════════════════════════
# _do_remove_repo
# ══════════════════════════════════════════════════════════════════════

class TestDoRemoveRepo:

    @pytest.mark.asyncio
    async def test_given_registered_branch__when_removed__then_removed_from_config(self):
        """
        Given: main 브랜치 등록됨
        When:  _do_remove_repo 호출
        Then:  config entry에서 해당 브랜치 제거
        """
        repos = [make_repo_item(branch="main", active=True)]
        store = make_store()
        github = AsyncMock()

        hass, entry, ed, coord = make_hass_for_services(repos, store, github)

        with patch("custom_components.private_hacs.services.er") as mock_er:
            mock_er.async_get.return_value = MagicMock(
                async_get_entity_id=MagicMock(return_value=None)
            )
            await _do_remove_repo(hass, "private_hacs", "main")

        assert not any(r["branch"] == "main" for r in entry.data[CONF_REPOS])

    @pytest.mark.asyncio
    async def test_given_active_with_sibling__when_removed__then_sibling_auto_activated(self):
        """
        Given: main(활성) + test(비활성), main 제거
        When:  _do_remove_repo 호출
        Then:  test 자동 활성화
        """
        repos = [
            make_repo_item(branch="main", active=True),
            make_repo_item(branch="test", active=False),
        ]
        store = make_store()
        github = AsyncMock()

        hass, entry, ed, coord = make_hass_for_services(repos, store, github)

        with patch("custom_components.private_hacs.services.er") as mock_er:
            mock_er.async_get.return_value = MagicMock(
                async_get_entity_id=MagicMock(return_value=None)
            )
            await _do_remove_repo(hass, "private_hacs", "main")

        test_branch = next(r for r in entry.data[CONF_REPOS] if r["branch"] == "test")
        assert test_branch["active"] is True

    @pytest.mark.asyncio
    async def test_given_unregistered_branch__when_removed__then_raises_error(self):
        """
        Given: 등록되지 않은 브랜치
        When:  _do_remove_repo 호출
        Then:  HomeAssistantError 발생
        """
        repos = [make_repo_item(branch="main")]
        store = make_store()
        github = AsyncMock()
        hass, _, _, _ = make_hass_for_services(repos, store, github)

        with pytest.raises(HomeAssistantError):
            await _do_remove_repo(hass, "private_hacs", "nonexistent")


# ══════════════════════════════════════════════════════════════════════
# _do_set_update_mode
# ══════════════════════════════════════════════════════════════════════

class TestDoSetUpdateMode:

    @pytest.mark.asyncio
    async def test_given_release_mode__when_changed_to_commit__then_config_updated(self):
        """
        Given: main 브랜치 update_mode=release
        When:  _do_set_update_mode("commit")
        Then:  config entry update_mode=commit
        """
        repos = [make_repo_item(update_mode="release")]
        store = make_store()
        github = AsyncMock()
        coord = MagicMock()
        coord.repos = list(repos)
        coord.data = {"private_hacs@main": {"update_mode": "release"}}
        coord.async_update_listeners = MagicMock()
        coord.async_request_refresh = AsyncMock()

        hass, entry, ed, _ = make_hass_for_services(repos, store, github, coord)

        await _do_set_update_mode(hass, "private_hacs", "main", "commit")

        updated = next(r for r in entry.data[CONF_REPOS] if r["branch"] == "main")
        assert updated["update_mode"] == "commit"

    @pytest.mark.asyncio
    async def test_given_commit_mode__when_changed_to_release__then_config_updated(self):
        """
        Given: test 브랜치 update_mode=commit
        When:  _do_set_update_mode("release")
        Then:  config entry update_mode=release
        """
        repos = [make_repo_item(branch="test", update_mode="commit")]
        store = make_store()
        github = AsyncMock()
        coord = MagicMock()
        coord.repos = list(repos)
        coord.data = {"private_hacs@test": {"update_mode": "commit"}}
        coord.async_update_listeners = MagicMock()
        coord.async_request_refresh = AsyncMock()

        hass, entry, ed, _ = make_hass_for_services(repos, store, github, coord)

        await _do_set_update_mode(hass, "private_hacs", "test", "release")

        updated = next(r for r in entry.data[CONF_REPOS] if r["branch"] == "test")
        assert updated["update_mode"] == "release"

    @pytest.mark.asyncio
    async def test_given_nonexistent_branch__when_set_update_mode__then_raises_error(self):
        """
        Given: 등록되지 않은 브랜치
        When:  _do_set_update_mode 호출
        Then:  HomeAssistantError 발생
        """
        repos = [make_repo_item()]
        store = make_store()
        github = AsyncMock()
        hass, _, _, _ = make_hass_for_services(repos, store, github)

        with pytest.raises(HomeAssistantError):
            await _do_set_update_mode(hass, "private_hacs", "nonexistent", "commit")


# ══════════════════════════════════════════════════════════════════════
# _do_add_repo
# ══════════════════════════════════════════════════════════════════════

class TestDoAddRepo:

    @pytest.mark.asyncio
    async def test_given_valid_repo__when_added__then_saved_to_config(self):
        """
        Given: 유효한 저장소
        When:  _do_add_repo 호출
        Then:  config entry에 저장소 추가
        """
        repos = []
        store = make_store()
        github = AsyncMock()
        github.get_repo_info = AsyncMock(return_value={"name": "private_hacs", "default_branch": "main"})

        coord = MagicMock()
        coord.repos = []
        coord.async_request_refresh = AsyncMock()
        coord.async_update_listeners = MagicMock()

        hass, entry, ed, _ = make_hass_for_services(repos, store, github, coord)
        ed["async_add_entities"] = MagicMock()

        await _do_add_repo(
            hass, repo="Murianwind/private_hacs",
            name="Private HACS", component_id="private_hacs",
            branch="main", update_mode="release",
        )

        assert any(r["component_id"] == "private_hacs" for r in entry.data[CONF_REPOS])

    @pytest.mark.asyncio
    async def test_given_nonexistent_repo__when_added__then_raises_error(self):
        """
        Given: get_repo_info → None (저장소 없음)
        When:  _do_add_repo 호출
        Then:  HomeAssistantError 발생
        """
        repos = []
        store = make_store()
        github = AsyncMock()
        github.get_repo_info = AsyncMock(return_value=None)

        hass, _, _, _ = make_hass_for_services(repos, store, github)

        with pytest.raises(HomeAssistantError):
            await _do_add_repo(
                hass, repo="Murianwind/nonexistent",
                name="없는 저장소", component_id="nonexistent",
                branch="main", update_mode="release",
            )

    @pytest.mark.asyncio
    async def test_given_duplicate_branch__when_added__then_raises_error(self):
        """
        Given: 이미 동일 component_id + branch 등록됨
        When:  _do_add_repo 호출
        Then:  HomeAssistantError 발생
        """
        repos = [make_repo_item(branch="main")]
        store = make_store()
        github = AsyncMock()
        github.get_repo_info = AsyncMock(return_value={"name": "private_hacs"})

        hass, _, _, _ = make_hass_for_services(repos, store, github)

        with pytest.raises(HomeAssistantError):
            await _do_add_repo(
                hass, repo="Murianwind/private_hacs",
                name="Private HACS", component_id="private_hacs",
                branch="main", update_mode="release",
            )

    @pytest.mark.asyncio
    async def test_given_commit_mode__when_added__then_update_mode_saved(self):
        """
        Given: update_mode=commit으로 추가
        When:  _do_add_repo 호출
        Then:  config entry에 update_mode=commit 저장
        """
        repos = [make_repo_item(branch="main", update_mode="release")]
        store = make_store()
        github = AsyncMock()
        github.get_repo_info = AsyncMock(return_value={"name": "private_hacs"})

        coord = MagicMock()
        coord.repos = list(repos)
        coord.async_request_refresh = AsyncMock()
        coord.async_update_listeners = MagicMock()

        hass, entry, ed, _ = make_hass_for_services(repos, store, github, coord)
        ed["async_add_entities"] = MagicMock()

        await _do_add_repo(
            hass, repo="Murianwind/private_hacs",
            name="Private HACS", component_id="private_hacs",
            branch="test", update_mode="commit",
        )

        test_branch = next(r for r in entry.data[CONF_REPOS] if r["branch"] == "test")
        assert test_branch["update_mode"] == "commit"


# ══════════════════════════════════════════════════════════════════════
# _do_uninstall
# ══════════════════════════════════════════════════════════════════════

class TestDoUninstall:

    @pytest.mark.asyncio
    async def test_given_installed_component__when_uninstalled__then_store_cleared(self):
        """
        Given: coordinator.data에 private_hacs 있음
        When:  _do_uninstall 호출
        Then:  github.uninstall + store.async_remove 호출
        """
        repos = [make_repo_item()]
        store = make_store()
        github = AsyncMock()
        github.uninstall = AsyncMock()

        coord = MagicMock()
        coord.repos = list(repos)
        coord.data = {"private_hacs@main": {"component_id": "private_hacs"}}
        coord.async_request_refresh = AsyncMock()

        hass, _, _, _ = make_hass_for_services(repos, store, github, coord)

        await _do_uninstall(hass, "private_hacs")

        github.uninstall.assert_called_once()
        store.async_remove.assert_called_once_with("private_hacs")

    @pytest.mark.asyncio
    async def test_given_nonexistent_component__when_uninstalled__then_raises_error(self):
        """
        Given: coordinator.data 비어있음
        When:  _do_uninstall 호출
        Then:  HomeAssistantError 발생
        """
        repos = []
        store = make_store()
        github = AsyncMock()

        coord = MagicMock()
        coord.repos = []
        coord.data = {}
        coord.async_request_refresh = AsyncMock()

        hass, _, _, _ = make_hass_for_services(repos, store, github, coord)

        with pytest.raises(HomeAssistantError):
            await _do_uninstall(hass, "nonexistent")
