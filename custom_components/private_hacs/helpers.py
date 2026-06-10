"""Shared helper utilities for Private HACS."""
from __future__ import annotations


def normalize_repo_config(repos: list[dict]) -> list[dict]:
    """
    active 필드가 없는 항목에 active=True를 명시적으로 추가.

    __init__.py(시작 시 정규화)와 services.py(서비스 호출 시 정규화)
    양쪽에서 사용하므로 순환 import를 피하기 위해 helpers.py에 위치.
    """
    result = []
    for r in repos:
        item = dict(r)
        if "active" not in item:
            item["active"] = True
        result.append(item)
    return result
