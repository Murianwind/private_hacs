"""
tests/test_services.py
서비스 핸들러 단위 테스트 — Given/When/Then(BDD) 형식
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.private_hacs.services import (
    _do_install, _do_uninstall, _do_add_repo,
    _do_remove_repo, _do_set_update_mode,
)
from custom_components.private_hacs.const import DOMAIN, CONF_REPOS
from custom_components.private_hacs.coordinator import make_entry_key
from homeassistant.exceptions import HomeAssistantError
from conftest import make_store, make_repo_item, make_hass_for_services


@pytest.fixture(autouse=True)
def _patch_frontend_assets():
    """
    component_id="private_hacs"(DOMAIN)로 _do_install을 호출하는 모든
    테스트에서 self-install 분기(프론트엔드 자산 재생성)가 실행된다.
    실제 파일시스템에 쓰지 않도록 panel.async_ensure_frontend_assets를
    자동으로 patch한다.
    """
    with patch(
        "custom_components.private_hacs.panel.async_ensure_frontend_assets",
        AsyncMock(),
    ) as mocked:
        yield mocked


def _latest_release(version="v2.0.0"):
    return {
        "type": "release", "version": version, "download_ref": version,
        "release_url": f"https://github.com/x/releases/tag/{version}",
        "release_summary": None, "commit_sha": None, "remote_manifest_version": None,
    }

def _latest_commit(sha="abc123abc123", branch="main"):
    return {
        "type": "branch", "version": sha[:7], "download_ref": branch,
        "release_url": f"https://github.com/x/commits/{branch}",
        "release_summary": None, "commit_sha": sha, "remote_manifest_version": None,
    }

def _make_install_setup(repos, store, latest, branch="main"):
    """_do_install 테스트용 hass 셋업 — coordinator.data에 entry_key 주입.

    component_id="private_hacs"는 DOMAIN과 같으므로 _do_install의
    self-install 분기(프론트엔드 자산 재생성)가 항상 실행된다.
    실제 파일 I/O를 피하기 위해 panel.async_ensure_frontend_assets를
    자동으로 patch한다 — mock은 각 테스트 함수에서 patch 컨텍스트로
    감싸 쓰거나, 아래 헬퍼가 반환하는 patcher를 사용한다.
    """
    github = AsyncMock()
    github.download_and_install = AsyncMock()
    entry_key = make_entry_key("private_hacs", branch)
    coord = MagicMock()
    coord.repos = list(repos)
    coord.data = {entry_key: {"latest": latest, "repo": "Murianwind/private_hacs"}}
    coord.async_refresh = AsyncMock()
    hass, entry, ed, _ = make_hass_for_services(repos, store, github, coord, coord.data)
    return hass, entry, github


# ══════════════════════════════════════════════════════════════════════
# _do_install
# ══════════════════════════════════════════════════════════════════════

class TestDoInstall:

    @pytest.mark.asyncio
    async def test_given_release_repo__when_install__then_store_saves_version(self):
        """
        Given: 릴리즈 저장소, latest=v2.0.0
        When:  _do_install 호출
        Then:  store에 installed_version="v2.0.0" 저장
        """
        repos = [make_repo_item()]
        store = make_store()
        hass, _, _ = _make_install_setup(repos, store, _latest_release())

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
        store = make_store()
        hass, _, _ = _make_install_setup(repos, store, _latest_commit(sha))

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
        store = make_store({("private_hacs", "main"): {"installed_version": "2.0.0", "installed_commit_sha": "oldsha"}})
        hass, _, _ = _make_install_setup(repos, store, _latest_commit("newsha999", "test"), branch="test")

        await _do_install(hass, "private_hacs", "test")

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
        store = make_store()
        hass, _, _ = _make_install_setup(repos, store, _latest_release())

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
        coord.data = {}
        coord.async_refresh = AsyncMock()
        hass, _, _, _ = make_hass_for_services(repos, store, github, coord, {})

        with pytest.raises(HomeAssistantError):
            await _do_install(hass, "private_hacs", "main")

    @pytest.mark.asyncio
    async def test_given_self_install__when_install__then_frontend_assets_regenerated(
        self, _patch_frontend_assets
    ):
        """
        Given: component_id="private_hacs" (Private HACS 자기 자신 재설치)
        When:  _do_install 호출
        Then:  panel.async_ensure_frontend_assets가 호출됨.
               Private HACS 재설치는 custom_components/private_hacs/ 전체를
               git 저장소 내용으로 덮어써서 런타임 생성 파일(frontend/js/panel.js
               등)을 지우므로, HA 재시작 없이 패널이 계속 동작하려면 설치
               직후 이 재생성이 반드시 호출되어야 한다.
        """
        repos = [make_repo_item()]
        store = make_store()
        hass, _, _ = _make_install_setup(repos, store, _latest_release())

        await _do_install(hass, "private_hacs", "main")

        _patch_frontend_assets.assert_called_once_with(hass)

    @pytest.mark.asyncio
    async def test_given_other_component_install__when_install__then_frontend_assets_not_touched(
        self, _patch_frontend_assets
    ):
        """
        Given: component_id="my_lg" (Private HACS 자신이 아닌 다른 컴포넌트)
        When:  _do_install 호출
        Then:  panel.async_ensure_frontend_assets가 호출되지 않음
               (다른 컴포넌트 설치는 Private HACS 자신의 디렉토리를
                건드리지 않으므로 프론트엔드 자산이 삭제될 일이 없음)
        """
        repos = [make_repo_item(component_id="my_lg")]
        store = make_store()
        github = AsyncMock()
        github.download_and_install = AsyncMock()
        entry_key = make_entry_key("my_lg", "main")
        coord = MagicMock()
        coord.repos = list(repos)
        coord.data = {entry_key: {"latest": _latest_release(), "repo": "Murianwind/my_lg"}}
        coord.async_refresh = AsyncMock()
        hass, entry, ed, _ = make_hass_for_services(repos, store, github, coord, coord.data)

        await _do_install(hass, "my_lg", "main")

        _patch_frontend_assets.assert_not_called()

    @pytest.mark.asyncio
    async def test_given_self_install_and_regen_fails__when_install__then_install_still_succeeds(
        self, _patch_frontend_assets
    ):
        """
        Given: component_id="private_hacs", 프론트엔드 자산 재생성 중 예외 발생
        When:  _do_install 호출
        Then:  설치 자체는 예외 없이 완료됨 (재생성 실패가 설치 성공을 막지
               않아야 함 — 최악의 경우에도 사용자는 HA 재시작으로 복구 가능)
        """
        _patch_frontend_assets.side_effect = Exception("디스크 쓰기 실패")
        repos = [make_repo_item()]
        store = make_store()
        hass, _, _ = _make_install_setup(repos, store, _latest_release())

        await _do_install(hass, "private_hacs", "main")  # 예외 없이 완료되어야 함

        store.async_set_branch.assert_called()


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
        coord.async_refresh = AsyncMock()
        hass, entry, _, _ = make_hass_for_services(repos, store, github, coord, coord.data)

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
        coord.async_refresh = AsyncMock()
        hass, entry, _, _ = make_hass_for_services(repos, store, github, coord, coord.data)

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
        coord.async_refresh = AsyncMock()
        coord.async_update_listeners = MagicMock()
        hass, entry, ed, _ = make_hass_for_services(repos, store, github, coord, {})
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
        coord.async_refresh = AsyncMock()
        coord.async_update_listeners = MagicMock()
        hass, entry, ed, _ = make_hass_for_services(repos, store, github, coord, {})
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
        coord.async_refresh = AsyncMock()
        hass, _, _, _ = make_hass_for_services(repos, store, github, coord, coord.data)

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
        coord.async_refresh = AsyncMock()
        hass, _, _, _ = make_hass_for_services(repos, store, github, coord, {})

        with pytest.raises(HomeAssistantError):
            await _do_uninstall(hass, "nonexistent")
