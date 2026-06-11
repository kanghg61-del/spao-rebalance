# -*- coding: utf-8 -*-
"""
AI 1.0 ver (테스트) 화면 — 'AI다움' 가시화 테스트 버전

v5.6 엔진·데이터는 그대로 두고(읽기 전용), 그 위에 AI 레이어 3종을 얹는다:
  ① 🤖 오늘의 AI 브리핑 — 전수 스캔 결과를 사람이 읽는 문단으로 요약
  ② 📡 결품 위험 레이더 — 단품×채널별 '7일 내 결품 확률'(포아송 수요 모형) + 등급/예상 결품일
  ③ 🧠 AI 권고 + 사유(XAI) — 각 재배치 권고의 '왜'를 자연어 설명문으로 생성

정직성 라벨: AI 1.0 = 통계 확률모형 + 규칙기반 설명 생성 (ML 수요예측·자기학습은 AI 1.5 로드맵).
"""
import streamlit as st
import pandas as pd

import ai_insight
from app_v20 import load_data_v20, calc_results_v20, CH_SHORT
from mock_data import CHANNELS, get_last_update_time

GRADE_ORDER = ['🔴 긴급', '🟠 경계', '🟡 관찰', '🟢 안정']

# 기본 시나리오와 동일 파라미터 (부족 1주 / 목표 4주 / 이동 상한 50%) — 제외 없음
BASE_KEY = (1.0, 4.0, 0.90, 0, 0, (), 0.50)


@st.cache_data(show_spinner=False)
def ai_risk_rows():
    skus = load_data_v20()
    return ai_insight.sku_channel_risks(skus, CHANNELS)


@st.cache_data(show_spinner=False)
def ai_reco_summary():
    """v5.6 엔진 권고(기본 시나리오) 요약 — 이동 발생 단품만."""
    results = calc_results_v20(BASE_KEY)
    moved = []
    total_in = 0
    total_rev = 0
    for r in results:
        ins = sum(v for v in r['moves'].values() if v > 0)
        if ins > 0:
            moved.append(r)
            total_in += ins
            total_rev += r['revenue']
    moved.sort(key=lambda r: -r['revenue'])
    return moved, total_in, total_rev


def _md_html(text):
    """간이 변환: **굵게** → <b></b>, 빈 줄 → <br><br> (HTML 박스 안 렌더용)."""
    out, bold = [], False
    i = 0
    while i < len(text):
        if text[i:i + 2] == '**':
            out.append('</b>' if bold else '<b>')
            bold = not bold
            i += 2
        else:
            out.append(text[i])
            i += 1
    return ''.join(out).replace('\n\n', '<br><br>').replace('\n', '<br>')


def _kpi(col, label, value, sub=''):
    col.markdown(
        f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>'
        f'<div class="kpi-sub">{sub}</div></div>', unsafe_allow_html=True)


def _risk_df(rows):
    return pd.DataFrame([{
        '위험등급': r['grade'],
        '결품확률(7일)': f"{ai_insight.risk_bar(r['p7'])} {r['p7'] * 100:.0f}%",
        '단품코드': r['code'],
        '단품명': r['name'],
        '채널': CH_SHORT.get(r['channel'], r['channel']),
        '현재고(장)': r['inv'],
        '주간수요(장)': r['ord'],
        '재고주수': r['woc'],
        '예상결품': (f"D+{r['d_day']:.0f}일" if r['d_day'] is not None and r['d_day'] <= 14 else '2주 이후'),
        '위험노출(만원/주)': round(r['loss_week'] / 10000),
        '예측신뢰도': r['conf'],
    } for r in rows])


def render():
    st.markdown(
        '<div class="title-bar">AICA — 온라인 재고관리 에이전트'
        '<span class="ver-badge">🤖 AI 1.0 ver (테스트)</span></div>',
        unsafe_allow_html=True)
    last = get_last_update_time()
    asof = last.strftime('%Y-%m-%d %H:%M')
    st.caption(
        f'마지막 갱신: **{asof}**   |   AI 1.0 = 결품 확률모형(포아송 수요) + 권고 사유 자동 생성(XAI)   |   '
        '엔진·데이터는 v5.6과 동일 (읽기 전용 레이어)')

    risk_rows = ai_risk_rows()
    moved, total_in, total_rev = ai_reco_summary()

    # ── ① 오늘의 AI 브리핑 ─────────────────────────────────────
    st.markdown('#### 🤖 오늘의 AI 브리핑')
    briefing = ai_insight.daily_briefing(risk_rows, total_in, total_rev, len(moved), asof)
    st.markdown(f'<div class="scenario-box" style="font-size:13px; line-height:1.7;">{_md_html(briefing)}</div>',
                unsafe_allow_html=True)

    # KPI 카드
    n_crit = sum(1 for r in risk_rows if r['p7'] >= 0.8)
    n_warn = sum(1 for r in risk_rows if 0.5 <= r['p7'] < 0.8)
    exposure = sum(r['loss_week'] for r in risk_rows if r['p7'] >= 0.5)
    c1, c2, c3, c4, c5 = st.columns(5)
    _kpi(c1, '🔴 긴급 (결품확률 80%+)', f'{n_crit:,}건', '단품×채널 · 7일 내')
    _kpi(c2, '🟠 경계 (50~80%)', f'{n_warn:,}건', '단품×채널 · 7일 내')
    _kpi(c3, '위험 노출 매출', f'{exposure / 100000000:.2f}억', '미조치 시 주간 손실 추정')
    _kpi(c4, 'AI 권고 이동', f'{total_in:,}장', f'{len(moved):,}개 단품 (기본 시나리오)')
    _kpi(c5, '기대 회수 매출', f'{total_rev / 100000000:.2f}억/주', '권고 전량 실행 시')

    st.markdown('---')

    # ── ② 결품 위험 레이더 ─────────────────────────────────────
    st.markdown('#### 📡 결품 위험 레이더 — 단품×채널 7일 내 결품 확률')
    f1, f2, f3, f4 = st.columns([1.6, 1.6, 2, 1])
    with f1:
        sel_grade = st.multiselect('위험 등급', GRADE_ORDER, default=['🔴 긴급', '🟠 경계'], key='ai_grade')
    with f2:
        sel_ch = st.multiselect('채널', CHANNELS, default=CHANNELS, key='ai_ch')
    with f3:
        q = st.text_input('단품코드/단품명 검색', '', key='ai_q', placeholder='예: SPJJG25G01 또는 윈드브레이커')
    with f4:
        top_n = st.number_input('표시 건수', 50, 2000, 300, 50, key='ai_topn')

    rows = [r for r in risk_rows
            if r['grade'] in (sel_grade or GRADE_ORDER) and r['channel'] in (sel_ch or CHANNELS)]
    if q.strip():
        ql = q.strip().lower()
        rows = [r for r in rows if ql in r['code'].lower() or ql in r['name'].lower()]
    st.caption(f'조건 일치 {len(rows):,}건 중 상위 {min(len(rows), int(top_n)):,}건 표시 — 결품 확률 ↓, 위험 노출 매출 ↓ 정렬. '
               '확률 = P(7일 수요 > 현재고), 수요는 주간 주문량 기반 포아송 분포 가정.')
    st.dataframe(_risk_df(rows[: int(top_n)]), use_container_width=True, height=420, hide_index=True)

    st.markdown('---')

    # ── ③ AI 권고 + 사유 (XAI) ────────────────────────────────
    st.markdown('#### 🧠 AI 권고 + 사유 (XAI) — "왜 이 이동인가"를 AI가 설명합니다')
    if not moved:
        st.info('현재 기준 이동 권고가 없습니다.')
        return

    top_moved = moved[:100]
    options = {
        f"{i + 1}. {r['code']} · {r['data'].get('name', '')[:22]} — 기대 회수 {r['revenue'] / 10000:,.0f}만원/주": r
        for i, r in enumerate(top_moved)
    }
    pick = st.selectbox('권고 단품 선택 (기대 회수 매출 상위 100건)', list(options.keys()), key='ai_pick')
    r = options[pick]
    d, moves = r['data'], r['moves']

    # 채널별 미니 매트릭스
    mini = pd.DataFrame([{
        '채널': CH_SHORT.get(c, c),
        '현재고(장)': d['inv'].get(c, 0),
        '주간수요(장)': d['orders'].get(c, 0),
        '재고주수': (round(max(0, d['inv'].get(c, 0)) / d['orders'][c], 1) if d['orders'].get(c, 0) > 0 else None),
        '외부창고(이동불가)': d.get('ext_wh', {}).get(c, 0),
        'AI 권고 이동(장)': moves.get(c, 0),
        '이동 후 재고(장)': d['inv'].get(c, 0) + moves.get(c, 0),
    } for c in CHANNELS])
    st.dataframe(mini, use_container_width=True, hide_index=True)

    explain = ai_insight.explain_move(r['code'], d, moves, r['revenue'], CHANNELS)
    st.markdown('**🤖 AI 사유 설명**')
    st.markdown(f'<div class="scenario-box" style="font-size:13px; line-height:1.8;">{_md_html(explain)}</div>',
                unsafe_allow_html=True)
    with st.expander('ⓘ 이 설명은 어떻게 생성되나요? (정직성 라벨)'):
        st.markdown(
            '- **결품 확률**: 채널 주간 주문량을 포아송 수요로 가정, P(7일 수요 > 현재고) 산출 (통계 모형)\n'
            '- **사유 설명문**: 엔진 산출(이동량·제약·수수료)을 근거 템플릿에 결합해 자동 생성 (규칙기반 XAI)\n'
            '- **AI 1.5 로드맵**: 시계열 수요예측(시즌성·프로모션) · 실행효과 실측 기반 파라미터 자기학습\n'
            '- **AI 2.0 로드맵**: EHUB 10분 주문 감지 → 이벤트 드리븐 장중 즉시 재배치 (24시간 실시간)')

    st.caption('© 2026 Fashion BG · CAIO실 AX 혁신팀 · 강훈구  |  AI 1.0 (테스트) — 위험 확률 레이더 · AI 브리핑 · XAI 권고 사유 / 엔진·승인 기능은 v5.6 탭 이용')
