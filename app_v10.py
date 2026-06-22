# -*- coding: utf-8 -*-
"""온라인 재고관리 Agent — v1.0 (테스트) 별도 페이지.

SCM에이전트 학습 4종 통합 — ① 데이터 신선도  ② 결품보정 토글
③ AI 인사이트 한 줄  ④ AI 어시스턴트 채팅.

라디오로 'AI 1.0 (테스트)' 선택 시 진입. v0.9 운영 화면과 완전 분리.
검토 후 확정/롤백 결정 → 확정 시 메인 페이지로 승격, 롤백 시 라디오만 제거.
"""
import streamlit as st

import app_v20  # 함수 재사용 (render_v10_test_tab, _v10_chat_answer)


def render() -> None:
    """v1.0 별도 페이지 — 헤더 + SCM 학습 4종 화면."""
    # 페이지 헤더 (다크 + 보라 그라데이션)
    st.markdown(
        '<div style="background:linear-gradient(135deg,#1a0d2e 0%,#0f1d3a 50%,#0a2138 100%);'
        'padding:24px 28px;border-radius:14px;border:1px solid #5a3fb8;margin-bottom:18px;'
        'box-shadow:0 0 30px rgba(90,63,184,.25)">'
        '<div style="display:flex;align-items:center;justify-content:space-between">'
        '  <div>'
        '    <div style="color:#c4a8ff;font-size:13px;letter-spacing:2px;font-weight:600">AICA · NEXT</div>'
        '    <div style="color:#fff;font-size:30px;font-weight:800;margin-top:4px">🧪 v1.0 (테스트) — AI 결과물 모드</div>'
        '    <div style="color:#9fb3d9;font-size:13px;margin-top:6px">'
        '      SCM에이전트 학습 4종 통합 · <b>검토 후 확정/롤백 결정</b>. '
        '      v0.9 운영 화면과 완전 분리 — 상단 라디오에서 언제든 v0.9로 복귀 가능.'
        '    </div>'
        '  </div>'
        '  <div style="text-align:right">'
        '    <span style="background:#5a3fb8;color:#fff;padding:6px 14px;border-radius:20px;'
        '          font-size:12px;font-weight:700">RESEARCH PREVIEW</span>'
        '  </div>'
        '</div></div>',
        unsafe_allow_html=True,
    )

    # SCM에이전트 학습 4종 출처 (간단 표시)
    with st.expander('📚 이 페이지는 무엇인가요? (SCM에이전트 학습 출처)', expanded=False):
        st.markdown(
            '실장님 6/22 메일 후속 — **SCM에이전트(E-Supply Depot) 학습 결과**를 우리 온라인 '
            '재고관리 Agent에 적용한 테스트 페이지입니다.\n\n'
            '- **A2 데이터 신선도 표시** — 채널별 동기 시각 ✅⚠️🔴\n'
            '- **A4 AI 인사이트 한 줄 결론** — 회전 추천을 한국어 1줄로 자동 요약\n'
            '- **B2 결품보정 ↔ 수요예측 토글** — SCM 차별 기능 (잠재수요 복원)\n'
            '- **B3 AI 어시스턴트 채팅** — 자연어 질의 (현 규칙 기반, 7월 LLM 본연동)\n\n'
            '👉 마음에 들면 메인 v0.9로 승격 · 아쉬우면 이 페이지만 제거 (v0.9 회귀 0)'
        )

    st.markdown('---')

    # 본문 — app_v20의 render_v10_test_tab 재사용
    app_v20.render_v10_test_tab()

    st.markdown('---')
    st.caption('© 2026 Fashion BG · CAIO실 AX 혁신팀 · 강훈구  ·  🧪 v1.0 (테스트) — SCM에이전트(E-Supply Depot) 학습 반영 · 1차 시연 7월 초 목표')
