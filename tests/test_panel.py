"""
tests/test_panel.py
panel.py — 프론트엔드 정적 자산(panel.js, marked.min.js) 생성/복구 로직 테스트.

핵심 시나리오: Private HACS가 자기 자신을 재설치하면
custom_components/private_hacs/ 전체가 git 저장소 내용으로 교체되어
런타임 생성 파일(frontend/js/panel.js 등)이 삭제된다. 이를 HA 재시작
없이 즉시 복구하는 async_ensure_frontend_assets가 정상 동작하는지 검증한다.
"""
from __future__ import annotations

import os
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.private_hacs.panel import (
    async_ensure_frontend_assets,
    async_setup_panel,
    _write_panel_js_sync,
    _PANEL_JS,
    _REGISTERED_HASS_IDS,
)


def _make_hass_with_tmp_dir(tmp_path):
    """panel.py의 os.path.dirname(__file__) 위치를 우회하기 위해
    hass.async_add_executor_job만 실제 실행하고 나머지는 mock 처리."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    hass.http.async_register_static_paths = AsyncMock()
    hass.config.path = MagicMock(return_value=str(tmp_path / "custom_components"))
    return hass


class TestWritePanelJsSync:

    def test_given_no_existing_file__when_written__then_file_created_with_content(self, tmp_path):
        """
        Given: panel.js 파일이 아직 없음
        When:  _write_panel_js_sync 호출
        Then:  파일이 생성되고 _PANEL_JS 내용이 그대로 기록됨
        """
        target = tmp_path / "panel.js"
        _write_panel_js_sync(str(target))

        assert target.is_file()
        assert target.read_text(encoding="utf-8") == _PANEL_JS

    def test_given_file_deleted_by_self_reinstall__when_rewritten__then_recreated(self, tmp_path):
        """
        Given: panel.js가 존재했다가 (자기 자신 재설치로) 디렉토리째 삭제된 상황을
               재현 — 파일이 없는 디렉토리에 다시 씀
        When:  _write_panel_js_sync 재호출
        Then:  파일이 다시 생성됨 (재시작 없이 복구되는 핵심 동작)
        """
        target = tmp_path / "js" / "panel.js"
        os.makedirs(target.parent, exist_ok=True)
        _write_panel_js_sync(str(target))
        assert target.is_file()

        # 재설치로 디렉토리 전체가 삭제된 상황 재현
        target.unlink()
        os.rmdir(target.parent)
        assert not target.parent.exists()

        # 복구 시도 — 디렉토리를 다시 만들고 파일 재생성
        os.makedirs(target.parent, exist_ok=True)
        _write_panel_js_sync(str(target))

        assert target.is_file()
        assert target.read_text(encoding="utf-8") == _PANEL_JS

    def test_given_identical_content_already_present__when_rewritten__then_no_error(self, tmp_path):
        """
        Given: panel.js가 이미 최신 내용으로 존재
        When:  _write_panel_js_sync 재호출
        Then:  에러 없이 통과 (불필요한 재작성 스킵 로직 포함)
        """
        target = tmp_path / "panel.js"
        _write_panel_js_sync(str(target))
        # 두 번째 호출 — 예외 없이 완료되어야 함
        _write_panel_js_sync(str(target))
        assert target.read_text(encoding="utf-8") == _PANEL_JS


class TestAsyncEnsureFrontendAssets:

    @pytest.mark.asyncio
    async def test_given_missing_frontend_dir__when_called__then_recreates_js_files(self, tmp_path):
        """
        Given: frontend/js 디렉토리 자체가 없음 (자기 재설치 직후 상황)
        When:  async_ensure_frontend_assets 호출
        Then:  디렉토리와 panel.js가 다시 생성됨
        """
        hass = _make_hass_with_tmp_dir(tmp_path)

        fake_panel_dir = str(tmp_path / "frontend")
        fake_js_dir = os.path.join(fake_panel_dir, "js")

        with patch("custom_components.private_hacs.panel.os.path.dirname", return_value=str(tmp_path)), \
             patch("custom_components.private_hacs.panel._async_ensure_marked_js", AsyncMock()):
            await async_ensure_frontend_assets(hass)

        # frontend/js/panel.js가 생성되었어야 함
        expected_path = os.path.join(str(tmp_path), "frontend", "js", "panel.js")
        assert os.path.isfile(expected_path)
        with open(expected_path, encoding="utf-8") as f:
            assert f.read() == _PANEL_JS

    @pytest.mark.asyncio
    async def test_given_called_multiple_times__when_no_hass_restart__then_no_error(self, tmp_path):
        """
        Given: HA 재시작 없이 async_ensure_frontend_assets를 여러 번 호출
               (설치 서비스가 여러 번 실행되는 상황)
        When:  연속 호출
        Then:  매번 예외 없이 정상 동작 (이 함수는 _REGISTERED_HASS_IDS 가드에
               걸리지 않고 몇 번이든 재실행 가능해야 함)
        """
        hass = _make_hass_with_tmp_dir(tmp_path)

        with patch("custom_components.private_hacs.panel.os.path.dirname", return_value=str(tmp_path)), \
             patch("custom_components.private_hacs.panel._async_ensure_marked_js", AsyncMock()):
            await async_ensure_frontend_assets(hass)
            await async_ensure_frontend_assets(hass)
            await async_ensure_frontend_assets(hass)

        expected_path = os.path.join(str(tmp_path), "frontend", "js", "panel.js")
        assert os.path.isfile(expected_path)


class TestAsyncSetupPanel:

    @pytest.mark.asyncio
    async def test_given_first_call__when_setup__then_static_paths_registered(self, tmp_path):
        """
        Given: 아직 등록되지 않은 hass 인스턴스
        When:  async_setup_panel 호출
        Then:  정적 경로가 등록되고, async_ensure_frontend_assets가 호출됨
        """
        _REGISTERED_HASS_IDS.clear()
        hass = _make_hass_with_tmp_dir(tmp_path)

        with patch("custom_components.private_hacs.panel.os.path.dirname", return_value=str(tmp_path)), \
             patch("custom_components.private_hacs.panel.async_ensure_frontend_assets", AsyncMock()) as mocked_ensure:
            await async_setup_panel(hass)

        mocked_ensure.assert_called_once_with(hass)
        hass.http.async_register_static_paths.assert_called_once()

    @pytest.mark.asyncio
    async def test_given_already_registered__when_setup_called_again__then_skipped(self, tmp_path):
        """
        Given: 같은 hass 인스턴스로 이미 한 번 등록됨
        When:  async_setup_panel 재호출
        Then:  정적 경로 재등록/재생성 스킵 (hass당 1회만 등록되어야 함)
        """
        _REGISTERED_HASS_IDS.clear()
        hass = _make_hass_with_tmp_dir(tmp_path)

        with patch("custom_components.private_hacs.panel.os.path.dirname", return_value=str(tmp_path)), \
             patch("custom_components.private_hacs.panel.async_ensure_frontend_assets", AsyncMock()) as mocked_ensure:
            await async_setup_panel(hass)
            await async_setup_panel(hass)

        mocked_ensure.assert_called_once()
        hass.http.async_register_static_paths.assert_called_once()
