# AI 온라인 재고 자동 재배치 — PoC

스파오 6채널 단품 재고 자동 재배치 시뮬레이션 (Streamlit)

## 🔒 비밀번호 보호
- 모든 접근에 비밀번호 필요
- 비밀번호는 `secrets.toml` 또는 Streamlit Cloud Secrets에서 설정

## 🚀 Streamlit Community Cloud 배포 (권장)

### 1단계: GitHub 리포지토리 생성
1. https://github.com/new → 리포지토리 이름 자유 (예: `spao-rebalance`)
2. **Private** 선택 권장 (코드는 비공개)
3. 이 폴더의 모든 파일 업로드 (단, `secrets.toml`은 절대 업로드 금지!)

### 2단계: Streamlit Cloud 연결
1. https://share.streamlit.io 접속 → GitHub 계정으로 로그인
2. **"Create app"** → 방금 만든 리포지토리 선택
3. **Main file path**: `app.py`
4. **"Advanced settings"** 클릭

### 3단계: 비밀번호 설정 (중요)
**Secrets** 입력란에 아래 한 줄 입력:
```
app_password = "원하는_비밀번호"
```

### 4단계: Deploy 클릭
- 5분 내 배포 완료
- URL: `https://[앱이름].streamlit.app`
- 팀원에게 URL + 비밀번호 공유

## 💻 로컬 실행 (개발자용)
```bash
pip install -r requirements.txt
# .streamlit/secrets.toml 파일 생성:
echo 'app_password = "테스트1234"' > .streamlit/secrets.toml
streamlit run app.py
```

## 📁 파일 구조
- `app.py` — 메인 Streamlit 앱
- `auth.py` — 비밀번호 인증 모듈
- `rebalance_engine.py` — 재배치 계산 로직
- `mock_data.py` — 데이터 로더
- `sku_master.csv` — 실 SPAO SKU 데이터 (8,308 단품)
- `requirements.txt` — 의존성
- `.streamlit/secrets.toml.example` — 비밀번호 설정 예시

## ⚠️ 주의사항
- `sku_master.csv`에는 **실 스파오 내부 데이터**가 포함되어 있습니다
- GitHub 리포지토리는 반드시 **Private**로 설정하세요
- 사용 종료 후 Streamlit Cloud 앱을 삭제하세요
