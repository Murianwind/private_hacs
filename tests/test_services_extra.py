"""
tests/test_services_extra.py
서비스 추가 테스트 — _do_toggle_branch, _do_refresh,
_do_get_repo_info, _do_get_releases, _do_get_readme 커버리지 확보
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.private_hacs.services import (
    _do_toggle_branch, _do_refresh, _do_uninstall,
    _do_get_repo_info, _do_get_releases, _do_get_readme,
    _do_add_repo, _do_remove_repo,
)
from custom_components.private_hacs.const import DOMAIN, CONF_REPOS
from custom_components.private_hacs.coordinator import make_entry_key
from homeassistant.exceptions import HomeAssistantError
from conftest import make_store, make_repo_item, make_hass_for_services


# ══════════════════════════════════════════════════════════════════════
# _do_toggle_branch
# ══════════════════════════════════════════════════════════════════════

class TestDoToggleBranch:

    @pytest.mark.asyncio
    async def test_given_inactive_branch__when_activated__then_config_updated(self):
        """
        Given: test 브랜치 비활성
        When:  _do_toggle_branch(active=True) 호출
        Then:  config entry에서 test 브랜치 active=True
        """
        repos = [
            make_repo_item(branch="main", active=True),
            make_repo_item(branch="test", active=False),
        ]
        store = make_store()
        github = AsyncMock()
        coord = MagicMock()
        coord.repos = list(repos)
        coord.data = {
            make_entry_key("private_hacs", "main"): {"active": True},
            make_entry_key("private_hacs", "test"): {"active": False},
        }
        coord.async_update_listeners = MagicMock()
        coord.async_request_refresh = AsyncMock()

        hass, entry, _, _ = make_hass_for_services(repos, store, github, coord, coord.data)

        await _do_toggle_branch(hass, "private_hacs", "test", True)

        test_repo = next(r for r in entry.data[CONF_REPOS] if r["branch"] == "test")
        assert test_repo["active"] is True

    @pytest.mark.asyncio
    async def test_given_active_branch__when_activated__then_siblings_deactivated(self):
        """
        Given: main(활성) + test(비활성), test 활성화 요청
        When:  _do_toggle_branch(branch="test", active=True) 호출
        Then:  main이 비활성화됨
        """
        repos = [
            make_repo_item(branch="main", active=True),
            make_repo_item(branch="test", active=False),
        ]
        store = make_store()
        github = AsyncMock()
        coord = MagicMock()
        coord.repos = list(repos)
        coord.data = {
            make_entry_key("private_hacs", "main"): {"active": True},
            make_entry_key("private_hacs", "test"): {"active": False},
        }
        coord.async_update_listeners = MagicMock()
        coord.async_request_refresh = AsyncMock()

        hass, entry, _, _ = make_hass_for_services(repos, store, github, coord, coord.data)

        await _do_toggle_branch(hass, "private_hacs", "test", True)

        main_repo = next(r for r in entry.data[CONF_REPOS] if r["branch"] == "main")
        assert main_repo["active"] is False

    @pytest.mark.asyncio
    async def test_given_nonexistent_branch__when_toggled__then_raises_error(self):
        """
        Given: 존재하지 않는 브랜치
        When:  _do_toggle_branch 호출
        Then:  HomeAssistantError 발생
        """
        repos = [make_repo_item(branch="main")]
        store = make_store()
        github = AsyncMock()
        hass, _, _, _ = make_hass_for_services(repos, store, github)

        with pytest.raises(HomeAssistantError):
            await _do_toggle_branch(hass, "private_hacs", "nonexistent", True)

    @pytest.mark.asyncio
    async def test_given_active_branch__when_deactivated__then_no_refresh(self):
        """
        Given: 활성 브랜치
        When:  _do_toggle_branch(active=False) 호출
        Then:  coordinator.async_request_refresh 미호출 (비활성화 시 refresh 불필요)
        """
        repos = [make_repo_item(branch="main", active=True)]
        store = make_store()
        github = AsyncMock()
        coord = MagicMock()
        coord.repos = list(repos)
        coord.data = {make_entry_key("private_hacs", "main"): {"active": True}}
        coord.async_update_listeners = MagicMock()
        coord.async_request_refresh = AsyncMock()

        hass, _, _, _ = make_hass_for_services(repos, store, github, coord, coord.data)

        await _do_toggle_branch(hass, "private_hacs", "main", False)

        coord.async_request_refresh.assert_not_called()


# ══════════════════════════════════════════════════════════════════════
# _do_refresh
# ══════════════════════════════════════════════════════════════════════

class TestDoRefresh:

    @pytest.mark.asyncio
    async def test_given_coordinator_exists__when_refresh__then_request_refresh_called(self):
        """
        Given: coordinator 있음
        When:  _do_refresh 호출
        Then:  coordinator.async_request_refresh 호출됨
        """
        repos = [make_repo_item()]
        store = make_store()
        github = AsyncMock()
        coord = MagicMock()
        coord.repos = list(repos)
        coord.data = {}
        coord.async_request_refresh = AsyncMock()

        hass, _, _, _ = make_hass_for_services(repos, store, github, coord, {})

        await _do_refresh(hass)

        coord.async_request_refresh.assert_called_once()


# ══════════════════════════════════════════════════════════════════════
# _do_get_repo_info
# ══════════════════════════════════════════════════════════════════════

class TestDoGetRepoInfo:

    @pytest.mark.asyncio
    async def test_given_valid_repo__when_get_info__then_returns_info(self):
        """
        Given: 유효한 저장소
        When:  _do_get_repo_info 호출
        Then:  저장소 정보 반환
        """
        repos = []
        store = make_store()
        github = AsyncMock()
        github.get_repo_info = AsyncMock(return_value={
            "name": "private_hacs", "default_branch": "main",
            "description": "test"
        })
        github.get_branches = AsyncMock(return_value=["main", "test"])

        hass, _, _, _ = make_hass_for_services(repos, store, github)

        result = await _do_get_repo_info(hass, "Murianwind/private_hacs")

        assert result is not None
        assert "branches" in result

    @pytest.mark.asyncio
    async def test_given_nonexistent_repo__when_get_info__then_raises_error(self):
        """
        Given: 존재하지 않는 저장소 (get_repo_info → None)
        When:  _do_get_repo_info 호출
        Then:  HomeAssistantError 발생
        """
        repos = []
        store = make_store()
        github = AsyncMock()
        github.get_repo_info = AsyncMock(return_value=None)

        hass, _, _, _ = make_hass_for_services(repos, store, github)

        with pytest.raises(HomeAssistantError):
            await _do_get_repo_info(hass, "Murianwind/nonexistent")


# ══════════════════════════════════════════════════════════════════════
# _do_get_releases
# ══════════════════════════════════════════════════════════════════════

class TestDoGetReleases:

    @pytest.mark.asyncio
    async def test_given_registered_repo__when_get_releases__then_returns_list(self):
        """
        Given: 등록된 저장소, 릴리즈 있음
        When:  _do_get_releases 호출
        Then:  릴리즈 목록 반환
        """
        repos = [make_repo_item(branch="main")]
        store = make_store()
        github = AsyncMock()
        github.get_releases = AsyncMock(return_value=[
            {"tag_name": "v2.0.0", "name": "v2.0.0",
             "published_at": "2024-01-01", "html_url": "https://x",
             "prerelease": False, "target_commitish": "main"},
        ])

        coord = MagicMock()
        coord.repos = list(repos)
        coord.data = {make_entry_key("private_hacs", "main"): {"repo": "Murianwind/private_hacs"}}

        hass, _, _, _ = make_hass_for_services(repos, store, github, coord, coord.data)

        result = await _do_get_releases(hass, "private_hacs", "main")

        assert result is not None
        assert len(result["releases"]) == 1
        assert result["releases"][0]["tag_name"] == "v2.0.0"


# ══════════════════════════════════════════════════════════════════════
# _do_get_readme
# ══════════════════════════════════════════════════════════════════════

class TestDoGetReadme:

    @pytest.mark.asyncio
    async def test_given_repo_with_readme__when_get_readme__then_returns_content(self):
        """
        Given: README 있는 저장소
        When:  _do_get_readme 호출
        Then:  README 내용 반환
        """
        repos = [make_repo_item(branch="main")]
        store = make_store()
        github = AsyncMock()
        github.get_readme = AsyncMock(return_value="# Private HACS\n테스트 README")

        coord = MagicMock()
        coord.repos = list(repos)
        coord.data = {make_entry_key("private_hacs", "main"): {"repo": "Murianwind/private_hacs"}}

        hass, _, _, _ = make_hass_for_services(repos, store, github, coord, coord.data)

        result = await _do_get_readme(hass, "Murianwind/private_hacs", "main")

        assert result is not None
        assert "content" in result
        assert "Private HACS" in result["content"]

    @pytest.mark.asyncio
    async def test_given_repo_without_readme__when_get_readme__then_returns_fallback_message(self):
        """
        Given: README 없는 저장소 (get_readme → None)
        When:  _do_get_readme 호출
        Then:  content="README 내용을 찾을 수 없습니다." 반환
        """
        repos = [make_repo_item(branch="main")]
        store = make_store()
        github = AsyncMock()
        github.get_readme = AsyncMock(return_value=None)

        coord = MagicMock()
        coord.repos = list(repos)
        coord.data = {make_entry_key("private_hacs", "main"): {"repo": "Murianwind/private_hacs"}}

        hass, _, _, _ = make_hass_for_services(repos, store, github, coord, coord.data)

        result = await _do_get_readme(hass, "Murianwind/private_hacs", "main")

        assert result["content"] == "README 내용을 찾을 수 없습니다."


# ══════════════════════════════════════════════════════════════════════
# 에러 핸들링 분기 추가 커버리지
# ══════════════════════════════════════════════════════════════════════

class TestDoAddRepoErrors:

    @pytest.mark.asyncio
    async def test_given_get_repo_info_raises__when_add_repo__then_raises_error(self):
        """
        Given: get_repo_info가 예외 발생
        When:  _do_add_repo 호출
        Then:  HomeAssistantError 발생
        """
        repos = []
        store = make_store()
        github = AsyncMock()
        github.get_repo_info = AsyncMock(side_effect=Exception("네트워크 오류"))
        hass, _, _, _ = make_hass_for_services(repos, store, github)

        with pytest.raises(HomeAssistantError, match="저장소 조회 실패"):
            await _do_add_repo(
                hass, repo="Murianwind/private_hacs",
                name="Private HACS", component_id="private_hacs",
                branch="main", update_mode="release",
            )


class TestDoGetRepoInfoExtra:

    @pytest.mark.asyncio
    async def test_given_get_repo_info_raises__when_called__then_raises_error(self):
        """
        Given: get_repo_info 예외 발생
        When:  _do_get_repo_info 호출
        Then:  HomeAssistantError 발생
        """
        repos = []
        store = make_store()
        github = AsyncMock()
        github.get_repo_info = AsyncMock(side_effect=Exception("API 오류"))
        hass, _, _, _ = make_hass_for_services(repos, store, github)

        with pytest.raises(HomeAssistantError, match="저장소 조회 실패"):
            await _do_get_repo_info(hass, "Murianwind/private_hacs")

    @pytest.mark.asyncio
    async def test_given_get_contents_raises__when_called__then_still_returns(self):
        """
        Given: get_contents 예외 발생 (component_ids 조회 실패)
        When:  _do_get_repo_info 호출
        Then:  에러 없이 결과 반환 (component_ids 빈 목록)
        """
        repos = []
        store = make_store()
        github = AsyncMock()
        github.get_repo_info = AsyncMock(return_value={"name": "private_hacs", "default_branch": "main"})
        github.get_contents = AsyncMock(side_effect=Exception("권한 없음"))
        github.get_branches = AsyncMock(return_value=["main"])
        github.get_releases = AsyncMock(return_value=[])
        hass, _, _, _ = make_hass_for_services(repos, store, github)

        result = await _do_get_repo_info(hass, "Murianwind/private_hacs")

        assert result is not None
        assert result.get("component_ids") == []

    @pytest.mark.asyncio
    async def test_given_has_releases__when_called__then_has_releases_true(self):
        """
        Given: 릴리즈 있는 저장소
        When:  _do_get_repo_info 호출
        Then:  has_releases=True 반환
        """
        repos = []
        store = make_store()
        github = AsyncMock()
        github.get_repo_info = AsyncMock(return_value={"name": "private_hacs", "default_branch": "main"})
        github.get_contents = AsyncMock(return_value=[{"name": "private_hacs", "type": "dir"}])
        github.get_branches = AsyncMock(return_value=["main"])
        github.get_releases = AsyncMock(return_value=[{"tag_name": "v1.0.0"}])
        hass, _, _, _ = make_hass_for_services(repos, store, github)

        result = await _do_get_repo_info(hass, "Murianwind/private_hacs")

        assert result["has_releases"] is True
        assert "private_hacs" in result["component_ids"]


class TestDoUninstallErrors:

    @pytest.mark.asyncio
    async def test_given_uninstall_raises__when_called__then_raises_error(self):
        """
        Given: github.uninstall 예외 발생
        When:  _do_uninstall 호출
        Then:  HomeAssistantError 발생
        """
        repos = [make_repo_item()]
        store = make_store()
        github = AsyncMock()
        github.uninstall = AsyncMock(side_effect=Exception("삭제 실패"))

        coord = MagicMock()
        coord.repos = list(repos)
        coord.data = {"private_hacs@main": {"component_id": "private_hacs"}}
        coord.async_request_refresh = AsyncMock()

        hass, _, _, _ = make_hass_for_services(repos, store, github, coord, coord.data)

        with pytest.raises(HomeAssistantError, match="삭제 실패"):
            await _do_uninstall(hass, "private_hacs")


class TestDoRemoveRepoExtra:

    @pytest.mark.asyncio
    async def test_given_entity_id_exists__when_removed__then_entity_unregistered(self):
        """
        Given: entity registry에 entity_id 등록됨
        When:  _do_remove_repo 호출
        Then:  ent_reg.async_remove 호출됨
        """
        repos = [make_repo_item(branch="main", active=True)]
        store = make_store()
        github = AsyncMock()
        hass, entry, ed, coord = make_hass_for_services(repos, store, github)

        mock_ent_reg = MagicMock()
        mock_ent_reg.async_get_entity_id = MagicMock(return_value="update.private_hacs_main_update")
        mock_ent_reg.async_remove = MagicMock()

        with patch("custom_components.private_hacs.services.er") as mock_er:
            mock_er.async_get.return_value = mock_ent_reg
            await _do_remove_repo(hass, "private_hacs", "main")

        mock_ent_reg.async_remove.assert_called_once_with("update.private_hacs_main_update")
