# AICA 다운로드 자산

대시보드 사이드바 "AICA 아침 브리핑" 섹션에서 제공되는 파일들.

## 파일 구성

| 파일 | 설명 | 용량 |
|---|---|---|
| `AICA_morning_brief.html` | 풀스크린 브리핑 HTML (음성 + 클릭 시 대시보드 이동) | 12KB |
| `AICA_light.zip` | HTML + 시작.bat 묶음 (Chrome/Edge 자동 풀스크린) | 5KB |
| `AICA_시작.bat` | Chrome/Edge 풀스크린 자동 실행 launcher | 1KB |
| `AICA_아침브리핑.html` | 한글 파일명 호환 (HTML 동일) | 12KB |
| `AICA_경량버전.zip` | 한글 파일명 호환 (ZIP 동일) | 5KB |

## 사용자 다운로드 후 절차

1. ZIP 다운로드 → 풀기
2. `AICA_시작.bat` 더블클릭
3. 음성 브리핑 + "지금 실행" 버튼 → 대시보드 자동 오픈
4. 매일 07:00 자동 실행:
   - Win+R → `taskschd.msc`
   - 기본 작업 만들기 → 매일 07:00 → 동작=`AICA_시작.bat`

## 데스크톱 펫 (풀버전) 호스팅 옵션

`REBA_Pet/dist/win-unpacked` (252MB) 는 Streamlit Cloud에 직접 호스팅하기엔 무거움. 다음 중 택1:

| 옵션 | 절차 |
|---|---|
| **GitHub Releases** | GitHub 리포 → Releases 탭 → New release → ZIP 업로드 → 공개 URL 획득 |
| **사내 NAS** | NAS 공유 폴더에 ZIP 배치 → 사내 IP 경로 공유 |
| **OneDrive / Drive** | 폴더 공유 → "링크 가진 사용자" 권한 → URL 획득 |

URL 정해지면 `app.py`의 `_aica_download_section()` 안 데스크톱 펫 expander에 `st.link_button("📥 데스크톱 펫 다운로드", url)` 한 줄만 추가하면 즉시 노출됨.

## Streamlit Cloud 배포 시 주의

- 본 폴더(`assets/aica/`)는 Streamlit 앱과 함께 GitHub에 push 되어야 함
- Streamlit Cloud가 자동으로 폴더 통째로 배포
- 다운로드 버튼은 `st.download_button(data=open(...).read())` 패턴으로 메모리 로드
- ZIP/HTML 파일이 git에 추적되는지 `git status` 확인
