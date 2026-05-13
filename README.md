# Private HACS

Private GitHub 저장소를 HACS처럼 관리하는 Home Assistant custom integration.

## 기능

| 기능 | 설명 |
|---|---|
| 🔒 Private 저장소 지원 | GitHub PAT 토큰으로 인증 |
| 📦 설치 / 업데이트 / 삭제 | GitHub Release → Tag → Branch 순 자동 선택 |
| 🖥 사이드바 패널 | HACS와 유사한 UI 패널 |
| 🔔 `update.*` 엔티티 | HA 기본 Updates 대시보드 연동 |
| ⚙️ 서비스 | 자동화에서 설치/삭제/새로고침 호출 가능 |

---

## 설치

### 방법 1: HACS Custom Repository

1. HACS → ⋮ → **Custom repositories**
2. URL: `https://github.com/<your-id>/private-hacs`, Category: **Integration**
3. Download 후 HA 재시작

### 방법 2: 수동

`custom_components/private_hacs/` 를 HA config 디렉토리에 복사 후 재시작

---

## 설정

1. **Settings → Devices & Services → Add Integration** → `Private HACS`

2. **GitHub Personal Access Token** 입력
   - Private 저장소: `repo` scope 필요
   - Public 저장소만: 토큰 불필요

3. **저장소 목록** JSON 입력:

```json
[
  {
    "repo": "your-org/your-private-integration",
    "name": "My Integration",
    "component_id": "my_integration",
    "branch": "main"
  },
  {
    "repo": "another-org/another-component",
    "name": "Another Component",
    "component_id": "another_component"
  }
]
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `repo` | ✅ | `owner/repo-name` |
| `name` | ✅ | 표시 이름 |
| `component_id` | ✅ | `custom_components/` 하위 폴더명 (snake_case) |
| `branch` | ❌ | 기본 브랜치 (기본값: `main`) |

---

## 버전 감지 우선순위

```
GitHub Releases (latest) → Git Tags → Branch HEAD
```

- Release가 있으면 tag_name을 버전으로 사용
- Release가 없으면 최신 Tag 사용
- Tag도 없으면 branch 이름을 버전으로 사용 (항상 "업데이트" 상태)

---

## 사이드바 패널

설치 완료 후 좌측 사이드바에 **Private HACS** 메뉴가 생깁니다.

- 전체 저장소 목록 + 설치 상태 확인
- 설치 / 업데이트 / 삭제 버튼
- 필터 (전체 / 설치됨 / 업데이트 가능 / 미설치)

---

## HA 서비스

### `private_hacs.install`
```yaml
service: private_hacs.install
data:
  component_id: my_integration
```

### `private_hacs.uninstall`
```yaml
service: private_hacs.uninstall
data:
  component_id: my_integration
```

### `private_hacs.refresh`
```yaml
service: private_hacs.refresh
```

---

## 엔티티

각 저장소마다 자동 생성:
```
update.my_integration_update
update.another_component_update
```

HA 기본 Updates 대시보드에서도 확인 가능.

---

## 주의사항

- 설치/삭제 후 **HA 재시작** 필요 (HA 구조상 불가피)
- 저장소의 `custom_components/<component_id>/` 디렉토리가 존재해야 함
- GitHub API Rate limit: 인증 시 시간당 5000 요청 (토큰 권장)

---

## License

MIT
