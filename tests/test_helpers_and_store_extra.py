"""
tests/test_helpers_and_store_extra.py
helpers.py와 store.py 추가 커버리지
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.private_hacs.helpers import normalize_repo_config
from custom_components.private_hacs.store import RepositoryStore


# ══════════════════════════════════════════════════════════════════════
# normalize_repo_config
# ══════════════════════════════════════════════════════════════════════

def test_normalize_repo_config__given_missing_active__when_called__then_defaults_to_true():
    """
    Given: active 필드 없는 레거시 설정
    When:  normalize_repo_config 호출
    Then:  active=True 자동 추가
    """
    repos = [{"repo": "x/y", "component_id": "y", "branch": "main"}]
    result = normalize_repo_config(repos)
    assert result[0]["active"] is True


def test_normalize_repo_config__given_active_false__when_called__then_preserved():
    """
    Given: active=False 명시된 항목
    When:  normalize_repo_config 호출
    Then:  active=False 유지
    """
    repos = [{"repo": "x/y", "component_id": "y", "branch": "main", "active": False}]
    result = normalize_repo_config(repos)
    assert result[0]["active"] is False


def test_normalize_repo_config__given_empty_list__when_called__then_returns_empty():
    """
    Given: 빈 목록
    When:  normalize_repo_config 호출
    Then:  빈 목록 반환
    """
    assert normalize_repo_config([]) == []


def test_normalize_repo_config__given_mixed_list__when_called__then_all_normalized():
    """
    Given: active 있는 항목과 없는 항목 혼재
    When:  normalize_repo_config 호출
    Then:  모두 active 필드 보유
    """
    repos = [
        {"repo": "x/a", "component_id": "a"},
        {"repo": "x/b", "component_id": "b", "active": False},
        {"repo": "x/c", "component_id": "c", "active": True},
    ]
    result = normalize_repo_config(repos)
    assert all("active" in r for r in result)
    assert result[0]["active"] is True
    assert result[1]["active"] is False
    assert result[2]["active"] is True


# ══════════════════════════════════════════════════════════════════════
# RepositoryStore 추가 테스트
# ══════════════════════════════════════════════════════════════════════

def _make_store(data: dict) -> RepositoryStore:
    hass = MagicMock()
    store = RepositoryStore(hass)
    store._data = data
    store._store = MagicMock()
    store._store.async_save = AsyncMock()
    store._store.async_load = AsyncMock(return_value=data)
    return store


def test_store_get__given_component_exists__when_called__then_returns_all_branches():
    """
    Given: private_hacs에 main + test 브랜치 데이터
    When:  get("private_hacs") 호출 (레거시 compat)
    Then:  전체 브랜치 딕셔너리 반환
    """
    store = _make_store({
        "private_hacs": {
            "main": {"installed_version": "2.0.0"},
            "test": {"installed_version": "1.0.0"},
        }
    })
    result = store.get("private_hacs")
    assert "main" in result
    assert "test" in result


def test_store_all__given_multiple_components__when_called__then_returns_all():
    """
    Given: 여러 컴포넌트 데이터
    When:  all() 호출
    Then:  전체 데이터 반환
    """
    data = {
        "private_hacs": {"main": {"installed_version": "2.0.0"}},
        "korea_gasapp": {"main": {"installed_version": "3.0.7"}},
    }
    store = _make_store(data)
    result = store.all()
    assert "private_hacs" in result
    assert "korea_gasapp" in result


@pytest.mark.asyncio
async def test_store_async_load__given_legacy_data__when_loaded__then_migrated():
    """
    Given: 레거시 flat 구조 데이터
    When:  async_load 호출
    Then:  main 브랜치로 마이그레이션
    """
    legacy = {"private_hacs": {"installed_version": "1.0.4"}}
    hass = MagicMock()
    store = RepositoryStore(hass)
    store._store = MagicMock()
    store._store.async_load = AsyncMock(return_value=legacy)

    await store.async_load()

    assert "main" in store._data["private_hacs"]
    assert store._data["private_hacs"]["main"]["installed_version"] == "1.0.4"


@pytest.mark.asyncio
async def test_store_async_load__given_none_data__when_loaded__then_empty():
    """
    Given: 저장된 데이터 없음 (첫 실행)
    When:  async_load 호출
    Then:  _data 빈 dict 유지
    """
    hass = MagicMock()
    store = RepositoryStore(hass)
    store._store = MagicMock()
    store._store.async_load = AsyncMock(return_value=None)

    await store.async_load()

    assert store._data == {}
