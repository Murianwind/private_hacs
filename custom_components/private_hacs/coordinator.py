"""DataUpdateCoordinator for Private HACS."""
from __future__ import annotations

import json
import logging
import os
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_REPOS, DEFAULT_SCAN_INTERVAL_HOURS, DOMAIN
from .github import GitHubClient
from .store import RepositoryStore

_LOGGER = logging.getLogger(__name__)

# update_mode 값
UPDATE_MODE_RELEASE = "release"   # 릴리즈/태그 기준 (기본값)
UPDATE_MODE_COMMIT  = "commit"    # 브랜치 HEAD 커밋 기준


def _strip_v(v: str) -> str:
    """버전 문자열에서 선행 'v'를 제거하여 정규화합니다. (예: v1.0 → 1.0)"""
    return v.lstrip("v") if v else v


def make_entry_key(component_id: str, branch: str) -> str:
    """Return the internal dict key for a (component_id, branch) pair."""
    return f"{component_id}@{branch}"


class PrivateHacsCoordinator(DataUpdateCoordinator):
    """Polls GitHub for the latest version of every registered repository."""

    def __init__(
        self,
        hass: HomeAssistant,
        repos: list[dict],
        github: GitHubClient,
        store: RepositoryStore,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=DEFAULT_SCAN_INTERVAL_HOURS),
        )
        self.repos = repos
        self.github = github
        self.store = store

    async def _async_update_data(self) -> dict[str, dict]:
        results: dict[str, dict] = {}

        # component_id별 설치 여부 / has_icon을 한 번만 확인
        installed_cache: dict[str, bool] = {}
        has_icon_cache: dict[str, bool] = {}

        for item in self.repos:
            repo: str = item["repo"]
            component_id: str = item["component_id"]
            branch: str = item.get("branch", "main")
            active: bool = item.get("active", True)
            update_mode: str = item.get("update_mode", UPDATE_MODE_RELEASE)
            entry_key = make_entry_key(component_id, branch)

            # 설치 여부: 캐시 활용
            if component_id not in installed_cache:
                installed_cache[component_id] = await self._check_installed(component_id)
            is_installed = installed_cache[component_id]

            # has_icon: component_id별 1회만 확인 (executor)
            if component_id not in has_icon_cache:
                icon_path = self.hass.config.path(
                    "custom_components", component_id, "brand", "icon.png"
                )
                has_icon_cache[component_id] = await self.hass.async_add_executor_job(
                    os.path.isfile, icon_path
                )

            # latest 조회
            # - update_mode=release: release → tag → branch 순 (기존 동작)
            # - update_mode=commit: branch HEAD만 조회
            #
            # commit 모드는 릴리즈를 아예 조회하지 않으므로, "이 저장소에
            # 릴리즈/태그가 있는지"는 패널 UI가 모드 전환 버튼을 보여줄지
            # 판단하는 데 별도로 필요하다. 릴리즈 유무는 한 번 확인되면
            # 사실상 바뀌지 않는 정보이므로(릴리즈가 생겼다가 전부
            # 사라지는 경우는 드묾) store에 캐시해두고, 캐시가 없을 때만
            # (False일 때만) 가볍게 재확인한다 — 매 폴링 API 호출을 피한다.
            try:
                if update_mode == UPDATE_MODE_COMMIT:
                    latest = await self.github.resolve_branch_latest(
                        repo, component_id, branch
                    )
                    if latest is not None:
                        store_entry_for_cache = self.store.get_branch(component_id, branch)
                        cached_has_release = store_entry_for_cache.get("has_release_or_tag", False)
                        if not cached_has_release:
                            try:
                                cached_has_release = await self.github.has_any_release_or_tag(repo)
                            except Exception as err:
                                _LOGGER.debug(
                                    "has_any_release_or_tag failed for %s: %s", repo, err
                                )
                                cached_has_release = False
                            if cached_has_release:
                                await self.store.async_set_branch(
                                    component_id, branch, {"has_release_or_tag": True}
                                )
                        latest["has_release_or_tag"] = cached_has_release
                else:
                    latest = await self.github.resolve_latest(repo, component_id, branch)
                    if latest is not None:
                        # release 모드에서 release/tag 타입이 나왔다면 릴리즈가
                        # 있다는 게 이미 증명된 것이므로 캐시를 채워둔다
                        # (나중에 commit 모드로 전환해도 재확인이 필요 없도록).
                        if latest.get("type") in ("release", "tag"):
                            await self.store.async_set_branch(
                                component_id, branch, {"has_release_or_tag": True}
                            )
            except ConfigEntryAuthFailed:
                raise
            except Exception as err:
                _LOGGER.warning("Failed to fetch version info for %s@%s: %s", repo, branch, err)
                latest = (self.data or {}).get(entry_key, {}).get("latest")

            installed_version, version_source = await self._resolve_installed_version(
                component_id, branch, active
            )
            store_entry = self.store.get_branch(component_id, branch)
            installed_commit_sha = store_entry.get("installed_commit_sha")

            if version_source == "manifest" and installed_version:
                await self.store.async_set_branch(
                    component_id, branch, {"installed_version": installed_version}
                )
                _LOGGER.debug(
                    "Auto-detected %s@%s v%s from manifest.json — persisted to store",
                    component_id, branch, installed_version,
                )
                version_source = "store"

            # 브랜치(커밋 추적) 타입이고 설치는 됐는데 installed_commit_sha가
            # store에 없는 경우: "현재 remote SHA = 설치된 SHA"로 추측해서
            # 덮어써버리면 실제 변경 사항을 영원히 놓치게 된다(과거 버그).
            #
            # 대신 파일 내용을 직접 비교해 검증을 시도한다(verify_installed_sha).
            # 로컬 파일과 원격 HEAD의 모든 blob SHA가 일치하면 — 즉 설치된
            # 파일이 정말로 HEAD와 동일하면 — 그때만 SHA를 안전하게 확정한다.
            # 검증에 실패하거나 다르면 "알 수 없음" 상태를 유지하고
            # has_update=True로 표시해 사용자가 재설치하도록 유도한다.
            sha_unknown_but_installed = (
                is_installed
                and installed_version
                and not installed_commit_sha
                and latest
                and latest.get("type") == "branch"
                and latest.get("commit_sha")
            )

            if sha_unknown_but_installed:
                head_sha = latest["commit_sha"]
                try:
                    verified = await self.github.verify_installed_sha(
                        self.hass, repo, component_id, head_sha
                    )
                except Exception as err:
                    _LOGGER.debug(
                        "verify_installed_sha failed for %s@%s: %s", component_id, branch, err
                    )
                    verified = False

                if verified:
                    installed_commit_sha = head_sha
                    new_manifest_version = latest.get("remote_manifest_version")
                    update_data: dict = {"installed_commit_sha": installed_commit_sha}
                    if new_manifest_version:
                        installed_version = new_manifest_version
                        update_data["installed_version"] = installed_version
                    await self.store.async_set_branch(component_id, branch, update_data)
                    _LOGGER.debug(
                        "Verified installed files match %s@%s HEAD — confirmed SHA %s (version: %s)",
                        component_id, branch, installed_commit_sha[:7], installed_version,
                    )
                    sha_unknown_but_installed = False

            has_update = self._compute_has_update(latest, installed_version, installed_commit_sha)
            if sha_unknown_but_installed:
                has_update = True
                _LOGGER.debug(
                    "%s@%s: installed_commit_sha unknown and could not be verified — "
                    "flagging has_update so a reinstall can record the correct SHA",
                    component_id, branch,
                )

            # 방법 A: SHA가 있는데 has_update=True로 나온 경우에도 verify 재시도.
            # HACS 등 외부 도구가 Private HACS store를 우회해 파일을 직접
            # 교체했을 수 있다 — store에 기록된 installed_commit_sha는 이전
            # 버전 그대로지만, 실제 디스크 파일은 이미 최신 HEAD와 동일할 수 있다.
            # 이 경우 verify_installed_sha가 True를 반환하면:
            #   - store의 installed_commit_sha를 최신 SHA로 갱신
            #   - has_update를 False로 전환 (실제로는 이미 최신 상태이므로)
            # 검증 실패 시에는 has_update=True를 유지(정말로 업데이트가 필요한 상황).
            if (
                has_update
                and not sha_unknown_but_installed
                and installed_commit_sha          # 기존 SHA가 있고
                and latest
                and latest.get("type") == "branch"
                and latest.get("commit_sha")
                and latest["commit_sha"] != installed_commit_sha
            ):
                head_sha = latest["commit_sha"]
                try:
                    verified = await self.github.verify_installed_sha(
                        self.hass, repo, component_id, head_sha
                    )
                except Exception as err:
                    _LOGGER.debug(
                        "verify_installed_sha (external-update check) failed for %s@%s: %s",
                        component_id, branch, err
                    )
                    verified = False

                if verified:
                    # 파일이 실제로 HEAD와 일치 — 외부 도구가 이미 업데이트한 것.
                    # SHA뿐 아니라 manifest 버전도 함께 갱신해야 패널/알림에서
                    # 버전 표시가 이전 값으로 남지 않는다.
                    installed_commit_sha = head_sha
                    new_manifest_version = latest.get("remote_manifest_version")
                    update_data: dict = {"installed_commit_sha": installed_commit_sha}
                    if new_manifest_version:
                        installed_version = new_manifest_version
                        update_data["installed_version"] = installed_version
                    await self.store.async_set_branch(component_id, branch, update_data)
                    has_update = False
                    _LOGGER.debug(
                        "External update detected for %s@%s: files match HEAD %s "
                        "(version: %s) — store updated, has_update cleared",
                        component_id, branch, installed_commit_sha[:7],
                        installed_version,
                    )

            # latest가 branch 타입인데 update_mode가 release인 경우
            # → 릴리즈/태그가 없는 저장소 확인 — config entry에 commit으로 영구 저장
            if (
                latest
                and latest.get("type") == "branch"
                and update_mode == UPDATE_MODE_RELEASE
            ):
                _LOGGER.debug(
                    "No release/tag for %s@%s — auto-switching update_mode to commit",
                    component_id, branch,
                )
                update_mode = UPDATE_MODE_COMMIT
                # repos 리스트와 config entry 모두 업데이트 (재시작 후에도 유지)
                for r in self.repos:
                    if r["component_id"] == component_id and r.get("branch", "main") == branch:
                        r["update_mode"] = UPDATE_MODE_COMMIT
                        break
                # config entry 갱신 (비동기 — fire and forget으로 처리)
                entries = self.hass.config_entries.async_entries(DOMAIN)
                if entries:
                    entry = entries[0]
                    updated_repos = [
                        {**r, "update_mode": UPDATE_MODE_COMMIT}
                        if r["component_id"] == component_id and r.get("branch", "main") == branch
                        else r
                        for r in entry.data.get(CONF_REPOS, [])
                    ]
                    self.hass.config_entries.async_update_entry(
                        entry, data={**entry.data, CONF_REPOS: updated_repos}
                    )

            results[entry_key] = {
                "entry_key": entry_key,
                "repo": repo,
                "name": item.get("name", repo),
                "component_id": component_id,
                "branch": branch,
                "active": active,
                "update_mode": update_mode,
                "latest": latest,
                "installed_version": installed_version,
                "installed_commit_sha": installed_commit_sha,
                "is_installed": is_installed,
                "version_source": version_source,
                # 비활성 브랜치도 has_update는 계산 — 패널에서 표시 여부는 active로 판단
                "has_update": has_update if active else False,
                "has_icon": has_icon_cache.get(component_id, False),
            }

        return results

    # ------------------------------------------------------------------
    # Update detection
    # ------------------------------------------------------------------

    def _compute_has_update(
        self,
        latest: dict | None,
        installed_version: str | None,
        installed_commit_sha: str | None,
    ) -> bool:
        if not installed_version or latest is None:
            return False

        latest_type = latest.get("type")

        if latest_type in ("release", "tag"):
            return _strip_v(str(installed_version)) != _strip_v(str(latest.get("version", "")))

        if latest_type == "branch":
            # 커밋 추적 브랜치: SHA가 1순위 판단 기준.
            # 두 SHA 모두 있으면 그것만으로 판단을 끝낸다 — manifest 버전
            # 문자열이 무엇이든 SHA 비교가 우선한다.
            remote_commit_sha = latest.get("commit_sha")
            if remote_commit_sha and installed_commit_sha:
                return remote_commit_sha != installed_commit_sha

            # SHA로 판단할 수 없는 경우(설치 SHA를 모름)에만
            # manifest.json 버전 문자열을 보조 수단으로 사용
            remote_manifest_version = latest.get("remote_manifest_version")
            if remote_manifest_version:
                return remote_manifest_version != installed_version

        return False

    # ------------------------------------------------------------------
    # Installed version resolution (store → manifest on disk)
    # ------------------------------------------------------------------

    async def _resolve_installed_version(
        self, component_id: str, branch: str, active: bool = True
    ) -> tuple[str | None, str]:
        stored = self.store.installed_version(component_id, branch)
        if stored:
            return stored, "store"

        # 비활성 브랜치는 manifest.json 자동 감지 차단
        # 디스크의 파일이 다른 브랜치 것일 수 있으므로 store 기록만 신뢰
        if not active:
            return None, "none"

        manifest_version = await self.hass.async_add_executor_job(
            self._read_manifest_version_sync, component_id
        )
        if manifest_version:
            return manifest_version, "manifest"

        return None, "none"

    def _read_manifest_version_sync(self, component_id: str) -> str | None:
        path = self.hass.config.path(
            "custom_components", component_id, "manifest.json"
        )
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            version = data.get("version")
            return str(version) if version else None
        except Exception as err:
            _LOGGER.debug("Could not read manifest.json for %s: %s", component_id, err)
            return None

    async def _check_installed(self, component_id: str) -> bool:
        path = self.hass.config.path("custom_components", component_id)
        return await self.hass.async_add_executor_job(os.path.isdir, path)
