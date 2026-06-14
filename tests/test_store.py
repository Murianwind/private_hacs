"""
tests/test_store.py
RepositoryStore 단위 테스트

브랜치별 설치 기록 저장/읽기/삭제 및 레거시 마이그레이션 검증.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.private_hacs.store import RepositoryStore


def _make_store_with_data(data: dict) -> RepositoryStore:
    hass = MagicMock()
    store = RepositoryStore(hass)
    store._data = data
    store._store = MagicMock()
    store._store.async_save = AsyncMock()
    store._store.async_load = AsyncMock(return_value=data)
    return store


# ══════════════════════════════════════════════════════════════════════
# get_branch / installed_version
# ══════════════════════════════════════════════════════════════════════

def test_get_branch__given_data_exists__when_accessed__then_returns_branch_data():
    """
    Given: private_hacs / main 브랜치 데이터 있음
    When:  get_branch("private_hacs", "main") 호출
    Then:  해당 데이터 반환
    """
    store = _make_store_with_data({
        "private_hacs": {
            "main": {"installed_version": "2.0.0", "installed_commit_sha": "abc"}
        }
    })
    result = store.get_branch("private_hacs", "main")
    assert result["installed_version"] == "2.0.0"
    assert result["installed_commit_sha"] == "abc"


def test_get_branch__given_no_data__when_accessed__then_returns_empty_dict():
    """
    Given: 데이터 없음
    When:  get_branch 호출
    Then:  빈 딕셔너리 반환
    """
    store = _make_store_with_data({})
    result = store.get_branch("nonexistent", "main")
    assert result == {}


def test_installed_version__given_version_stored__when_accessed__then_returns_version():
    """
    Given: installed_version 저장됨
    When:  installed_version 호출
    Then:  버전 문자열 반환
    """
    store = _make_store_with_data({
        "private_hacs": {"main": {"installed_version": "1.0.4"}}
    })
    assert store.installed_version("private_hacs", "main") == "1.0.4"


def test_installed_version__given_no_version__when_accessed__then_returns_none():
    """
    Given: installed_version 없음
    When:  installed_version 호출
    Then:  None 반환
    """
    store = _make_store_with_data({})
    assert store.installed_version("private_hacs", "main") is None


# ══════════════════════════════════════════════════════════════════════
# async_set_branch
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_async_set_branch__given_new_data__when_set__then_data_persisted():
    """
    Given: 새 설치 데이터
    When:  async_set_branch 호출
    Then:  내부 데이터 갱신, async_save 호출
    """
    store = _make_store_with_data({})

    await store.async_set_branch(
        "private_hacs", "main",
        {"installed_version": "2.0.0", "installed_commit_sha": "abc123"}
    )

    assert store._data["private_hacs"]["main"]["installed_version"] == "2.0.0"
    assert store._data["private_hacs"]["main"]["installed_commit_sha"] == "abc123"
    store._store.async_save.assert_called()


@pytest.mark.asyncio
async def test_async_set_branch__given_existing_data__when_updated__then_merged():
    """
    Given: 기존 데이터 있음
    When:  async_set_branch로 일부 필드 업데이트
    Then:  기존 필드 유지, 새 필드 추가
    """
    store = _make_store_with_data({
        "private_hacs": {"main": {"installed_version": "1.0.0"}}
    })

    await store.async_set_branch(
        "private_hacs", "main",
        {"installed_commit_sha": "newsha"}
    )

    assert store._data["private_hacs"]["main"]["installed_version"] == "1.0.0"
    assert store._data["private_hacs"]["main"]["installed_commit_sha"] == "newsha"


@pytest.mark.asyncio
async def test_async_set_branch__given_none_values__when_cleared__then_none_stored():
    """
    Given: 설치 기록 있음
    When:  installed_version=None, installed_commit_sha=None으로 초기화
    Then:  None 값 저장 (다른 브랜치 설치 후 기록 초기화)
    """
    store = _make_store_with_data({
        "private_hacs": {"main": {"installed_version": "2.0.0", "installed_commit_sha": "abc"}}
    })

    await store.async_set_branch(
        "private_hacs", "main",
        {"installed_version": None, "installed_commit_sha": None}
    )

    assert store._data["private_hacs"]["main"]["installed_version"] is None
    assert store._data["private_hacs"]["main"]["installed_commit_sha"] is None


# ══════════════════════════════════════════════════════════════════════
# async_remove_branch / async_remove
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_async_remove_branch__given_two_branches__when_one_removed__then_other_remains():
    """
    Given: main + test 두 브랜치 데이터
    When:  async_remove_branch("test") 호출
    Then:  test 제거, main 유지
    """
    store = _make_store_with_data({
        "private_hacs": {
            "main": {"installed_version": "2.0.0"},
            "test": {"installed_version": "1.0.0"},
        }
    })

    await store.async_remove_branch("private_hacs", "test")

    assert "test" not in store._data["private_hacs"]
    assert "main" in store._data["private_hacs"]


@pytest.mark.asyncio
async def test_async_remove_branch__given_last_branch__when_removed__then_component_removed():
    """
    Given: main 브랜치만 있음
    When:  async_remove_branch("main") 호출
    Then:  component_id 전체 제거
    """
    store = _make_store_with_data({
        "private_hacs": {"main": {"installed_version": "2.0.0"}}
    })

    await store.async_remove_branch("private_hacs", "main")

    assert "private_hacs" not in store._data


@pytest.mark.asyncio
async def test_async_remove__given_component_exists__when_removed__then_all_branches_removed():
    """
    Given: private_hacs의 main + test 두 브랜치
    When:  async_remove("private_hacs") 호출
    Then:  전체 제거
    """
    store = _make_store_with_data({
        "private_hacs": {
            "main": {"installed_version": "2.0.0"},
            "test": {"installed_version": "1.0.0"},
        }
    })

    await store.async_remove("private_hacs")

    assert "private_hacs" not in store._data


# ══════════════════════════════════════════════════════════════════════
# 레거시 마이그레이션
# ══════════════════════════════════════════════════════════════════════

def test_migrate__given_legacy_flat_layout__when_migrated__then_wrapped_under_main():
    """
    Given: 구버전 레이아웃 {component_id: {installed_version: ...}}
    When:  _migrate 호출
    Then:  {component_id: {main: {installed_version: ...}}} 로 변환
    """
    legacy = {
        "private_hacs": {"installed_version": "1.0.4", "installed_commit_sha": None}
    }

    result = RepositoryStore._migrate(legacy)

    assert "main" in result["private_hacs"]
    assert result["private_hacs"]["main"]["installed_version"] == "1.0.4"


def test_migrate__given_new_layout__when_migrated__then_unchanged():
    """
    Given: 신버전 레이아웃 (이미 중첩 구조)
    When:  _migrate 호출
    Then:  변경 없이 그대로 반환
    """
    new_layout = {
        "private_hacs": {
            "main": {"installed_version": "2.0.0"},
            "test": {"installed_version": "1.0.0"},
        }
    }

    result = RepositoryStore._migrate(new_layout)

    assert result == new_layout


def test_migrate__given_mixed_layout__when_migrated__then_only_legacy_converted():
    """
    Given: 레거시 + 신버전 혼재
    When:  _migrate 호출
    Then:  레거시만 변환, 신버전 유지
    """
    mixed = {
        "old_component": {"installed_version": "1.0.0"},  # 레거시
        "new_component": {"main": {"installed_version": "2.0.0"}},  # 신버전
    }

    result = RepositoryStore._migrate(mixed)

    assert "main" in result["old_component"]
    assert result["new_component"] == {"main": {"installed_version": "2.0.0"}}
