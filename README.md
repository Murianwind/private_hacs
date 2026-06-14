# Private HACS

[![Pytest](https://github.com/Murianwind/private_hacs/actions/workflows/pytest.yml/badge.svg)](https://github.com/Murianwind/private_hacs/actions/workflows/pytest.yml)
[![codecov](https://codecov.io/gh/Murianwind/private_hacs/graph/badge.svg)](https://codecov.io/gh/Murianwind/private_hacs)

Private GitHub 저장소를 Home Assistant에서 HACS처럼 관리하는 custom integration.

HACS에 등록할 수 없는 **비공개(Private) 저장소**를 설치·업데이트·삭제할 수 있으며, 하나의 저장소에 **여러 브랜치를 동시에 등록**하여 안정 버전과 개발 버전을 함께 관리할 수 있습니다.

---

## 기능

| 기능 | 설명 |
|---|---|
| 🔒 Private 저장소 지원 | GitHub PAT 토큰으로 비공개 저장소 접근 |
| 🌿 멀티 브랜치 등록 | 저장소당 여러 브랜치 등록, 토글로 활성/비활성 전환 |
| 📦 설치 / 업데이트 / 삭제 | Release → Tag → Branch 순 자동 버전 감지 |
| 🔄 Commit 기반 업데이트 감지 | Release 없는 저장소도 commit 변경 시 업데이트 알림 |
| 🔀 업데이트 방식 선택 | 브랜치별 릴리즈 추적 또는 커밋 추적 선택 |
| #️⃣ Commit SHA 표시 | 커밋 추적 브랜치의 설치 버전 옆에 SHA 7자리 표시 |
| 🖥 사이드바 패널 | 저장소 목록, 설치 상태, README 뷰어 |
| 🔔 `update.*` 엔티티 | HA 기본 Updates 대시보드 연동 |
| ↩️ 등록 해제 후 재등록 | 저장소 해제 시 설치 정보 보존 → 재등록 시 즉시 복원 |

---

## 설치

### 방법 1: HACS Custom Repository (권장)

1. HACS → 우측 상단 ⋮ → **Custom repositories**
2. **URL**: `https://github.com/Murianwind/private_hacs`
3. **Category**: `Integration`
4. **ADD** 클릭 → 목록에서 Private HACS 찾아 **Download**
5. Home Assistant 재시작

### 방법 2: 수동 설치

1. 이 저장소의 `custom_components/private_hacs/` 폴더를 HA config 디렉토리의 `custom_components/` 아래에 복사
2. Home Assistant 재시작

---

## GitHub Personal Access Token 발급

Private 저장소를 관리하려면 GitHub PAT가 필요합니다.

### 발급 경로

GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**

또는 아래 링크로 바로 이동:  
👉 https://github.com/settings/tokens/new

### 필요 권한(Scope)

| 사용 목적 | 필요 scope |
|---|---|
| **Private 저장소** 설치/업데이트 | `repo` (전체 체크) |

> **주의:** `repo` scope는 저장소 읽기/쓰기 권한을 모두 포함합니다.  
> 읽기 전용으로 제한하려면 Fine-grained token을 사용하고 **Contents: Read-only** 권한만 부여하세요.

### Fine-grained Token (더 안전한 방법)

GitHub → Settings → Developer settings → **Personal access tokens** → **Fine-grained tokens** → Generate new token

- **Repository access**: 관리할 저장소만 선택
- **Permissions → Repository permissions**:
  - `Contents`: Read-only
  - `Metadata`: Read-only (자동 포함)

---

## 설정

### 1. Integration 추가

**Settings → Devices & Services → Add Integration** → `Private HACS` 검색

### 2. 토큰 입력

- Private 저장소: 위에서 발급한 PAT 입력

> 토큰은 HA 내부 스토리지에 암호화되어 저장됩니다.

### 3. 저장소 추가 (패널에서)

설치 완료 후 좌측 사이드바에 **Private HACS** 패널이 생깁니다.

1. **＋ 저장소 추가** 클릭
2. GitHub URL 또는 `owner/repo-name` 입력
   - 예: `https://github.com/your-org/your-integration`
   - 예: `your-org/your-integration`
3. 저장소 정보 및 브랜치 목록이 자동으로 조회됩니다
4. 브랜치 선택
5. 업데이트 방식 선택 (릴리즈가 있는 저장소의 비기본 브랜치만 표시)
6. **추가** 클릭

---

## 버전 감지 우선순위

```
GitHub Release (해당 브랜치 대상)  → target_commitish 기준 필터링
Git Tag (최신)                      → tag_name을 버전으로 사용
Branch HEAD                         → remote manifest.json 버전 비교 후 commit SHA 비교
```

Release/Tag가 없는 저장소도 코드 변경(commit)이 있으면 업데이트 알림이 표시됩니다.

> **브랜치 간 간섭 없음**: 각 브랜치는 해당 브랜치를 타겟으로 한 릴리즈만 감지합니다.

---

## 멀티 브랜치 활용

하나의 저장소에 여러 브랜치를 등록하여 상황에 따라 전환할 수 있습니다.

### HACS + Private HACS 조합

HACS에서는 공개 저장소의 안정 릴리즈를 유지하면서, Private HACS에 개발 브랜치를 등록해 테스트할 수 있습니다.

```
HACS:         my_integration  v2.0.0  (공개 저장소 릴리즈)
Private HACS: my_integration  dev 브랜치  (비공개 저장소 커밋 추적)
```

### 브랜치 전환 동작

- 비활성 브랜치를 활성화하면 **설치 여부**에 따라 팝업이 표시됩니다
  - 미설치: 설치 팝업
  - 설치됨 + 업데이트 있음: 업데이트 팝업
  - 설치됨 + 최신: 팝업 없이 활성화
- 활성 브랜치를 비활성화하면 **등록 해제 버튼만** 표시됩니다
- 활성 브랜치 등록 해제 시 마지막 남은 브랜치가 **자동 활성화**됩니다

---

## 패널 기능

| 기능 | 설명 |
|---|---|
| 저장소 목록 | 전체 / 설치됨 / 업데이트 가능 / 미설치 필터 |
| 설치 / 업데이트 / 재설치 | 버튼 한 번으로 GitHub에서 직접 설치 |
| 릴리즈 선택 설치 | 릴리즈 타입 브랜치 재설치 시 버전 선택 모달 |
| 컴포넌트 삭제 | 파일만 삭제, 저장소 등록은 유지 |
| 등록 해제 | 목록에서 제거, 파일과 버전 정보는 보존 |
| README 뷰어 | 저장소 이름 클릭 시 README 팝업 표시 |
| 새로고침 | GitHub API를 즉시 재조회하여 최신 버전 확인 |
| HA 재시작 | Home Assistant 재시작 (새로고침과 저장소 추가 사이) |

---

## HA 서비스

자동화나 스크립트에서 직접 호출할 수 있습니다.

### `private_hacs.install`
```yaml
service: private_hacs.install
data:
  component_id: my_integration
  branch: main
  ref: "v2.0.0"  # 선택사항 — 특정 버전 지정
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

### `private_hacs.add_repo`
```yaml
service: private_hacs.add_repo
data:
  repo: "your-org/your-integration"
  name: "My Integration"
  component_id: "my_integration"
  branch: "main"
  update_mode: "release"  # "release" 또는 "commit"
```

### `private_hacs.remove_repo`
```yaml
service: private_hacs.remove_repo
data:
  component_id: my_integration
  branch: main
```

### `private_hacs.set_update_mode`
```yaml
service: private_hacs.set_update_mode
data:
  component_id: my_integration
  branch: dev
  update_mode: "commit"  # "release" 또는 "commit"
```

---

## 생성되는 엔티티

저장소 등록 시 브랜치별로 자동 생성:
```
update.private_hacs_my_integration_main
update.private_hacs_my_integration_dev
```

HA 기본 **Updates** 대시보드에서도 확인 및 업데이트 가능.

---

## 주의사항

- 설치/삭제 후 **HA 재시작** 필요 (HA 구조상 불가피)
- 저장소에 `custom_components/<component_id>/` 디렉토리가 존재해야 함
- `custom_components/<component_id>/` 경로는 하나뿐이므로 여러 브랜치 중 실제로 설치된 브랜치의 파일만 존재
- GitHub API: 인증 토큰 사용 시 시간당 5,000 요청
- 폴링 주기: 기본 6시간 (즉시 갱신은 패널의 새로고침 버튼 사용)

---

## License

MIT
