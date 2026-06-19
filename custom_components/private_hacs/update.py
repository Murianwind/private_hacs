"""Update platform for Private HACS."""
from __future__ import annotations

import logging

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_REPOS, DOMAIN
from .coordinator import PrivateHacsCoordinator, make_entry_key

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    ed = hass.data[DOMAIN][entry.entry_id]
    coordinator: PrivateHacsCoordinator = ed["coordinator"]

    ed["async_add_entities"] = async_add_entities
    ed.setdefault("update_entities", {})

    repos: list[dict] = entry.data.get(CONF_REPOS, [])
    async_add_entities(
        PrivateHacsUpdateEntity(coordinator, entry, repo) for repo in repos
    )


class PrivateHacsUpdateEntity(CoordinatorEntity[PrivateHacsCoordinator], UpdateEntity):
    """One update entity per (component_id, branch) pair."""

    _attr_has_entity_name = False
    _attr_auto_update = False
    _attr_supported_features = (
        UpdateEntityFeature.RELEASE_NOTES
        | UpdateEntityFeature.SPECIFIC_VERSION
    )

    def __init__(
        self,
        coordinator: PrivateHacsCoordinator,
        entry: ConfigEntry,
        repo_cfg: dict,
    ) -> None:
        super().__init__(coordinator)
        self._component_id: str = repo_cfg["component_id"]
        self._branch: str = repo_cfg.get("branch", "main")
        self._entry_key: str = make_entry_key(self._component_id, self._branch)
        self._entry_id = entry.entry_id

        # repo_cfg의 active를 초기값으로 캐시
        self._active_cache: bool = bool(repo_cfg.get("active", True))

        self.entity_id = f"update.{self._component_id}_{self._branch}_update"
        self._attr_unique_id = f"repo_{self._component_id}_{self._branch}"
        self._attr_name = f"{repo_cfg['name']} ({self._branch})"
        self._attr_title = repo_cfg["name"]

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Private HACS",
            manufacturer="private-hacs",
            model="Private Repository Manager",
            entry_type=DeviceEntryType.SERVICE,
        )

        coordinator.hass.data[DOMAIN][self._entry_id]["update_entities"][
            self._entry_key
        ] = self

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        entities = (
            self.hass.data.get(DOMAIN, {})
            .get(self._entry_id, {})
            .get("update_entities", {})
        )
        entities.pop(self._entry_key, None)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def _repo_data(self) -> dict:
        if self.coordinator.data is None:
            return {}
        return self.coordinator.data.get(self._entry_key) or {}

    @property
    def _latest(self) -> dict:
        return self._repo_data.get("latest") or {}

    @property
    def _is_active(self) -> bool:
        """
        active 상태 결정 우선순위:
        1. coordinator.data에 값이 있으면 그 값 사용
        2. 없으면 _active_cache(생성 시 repo_cfg 값) 사용
        """
        data = self._repo_data
        if data:
            return bool(data.get("active", self._active_cache))
        return self._active_cache

    def _handle_coordinator_update(self) -> None:
        """coordinator 갱신 시 _active_cache 동기화."""
        data = self._repo_data
        if data and "active" in data:
            self._active_cache = bool(data["active"])
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        """
        항상 True를 반환.

        비활성 브랜치를 unavailable로 만들면 HA가 attributes를 빈 dict로
        반환하여 패널이 active=False를 읽지 못하는 문제가 발생함.
        active 상태는 extra_state_attributes의 'active' 키로 노출하고,
        패널이 이를 읽어 UI에서 비활성으로 표시함.
        """
        return True

    @property
    def installed_version(self) -> str | None:
        return self._repo_data.get("installed_version")

    @property
    def latest_version(self) -> str | None:
        # 비활성 브랜치는 버전 불일치로 인한 업데이트 알림을 표시하지 않음
        if not self._is_active:
            return self._repo_data.get("installed_version")
        if not self._repo_data.get("has_update", False):
            return self._repo_data.get("installed_version")
        latest = self._latest
        # 커밋 추적(branch 타입): 1순위 SHA, 2순위 manifest 버전.
        # SHA가 있으면 항상 SHA 7자리를 우선 표시한다.
        # manifest 버전은 SHA를 구할 수 없을 때만 보조로 사용한다.
        # (manifest 버전 자체가 사라지는 게 아니라, 패널 UI에서
        #  extra_state_attributes의 remote_commit_sha와 함께
        #  "버전/SHA" 형태로 합쳐서 보여준다.)
        if latest.get("type") == "branch":
            commit_sha = latest.get("commit_sha")
            if commit_sha:
                return commit_sha[:7]
            manifest_version = latest.get("remote_manifest_version")
            if manifest_version:
                return manifest_version
        return latest.get("version")

    @property
    def release_url(self) -> str | None:
        latest = self._latest
        latest_type = latest.get("type")
        repo = self._repo_data.get("repo")
        branch = self._repo_data.get("branch", self._branch)

        # branch 타입이면 항상 커밋 로그 URL
        if latest_type == "branch" and repo:
            return f"https://github.com/{repo}/commits/{branch}"

        # release/tag 타입이면 release_url 사용
        url = latest.get("release_url")
        if url:
            return url

        # latest 없는 초기 상태 — repo가 있으면 커밋 로그로 fallback
        if repo:
            return f"https://github.com/{repo}/commits/{branch}"

        return None

    @property
    def release_summary(self) -> str | None:
        return self._latest.get("release_summary")

    @property
    def extra_state_attributes(self) -> dict:
        latest = self._latest
        return {
            "branch": self._branch,
            "active": self._is_active,
            "update_mode": self._repo_data.get("update_mode", "release"),
            "version_source": self._repo_data.get("version_source", "none"),
            "latest_type": latest.get("type"),
            "remote_commit_sha": latest.get("commit_sha"),
            "remote_manifest_version": latest.get("remote_manifest_version"),
            "installed_commit_sha": self._repo_data.get("installed_commit_sha"),
            "has_icon": self._repo_data.get("has_icon", False),
            # commit 모드는 릴리즈를 조회하지 않으므로 latest_type만으로는
            # "릴리즈가 진짜 없는지" 판단할 수 없다. coordinator가 캐시해둔
            # 값을 그대로 노출해 패널 UI가 모드 전환 가능 여부를 정확히
            # 판단하도록 한다.
            "has_release_or_tag": latest.get("has_release_or_tag", False),
        }

    async def async_release_notes(self) -> str | None:
        return self.release_summary

    async def async_install(self, version: str | None, backup: bool, **kwargs) -> None:
        from .services import _do_install
        await _do_install(
            self.hass,
            self._component_id,
            self._branch,
            ref=version,
        )
