"""
tests/test_services.py
서비스 핸들러 단위 테스트

_do_install, _do_uninstall, _do_add_repo, _do_remove_repo,
_do_set_update_mode, _do_toggle_branch 등 핵심 서비스 로직 검증.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from conftest import make_hass, make_store, make_repo_item, make_github_client
from homeassistant.exceptions import HomeAssistantError


# ──────────────────────────────────────────────
# 공통 entry_data 목업
# ──────────────────────────────────────────────

def _make_entry_data(repos, store, github, coordinator=None):
    coord = coordinator or MagicMock()
    coord.repos = list(repos)
    coord.data = {}
    coord.async_request_refresh = AsyncMock()
    coord.async_update_listeners = MagicMock()
    return {
        "coordinator": coord,
        "github": github,
        "store": store,
    }


def _make_hass_with_entry(repos, store, github, coordinator=None):
    hass = make_hass()
    entry = MagicMock()
    entry.data = {"repos": list(repos)}

    ed = _make_entry_data(repos, store, github, coordinator)
    hass.data = {"private_hacs": {"entry": ed}}

    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    hass.config_entries.async_update_entry = MagicMock()

    # _get_entry, _get_entry_data, _require_entry_data 패치용
    return hass, entry, ed


# ══════════════════════════════════════════════════════════════════════
# 설치 (_do_install)
# ══════════════════════════════════════════════════════════════════════

class TestDoInstall:

    @pytest.mark.asyncio
    async def test_given_release_repo__when_install__then_store_saves_version(self):
        """
        Given: 릴리즈 저장소, latest=v2.0.0
        When:  _do_install 호출
        Then:  store에 installed_version="v2.0.0" 저장
        """
        from custom_components.private_hacs.services import _do_install

        store = make_store()
        github = AsyncMock()
        github.download_and_install = AsyncMock()

        coordinator = MagicMock()
        coordinator.repos = [make_repo_item()]
        coordinator.data = {
            "private_hacs@main": {
                "latest": {
                    "type": "release",
                    "version": "v2.0.0",
                    "download_ref": "v2.0.0",
                    "release_url": "https://github.com/x/releases/tag/v2.0.0",
                    "release_summary": None,
                    "commit_sha": None,
                    "remote_manifest_version": None,
                },
                "repo": "Murianwind/private_hacs",
            }
        }
        coordinator.async_request_refresh = AsyncMock()

        hass, entry, ed = _make_hass_with_entry(
            [make_repo_item()], store, github, coordinator
        )
        ed["coordinator"] = coordinator

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed), \
             patch("custom_components.private_hacs.services._require_entry_data", return_value=ed):
            await _do_install(hass, "private_hacs", "main")

        store.async_set_branch.assert_called()
        call_args = store.async_set_branch.call_args_list[0]
        assert call_args[0][0] == "private_hacs"
        assert call_args[0][1] == "main"
        assert "installed_version" in call_args[0][2]

    @pytest.mark.asyncio
    async def test_given_commit_repo__when_install__then_store_saves_sha(self):
        """
        Given: 커밋 추적 저장소, latest commit_sha 있음
        When:  _do_install 호출
        Then:  store에 installed_commit_sha 저장
        """
        from custom_components.private_hacs.services import _do_install

        store = make_store()
        github = AsyncMock()
        github.download_and_install = AsyncMock()

        sha = "abc123abc123"
        coordinator = MagicMock()
        coordinator.repos = [make_repo_item(update_mode="commit")]
        coordinator.data = {
            "private_hacs@main": {
                "latest": {
                    "type": "branch",
                    "version": "abc123",
                    "download_ref": "main",
                    "release_url": "https://github.com/x/commits/main",
                    "release_summary": None,
                    "commit_sha": sha,
                    "remote_manifest_version": None,
                },
                "repo": "Murianwind/private_hacs",
            }
        }
        coordinator.async_request_refresh = AsyncMock()

        hass, entry, ed = _make_hass_with_entry(
            [make_repo_item(update_mode="commit")], store, github, coordinator
        )
        ed["coordinator"] = coordinator

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed), \
             patch("custom_components.private_hacs.services._require_entry_data", return_value=ed):
            await _do_install(hass, "private_hacs", "main")

        # SHA 저장 확인
        all_calls = store.async_set_branch.call_args_list
        saved_data = all_calls[0][0][2]
        assert saved_data.get("installed_commit_sha") == sha

    @pytest.mark.asyncio
    async def test_given_two_branches__when_one_installed__then_other_branch_store_cleared(self):
        """
        Given: main + test 두 브랜치 등록, main 설치됨
        When:  test 브랜치 설치
        Then:  main의 installed_version/sha가 None으로 초기화
        """
        from custom_components.private_hacs.services import _do_install

        store = make_store({
            ("private_hacs", "main"): {
                "installed_version": "2.0.0",
                "installed_commit_sha": "oldsha",
            }
        })
        github = AsyncMock()
        github.download_and_install = AsyncMock()

        coordinator = MagicMock()
        coordinator.repos = [
            make_repo_item(branch="main"),
            make_repo_item(branch="test", update_mode="commit"),
        ]
        coordinator.data = {
            "private_hacs@test": {
                "latest": {
                    "type": "branch", "version": "newsha",
                    "download_ref": "test",
                    "release_url": "https://github.com/x/commits/test",
                    "release_summary": None, "commit_sha": "newsha999",
                    "remote_manifest_version": None,
                },
                "repo": "Murianwind/private_hacs",
            }
        }
        coordinator.async_request_refresh = AsyncMock()

        hass, entry, ed = _make_hass_with_entry(
            coordinator.repos, store, github, coordinator
        )
        ed["coordinator"] = coordinator

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed), \
             patch("custom_components.private_hacs.services._require_entry_data", return_value=ed):
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
        Given: ref="v1.0.0" 지정 설치 (릴리즈 선택 설치)
        When:  _do_install(ref="v1.0.0") 호출
        Then:  installed_version="v1.0.0", installed_commit_sha=None
        """
        from custom_components.private_hacs.services import _do_install

        store = make_store()
        github = AsyncMock()
        github.download_and_install = AsyncMock()

        coordinator = MagicMock()
        coordinator.repos = [make_repo_item()]
        coordinator.data = {
            "private_hacs@main": {
                "latest": {
                    "type": "release", "version": "v2.0.0",
                    "download_ref": "v2.0.0",
                    "release_url": "https://github.com/x/releases/tag/v2.0.0",
                    "release_summary": None, "commit_sha": None,
                    "remote_manifest_version": None,
                },
                "repo": "Murianwind/private_hacs",
            }
        }
        coordinator.async_request_refresh = AsyncMock()

        hass, entry, ed = _make_hass_with_entry(
            [make_repo_item()], store, github, coordinator
        )
        ed["coordinator"] = coordinator

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed), \
             patch("custom_components.private_hacs.services._require_entry_data", return_value=ed):
            await _do_install(hass, "private_hacs", "main", ref="v1.0.0")

        all_calls = store.async_set_branch.call_args_list
        saved = all_calls[0][0][2]
        assert saved["installed_version"] == "v1.0.0"
        assert saved.get("installed_commit_sha") is None


# ══════════════════════════════════════════════════════════════════════
# 등록 해제 (_do_remove_repo)
# ══════════════════════════════════════════════════════════════════════

class TestDoRemoveRepo:

    @pytest.mark.asyncio
    async def test_given_registered_branch__when_removed__then_removed_from_config(self):
        """
        Given: main 브랜치 등록됨
        When:  _do_remove_repo("private_hacs", "main") 호출
        Then:  config entry에서 해당 브랜치 제거
        """
        from custom_components.private_hacs.services import _do_remove_repo

        repos = [make_repo_item(branch="main", active=True)]
        store = make_store()
        github = AsyncMock()

        hass, entry, ed = _make_hass_with_entry(repos, store, github)
        entry.data = {"repos": list(repos)}

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed), \
             patch("custom_components.private_hacs.services.er.async_get", return_value=MagicMock(
                 async_get_entity_id=MagicMock(return_value=None)
             )):
            await _do_remove_repo(hass, "private_hacs", "main")

        hass.config_entries.async_update_entry.assert_called()
        updated_repos = hass.config_entries.async_update_entry.call_args[1]["data"]["repos"]
        assert not any(r["branch"] == "main" for r in updated_repos)

    @pytest.mark.asyncio
    async def test_given_active_branch_with_sibling__when_removed__then_sibling_auto_activated(self):
        """
        Given: main(활성) + test(비활성) 등록, main 제거
        When:  _do_remove_repo("private_hacs", "main") 호출
        Then:  test 브랜치 자동 활성화
        """
        from custom_components.private_hacs.services import _do_remove_repo

        repos = [
            make_repo_item(branch="main", active=True),
            make_repo_item(branch="test", active=False),
        ]
        store = make_store()
        github = AsyncMock()

        coordinator = MagicMock()
        coordinator.repos = list(repos)
        coordinator.data = {}
        coordinator.async_update_listeners = MagicMock()

        hass, entry, ed = _make_hass_with_entry(repos, store, github, coordinator)
        entry.data = {"repos": list(repos)}
        ed["coordinator"] = coordinator

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed), \
             patch("custom_components.private_hacs.services.er.async_get", return_value=MagicMock(
                 async_get_entity_id=MagicMock(return_value=None)
             )):
            await _do_remove_repo(hass, "private_hacs", "main")

        updated_repos = hass.config_entries.async_update_entry.call_args[1]["data"]["repos"]
        test_branch = next(r for r in updated_repos if r["branch"] == "test")
        assert test_branch["active"] is True

    @pytest.mark.asyncio
    async def test_given_unregistered_branch__when_removed__then_raises_error(self):
        """
        Given: 등록되지 않은 브랜치
        When:  _do_remove_repo 호출
        Then:  HomeAssistantError 발생
        """
        from custom_components.private_hacs.services import _do_remove_repo

        repos = [make_repo_item(branch="main")]
        store = make_store()
        github = AsyncMock()
        hass, entry, ed = _make_hass_with_entry(repos, store, github)
        entry.data = {"repos": list(repos)}

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed):
            with pytest.raises(HomeAssistantError):
                await _do_remove_repo(hass, "private_hacs", "nonexistent")


# ══════════════════════════════════════════════════════════════════════
# update_mode 변경 (_do_set_update_mode)
# ══════════════════════════════════════════════════════════════════════

class TestDoSetUpdateMode:

    @pytest.mark.asyncio
    async def test_given_release_mode__when_changed_to_commit__then_config_updated(self):
        """
        Given: main 브랜치 update_mode=release
        When:  _do_set_update_mode("commit") 호출
        Then:  config entry의 update_mode=commit 으로 갱신
        """
        from custom_components.private_hacs.services import _do_set_update_mode

        repos = [make_repo_item(update_mode="release")]
        store = make_store()
        github = AsyncMock()

        coordinator = MagicMock()
        coordinator.repos = list(repos)
        coordinator.data = {"private_hacs@main": {"update_mode": "release"}}
        coordinator.async_update_listeners = MagicMock()
        coordinator.async_request_refresh = AsyncMock()

        hass, entry, ed = _make_hass_with_entry(repos, store, github, coordinator)
        entry.data = {"repos": list(repos)}
        ed["coordinator"] = coordinator

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed):
            await _do_set_update_mode(hass, "private_hacs", "main", "commit")

        updated_repos = hass.config_entries.async_update_entry.call_args[1]["data"]["repos"]
        updated = next(r for r in updated_repos if r["branch"] == "main")
        assert updated["update_mode"] == "commit"

    @pytest.mark.asyncio
    async def test_given_commit_mode__when_changed_to_release__then_config_updated(self):
        """
        Given: test 브랜치 update_mode=commit
        When:  _do_set_update_mode("release") 호출
        Then:  config entry의 update_mode=release 로 갱신
        """
        from custom_components.private_hacs.services import _do_set_update_mode

        repos = [make_repo_item(branch="test", update_mode="commit")]
        store = make_store()
        github = AsyncMock()

        coordinator = MagicMock()
        coordinator.repos = list(repos)
        coordinator.data = {"private_hacs@test": {"update_mode": "commit"}}
        coordinator.async_update_listeners = MagicMock()
        coordinator.async_request_refresh = AsyncMock()

        hass, entry, ed = _make_hass_with_entry(repos, store, github, coordinator)
        entry.data = {"repos": list(repos)}
        ed["coordinator"] = coordinator

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed):
            await _do_set_update_mode(hass, "private_hacs", "test", "release")

        updated_repos = hass.config_entries.async_update_entry.call_args[1]["data"]["repos"]
        updated = next(r for r in updated_repos if r["branch"] == "test")
        assert updated["update_mode"] == "release"

    @pytest.mark.asyncio
    async def test_given_nonexistent_branch__when_set_update_mode__then_raises_error(self):
        """
        Given: 등록되지 않은 브랜치
        When:  _do_set_update_mode 호출
        Then:  HomeAssistantError 발생
        """
        from custom_components.private_hacs.services import _do_set_update_mode

        repos = [make_repo_item()]
        store = make_store()
        github = AsyncMock()
        hass, entry, ed = _make_hass_with_entry(repos, store, github)
        entry.data = {"repos": list(repos)}

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed):
            with pytest.raises(HomeAssistantError):
                await _do_set_update_mode(hass, "private_hacs", "nonexistent", "commit")


# ══════════════════════════════════════════════════════════════════════
# 저장소 추가 (_do_add_repo)
# ══════════════════════════════════════════════════════════════════════

class TestDoAddRepo:

    @pytest.mark.asyncio
    async def test_given_valid_repo__when_added__then_saved_to_config(self):
        """
        Given: 유효한 저장소, github.get_repo_info 성공
        When:  _do_add_repo 호출
        Then:  config entry에 저장소 추가
        """
        from custom_components.private_hacs.services import _do_add_repo

        repos = []
        store = make_store()
        github = AsyncMock()
        github.get_repo_info = AsyncMock(return_value={
            "name": "private_hacs",
            "default_branch": "main",
        })

        coordinator = MagicMock()
        coordinator.repos = []
        coordinator.async_request_refresh = AsyncMock()
        coordinator.async_update_listeners = MagicMock()

        hass, entry, ed = _make_hass_with_entry(repos, store, github, coordinator)
        entry.data = {"repos": []}
        ed["coordinator"] = coordinator
        ed["async_add_entities"] = MagicMock()

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed), \
             patch("custom_components.private_hacs.services._require_entry_data", return_value=ed):
            await _do_add_repo(
                hass,
                repo="Murianwind/private_hacs",
                name="Private HACS",
                component_id="private_hacs",
                branch="main",
                update_mode="release",
            )

        updated_repos = hass.config_entries.async_update_entry.call_args[1]["data"]["repos"]
        assert any(r["component_id"] == "private_hacs" for r in updated_repos)

    @pytest.mark.asyncio
    async def test_given_nonexistent_repo__when_added__then_raises_error(self):
        """
        Given: 존재하지 않는 저장소 (get_repo_info → None)
        When:  _do_add_repo 호출
        Then:  HomeAssistantError 발생
        """
        from custom_components.private_hacs.services import _do_add_repo

        repos = []
        store = make_store()
        github = AsyncMock()
        github.get_repo_info = AsyncMock(return_value=None)

        hass, entry, ed = _make_hass_with_entry(repos, store, github)
        entry.data = {"repos": []}

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed), \
             patch("custom_components.private_hacs.services._require_entry_data", return_value=ed):
            with pytest.raises(HomeAssistantError):
                await _do_add_repo(
                    hass,
                    repo="Murianwind/nonexistent",
                    name="없는 저장소",
                    component_id="nonexistent",
                    branch="main",
                    update_mode="release",
                )

    @pytest.mark.asyncio
    async def test_given_duplicate_branch__when_added__then_raises_error(self):
        """
        Given: 이미 동일 component_id + branch 등록됨
        When:  _do_add_repo 호출
        Then:  HomeAssistantError 발생
        """
        from custom_components.private_hacs.services import _do_add_repo

        existing = make_repo_item(branch="main")
        repos = [existing]
        store = make_store()
        github = AsyncMock()
        github.get_repo_info = AsyncMock(return_value={"name": "private_hacs"})

        hass, entry, ed = _make_hass_with_entry(repos, store, github)
        entry.data = {"repos": list(repos)}

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed), \
             patch("custom_components.private_hacs.services._require_entry_data", return_value=ed):
            with pytest.raises(HomeAssistantError):
                await _do_add_repo(
                    hass,
                    repo="Murianwind/private_hacs",
                    name="Private HACS",
                    component_id="private_hacs",
                    branch="main",
                    update_mode="release",
                )

    @pytest.mark.asyncio
    async def test_given_commit_mode_added__when_polled__then_uses_commit_tracking(self):
        """
        Given: update_mode=commit으로 브랜치 추가
        When:  config entry 확인
        Then:  update_mode=commit 저장됨
        """
        from custom_components.private_hacs.services import _do_add_repo

        repos = [make_repo_item(branch="main", update_mode="release")]
        store = make_store()
        github = AsyncMock()
        github.get_repo_info = AsyncMock(return_value={"name": "private_hacs"})

        coordinator = MagicMock()
        coordinator.repos = list(repos)
        coordinator.async_request_refresh = AsyncMock()
        coordinator.async_update_listeners = MagicMock()

        hass, entry, ed = _make_hass_with_entry(repos, store, github, coordinator)
        entry.data = {"repos": list(repos)}
        ed["coordinator"] = coordinator
        ed["async_add_entities"] = MagicMock()

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed), \
             patch("custom_components.private_hacs.services._require_entry_data", return_value=ed):
            await _do_add_repo(
                hass,
                repo="Murianwind/private_hacs",
                name="Private HACS",
                component_id="private_hacs",
                branch="test",
                update_mode="commit",
            )

        updated_repos = hass.config_entries.async_update_entry.call_args[1]["data"]["repos"]
        test_branch = next(r for r in updated_repos if r["branch"] == "test")
        assert test_branch["update_mode"] == "commit"


# ══════════════════════════════════════════════════════════════════════
# 컴포넌트 삭제 (_do_uninstall)
# ══════════════════════════════════════════════════════════════════════

class TestDoUninstall:

    @pytest.mark.asyncio
    async def test_given_installed_component__when_uninstalled__then_store_cleared(self):
        """
        Given: private_hacs 설치됨 (coordinator.data 있음)
        When:  _do_uninstall 호출
        Then:  github.uninstall 호출, store.async_remove 호출
        """
        from custom_components.private_hacs.services import _do_uninstall

        store = make_store({
            ("private_hacs", "main"): {"installed_version": "2.0.0"}
        })
        github = AsyncMock()
        github.uninstall = AsyncMock()

        coordinator = MagicMock()
        coordinator.data = {"private_hacs@main": {"component_id": "private_hacs"}}
        coordinator.async_request_refresh = AsyncMock()

        hass, entry, ed = _make_hass_with_entry(
            [make_repo_item()], store, github, coordinator
        )
        ed["coordinator"] = coordinator

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed), \
             patch("custom_components.private_hacs.services._require_entry_data", return_value=ed):
            await _do_uninstall(hass, "private_hacs")

        github.uninstall.assert_called_once()
        store.async_remove.assert_called_once_with("private_hacs")

    @pytest.mark.asyncio
    async def test_given_nonexistent_component__when_uninstalled__then_raises_error(self):
        """
        Given: coordinator.data에 없는 component_id
        When:  _do_uninstall 호출
        Then:  HomeAssistantError 발생
        """
        from custom_components.private_hacs.services import _do_uninstall

        store = make_store()
        github = AsyncMock()

        coordinator = MagicMock()
        coordinator.data = {}

        hass, entry, ed = _make_hass_with_entry([], store, github, coordinator)
        ed["coordinator"] = coordinator

        with patch("custom_components.private_hacs.services._get_entry", return_value=entry), \
             patch("custom_components.private_hacs.services._get_entry_data", return_value=ed), \
             patch("custom_components.private_hacs.services._require_entry_data", return_value=ed):
            with pytest.raises(HomeAssistantError):
                await _do_uninstall(hass, "nonexistent")


# ══════════════════════════════════════════════════════════════════════
# 커스텀 컴포넌트 이미 설치된 상태에서 저장소 추가
# ══════════════════════════════════════════════════════════════════════

class TestPreinstalledComponent:

    @pytest.mark.asyncio
    async def test_given_preinstalled_component__when_repo_added__then_update_detected_after_poll(self):
        """
        Given: 디스크에 커스텀 컴포넌트 이미 설치됨, 저장소 새로 등록
        When:  coordinator 폴링 (active 브랜치, manifest로 버전 감지)
        Then:  최신 버전과 비교해 has_update 정확히 판단
        """
        from custom_components.private_hacs.coordinator import PrivateHacsCoordinator, make_entry_key

        hass = make_hass()
        # manifest에서 2.0.0 읽음
        hass.async_add_executor_job = AsyncMock(return_value="2.0.0")

        store = make_store()  # store는 비어있음 (새로 등록)
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

        with patch.object(coord, "_read_manifest_version_sync", return_value="2.0.0"):
            hass.async_add_executor_job = AsyncMock(return_value="2.0.0")
            result = await coord._async_update_data()

        entry_key = make_entry_key("private_hacs", "main")
        assert result[entry_key]["installed_version"] == "2.0.0"
        assert result[entry_key]["has_update"] is True
