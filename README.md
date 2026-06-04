# AI 온라인 재고 자동 재배치 — 운영 대시보드 (듀얼 버전)

**한 앱에서 버전 전환**: 로그인 후 상단 라디오로 `v2.0 (최신)` ↔ `v1.4 (이전 참고용)` 전환.

| 파일 | 역할 |
|---|---|
| `app.py` | 진입점 — 페이지 설정·비밀번호 게이트·공통 CSS·버전 토글 |
| `app_v20.py` | v2.0 화면 (자동분배 제거·리오더 병합·외부창고 분리) |
| `app_v14.py` | v1.4 화면 (반응과 자동분배 포함, 이전 참고용) |
| `rebalance_engine.py` | v2.0 엔진 |
| `rebalance_engine_v14.py` | v1.4 엔진 (모드A/B) |
| `mock_data.py` | 공용 로더 — v2(병합)·v1(원본) 동시 제공 |

## v2.0 변경 (2026-06-04)

| # | 변경 | 내용 |
|---|---|---|
| ① | 자동분배 제거 | 모드B(반응과→채널 분배)·반응과 컬럼 삭제. 채널 간 재배치만 수행 |
| ② | 리오더코드 병합 | `reorder_mapping.csv`(또는 .xlsx, 컬럼: 기존코드/리오더코드)를 앱 폴더에 넣으면 자동 감지 → 리오더코드의 재고·주문을 기존코드로 합산, 화면은 기존코드로 노출. 매트릭스 '리오더' 컬럼(+N)·'리오더 병합만' 필터 추가. 파일 없으면 병합 없이 동작 |
| ③ | 외부창고 재고량 | 무신사 풀필먼트(AENS)·지그재그 천안(ADU3)·네이버 CMS(ADQS) 별도 컬럼. 외부창고 보관분은 타 채널 회수(OUT) 대상에서 제외. ※ 현재 mock 분리(35~65% 결정적) — `sku_master.csv`에 `wh_무신사`/`wh_지그재그`/`wh_네이버` 컬럼 추가 시 실데이터 사용 |

## 배포 (Streamlit Cloud)
GitHub 레포에 이 폴더 파일을 push → spao-rebal.streamlit.app 자동 재배포.
비밀번호: 환경변수 `APP_PASSWORD` (기본 `spao`).

## 리오더 매핑 파일 형식
`reorder_mapping_TEMPLATE.csv` 참조:
```
기존코드,리오더코드
SPJJG25G0110090,SPJJG26G0110090
```
(rsc.reorder_style_mapping_spao 추출본 그대로 사용 가능 — '기존'/'리오더' 포함 컬럼명 자동 탐지)

---

---
title: SPAO Rebalance
emoji: 📊
colorFrom: green
colorTo: blue
sdk: streamlit
sdk_version: 1.40.0
app_file: app.py
pinned: false
short_description: AI 온라인 재고 자동 재배치 PoC 대시보드 (비밀번호 보호)
---

# AI 온라인 재고 자동 재배치 — PoC 웹 대시보드

Streamlit 기반의 실시간 운영 대시보드. SAP 재고 + 6채널 주문을 자동 수집하여 단품 × 채널 매트릭스로 시각화하고, 1-클릭 승인으로 SAP에 자동 반영합니다.

## 접속

진입 시 비밀번호 입력 화면이 표시됩니다. 비밀번호는 Hugging Face Space의 **Settings → Variables and secrets → `APP_PASSWORD`** 에 등록된 값입니다. 미설정 시 기본값 `spao`.

## 빠른 시작 (로컬)

```bash
pip install -r requirements.txt
export APP_PASSWORD=spao   # 선택 — 미설정 시 'spao'
streamlit run app.py
# 브라우저: http://localhost:8501
```

## 파일 구성

| 파일 | 역할 |
|---|---|
| `app.py` | Streamlit 메인 앱 — 비밀번호 게이트 + UI/UX 전체 |
| `rebalance_engine.py` | 핵심 재배치 로직 (보수 시나리오 기본) |
| `mock_data.py` | SAP/채널 API 시뮬레이터 (PoC) — 실 배포 시 교체 |
| `sku_master.csv` | 보수운영.xlsx에서 추출한 실 단품 데이터 (8,308건) |
| `requirements.txt` | 의존성 |

## 주요 기능

### 1. 데이터 자동 수집
- **재고**: SAP CDS View / ABAP RFC (현재 mock)
- **주문**: 6채널 파트너센터 API — 공홈·이랜드몰·무신사·지그재그·네이버·카카오선물하기 (현재 mock)
- 매일 06:00 Airflow 자동 갱신 (EHUB 06:00 & 샵링크 06:30 배치 직후) (실 배포 시)

### 2. AI 재배치 로직
- **모드 A** (출고율 ≥90%): 채널 간 재고 회전
- **모드 B** (출고율 <90% + 온라인비중 ≥10%): 반응과 → 부족 채널 분배
- **트리거**: 재고주수 ≤ 1주 (설정 가능)
- **목표**: 4주 (설정 가능)
- **필터**: 단품당 이동 <10장 제외 (Critical SKU 예외)

### 3. 단품 × 채널 매트릭스
- 6채널 재고주수 + 이동수량 + 이동 후 재고주수 + 기대효과 한눈에
- 색상 시각화:
  - 재고주수: 🔴 <2주 / 🟡 2~4주 / 🟢 ≥4주
  - 이동수량: 🟢 +IN / 🔴 -OUT

### 4. 인터랙티브 파라미터
- 사이드바에서 부족 임계·목표 주수·출고율·온라인비중·10장 필터 실시간 조정
- 조정 즉시 모든 KPI·매트릭스 자동 재계산

### 5. 시나리오 탭
- 🛡️ 방어형 (추천) / ⚡ 공격형 / 🎛️ 사용자 정의

## 단계별 로드맵

| 단계 | 시점 | 내용 |
|---|---|---|
| **PoC v1** | 즉시 | Streamlit + mock 데이터 (현재) |
| **PoC v2** | W-3 | SAP 1채널 + 무신사 1채널 실 데이터 연동 |
| **본 운영 v1** | Cut-over (7/1) | 6채널 전체 실 연동 + 1-클릭 승인 → SAP BAPI |
| **본 운영 v2** | 안정화 (W+8) | FastAPI + Plotly Dash + SSO + 다중 사용자 |
| **확산 v3** | W+12 이후 | 미쏘·로엠 확산 + 권한 관리 + 감사 로그 |

## 문의

Fashion BG · CAIO실 AX 혁신팀 · 강훈구
