# -*- coding: utf-8 -*-
"""
AI 온라인 재고 자동 재배치 — PoC 대시보드 v1.4

v1.4 변경:
  - 실 데이터 8,308 단품 (보수운영.xlsx 추출)
  - 상단 탭: 🛡️ 방어형 / ⚡ 공격형 / 🎛️ 사용자 정의
  - 헤더: '현 재고보유주수' / '이동 후 재고보유주수'
  - 모든 주 단위 셀에 "N주" 표기 (정수 반올림)
  - 매출 순위(온라인 매출 랭킹) 기본 정렬
  - 전체 단품 매트릭스 (필터로 좁히기)
"""
import streamlit as st
import pandas as pd
from datetime import datetime

from rebalance_engine import calc_rebalance, calc_after_woc, calc_expected_revenue
from mock_data import (
    get_combined_data, get_last_update_time,
    CHANNELS, BW_NAME
)

CH_SHORT = {
    '공홈': '공홈', '이랜드몰': '이몰', '무신사': '무신',
    '지그재그': '지재', '네이버': '네이', '카카오선물하기': '카카오',
}
BW_SHORT = '반응'

# 시나리오 프리셋 (PPT 9페이지 시뮬 결과 기준 = 보수운영.xlsx 매칭)
SCENARIOS = {
    '🛡️ 방어형 (추천)': {
        'desc': '부족 1주 / 목표 4주 — 결품 임박 시 4주까지 충분히 충전. 운영 부담 최소·효과 극대',
        'shortage_th': 1.0, 'target_woc': 4.0,
        'ship_th': 0.90, 'online_th': 0.10, 'min_move': 0,
    },
    '⚡ 공격형': {
        'desc': '부족 2주 / 목표 4주 — 결품 발생 전 선제 재배치. 이동량 +31%, 효과는 방어형과 유사',
        'shortage_th': 2.0, 'target_woc': 4.0,
        'ship_th': 0.90, 'online_th': 0.10, 'min_move': 0,
    },
    '🎛️ 사용자 정의': {
        'desc': '사이드바 슬라이더로 직접 조정',
        'shortage_th': 1.0, 'target_woc': 2.0,
        'ship_th': 0.90, 'online_th': 0.10, 'min_move': 10,
    },
}

# ====== 비밀번호 게이트 + 페이지 설정 (Streamlit Cloud 배포용) ======
st.set_page_config(
    page_title='AI 재고 자동 재배치',
    page_icon='🔒',
    layout='wide',
    initial_sidebar_state='collapsed',
)
from auth import check_password
if not check_password():
    st.stop()
# ====================================================================

st.markdown("""
<style>
    .stApp { background-color: #0A141F; }
    .stSidebar { background-color: #15202C; }
    h1, h2, h3, h4 { color: #FFFFFF; }
    .kpi-card {
        background: #15202C; border: 1px solid #4AE3B5;
        border-radius: 8px; padding: 10px 12px; text-align: center;
    }
    .kpi-label { color: #FFFFFF; font-size: 11px; }
    .kpi-value { color: #4AE3B5; font-size: 26px; font-weight: bold; }
    .kpi-sub   { color: #6F7A8B; font-size: 10px; }
    .title-bar {
        border-left: 4px solid #4AE3B5; padding-left: 12px;
        color: white; font-size: 22px; font-weight: bold; margin: 4px 0 12px 0;
    }
    .scenario-box {
        background: #1C2836; border-left: 3px solid #4AE3B5;
        padding: 8px 12px; border-radius: 4px;
        color: #B0B7C3; font-size: 12px; margin-bottom: 8px;
    }
    .stDataFrame { background-color: #15202C; font-size: 11px; color: #FFFFFF; }
    .stCaption, .stCaption p, [data-testid="stCaptionContainer"] { color: #FFFFFF !important; }
    .stMarkdown, .stMarkdown p, .stMarkdown li { color: #FFFFFF !important; }
    .stTabs [data-baseweb="tab"] { color: #FFFFFF !important; }
    /* 일반 텍스트 */
    .stApp p, .stApp span, .stApp label, .stApp small, .stApp .stCheckbox label { color: #FFFFFF !important; }
    /* KPI 카드 부가 텍스트도 흰색 */
    .kpi-sub { color: #FFFFFF !important; }
    /* 시나리오 박스 */
    .scenario-box { color: #FFFFFF !important; }
    /* 매트릭스 헤더 그룹 색상 구분 — Group Level (multi-index 첫번째 행) */
    .stDataFrame thead tr:first-child th {
        background: #1E2D40 !important;
        color: #FFFFFF !important;
        font-weight: bold !important;
        font-size: 13px !important;
        border-right: 3px solid #0A141F !important;
        text-align: center !important;
    }
    .stDataFrame thead tr:nth-child(2) th {
        background: #15202C !important;
        color: #FFFFFF !important;
        font-weight: bold !important;
    }
    .stDataFrame tbody td { color: #FFFFFF !important; }
    .block-container { padding-top: 3rem !important; padding-bottom: 0.5rem !important; max-width: 100%; }
    /* 탭 디자인 */
    .stTabs [data-baseweb="tab-list"] { gap: 8px; background: transparent; }
    .stTabs [data-baseweb="tab"] {
        background: #15202C; border-radius: 8px 8px 0 0;
        padding: 10px 24px; color: #B0B7C3; font-size: 16px; font-weight: bold;
    }
    .stTabs [aria-selected="true"] {
        background: #4AE3B5 !important; color: #0A141F !important;
    }
    /* 사이드바 텍스트 흰색 처리 */
    [data-testid="stSidebar"] * {
        color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] .stMarkdown p,
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] h4,
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"],
    [data-testid="stSidebar"] .stCaption,
    [data-testid="stSidebar"] small {
        color: #FFFFFF !important;
    }
    /* 슬라이더 숫자 값도 흰색 */
    [data-testid="stSidebar"] [data-baseweb="slider"] div {
        color: #FFFFFF !important;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="title-bar">AI 온라인 재고 자동 재배치 — 운영 대시보드</div>', unsafe_allow_html=True)
last = get_last_update_time()
col_a, col_b, col_c = st.columns([4, 1, 1])
with col_a:
    st.caption(f'마지막 갱신: **{last.strftime("%Y-%m-%d %H:%M")}**   |   다음 갱신: 매일 03:00 (Airflow)   |   8,308 단품 (보수운영.xlsx 기준)')
with col_b:
    if st.button('🔄 새로고침', use_container_width=True):
        st.rerun()
with col_c:
    st.caption('PoC v1.4')

# ========== 탭 ==========
tab_d, tab_a, tab_c = st.tabs(list(SCENARIOS.keys()))


@st.cache_data(show_spinner=False)
def load_data():
    return get_combined_data()


@st.cache_data(show_spinner=False)
def calc_results(_skus_id, params_key):
    """모든 단품에 대해 재배치 계산. cache key는 params_key 튜플"""
    skus = load_data()
    params = {
        'shortage_threshold': params_key[0], 'target_woc': params_key[1],
        'ship_rate_threshold': params_key[2], 'online_ratio_threshold': params_key[3],
        'min_move_qty': params_key[4],
    }
    results = []
    for code, d in skus.items():
        moves = calc_rebalance(d, params, CHANNELS, BW_NAME)
        after = calc_after_woc(d, moves, CHANNELS)
        rev = calc_expected_revenue(d, moves, CHANNELS, d['price'])
        ship = d['ship_rate']
        mode = 'A' if ship >= params['ship_rate_threshold'] else (
            'B' if d['online_ratio'] >= params['online_ratio_threshold'] else '-')
        results.append({'code': code, 'data': d, 'moves': moves,
                        'after': after, 'revenue': rev, 'mode': mode})
    return results


def render_scenario(scenario_key, container, allow_slider=False):
    preset = SCENARIOS[scenario_key]

    if allow_slider:
        st.sidebar.markdown('### 🎛️ 사용자 정의 파라미터')
        shortage_th = st.sidebar.slider('부족 임계 (주)', 0.5, 4.0, preset['shortage_th'], 0.5)
        target_woc = st.sidebar.slider('목표 재고주수 (주)', 1.0, 6.0, preset['target_woc'], 0.5)
        ship_th = st.sidebar.slider('출고율 분기 (%)', 50, 100, int(preset['ship_th']*100), 5) / 100
        online_th = st.sidebar.slider('온라인 비중 임계 (%)', 0, 50, int(preset['online_th']*100), 5) / 100
        min_move = st.sidebar.slider('이동 ≥ N장만 (비부가 제거)', 0, 50, preset['min_move'], 1)
    else:
        shortage_th = preset['shortage_th']
        target_woc = preset['target_woc']
        ship_th = preset['ship_th']
        online_th = preset['online_th']
        min_move = preset['min_move']

    container.markdown(f'<div class="scenario-box">{preset["desc"]}</div>', unsafe_allow_html=True)

    with st.spinner('계산 중...'):
        params_key = (shortage_th, target_woc, ship_th, online_th, min_move)
        results = calc_results(id(None), params_key)

    # KPI
    total_skus = len(results)
    moved_count = sum(1 for r in results if any(v != 0 for v in r['moves'].values()))
    total_in = sum(sum(v for v in r['moves'].values() if v > 0) for r in results)
    total_rev = sum(r['revenue'] for r in results)

    def kpi_card(col, label, value, sub=''):
        col.markdown(f"""<div class="kpi-card"><div class="kpi-label">{label}</div>
            <div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>""", unsafe_allow_html=True)

    k1, k2, k3, k4, k5 = container.columns(5)
    kpi_card(k1, '전체 단품', f'{total_skus:,}', '6채널')
    kpi_card(k2, '이동 발생', f'{moved_count:,}', f'{moved_count/max(1,total_skus)*100:.1f}%')
    kpi_card(k3, '총 이동량', f'{total_in:,}장', '주간 IN')
    kpi_card(k4, '회수 매출', f'{total_rev/100000000:.2f}억', '주간')
    kpi_card(k5, '연 환산', f'{total_rev*52/100000000:.0f}억', '× 52주')

    # 필터
    col_f1, col_f2, col_f3, col_f4 = container.columns([2, 2, 2, 2])
    with col_f1:
        show_only_moved = st.checkbox(f'이동 발생만', value=True, key=f'moved_{scenario_key}')
    with col_f2:
        mode_filter = st.multiselect('모드', ['A', 'B', '-'], default=['A', 'B'], key=f'mode_{scenario_key}')
    with col_f3:
        sort_by = st.selectbox('정렬', ['온라인 매출 순위 ↑', '기대효과 ↓', '이동수량 ↓', '단품코드'], key=f'sort_{scenario_key}')
    with col_f4:
        hide_locked = st.checkbox('잠금 SKU 숨김', value=False, key=f'lock_{scenario_key}')

    filtered = [r for r in results if r['mode'] in mode_filter]
    if show_only_moved:
        filtered = [r for r in filtered if any(v != 0 for v in r['moves'].values())]
    if hide_locked:
        filtered = [r for r in filtered if not r['data'].get('locked')]

    if sort_by == '온라인 매출 순위 ↑':
        filtered.sort(key=lambda r: r['data'].get('rank_online', 9999))
    elif sort_by == '기대효과 ↓':
        filtered.sort(key=lambda r: -r['revenue'])
    elif sort_by == '이동수량 ↓':
        filtered.sort(key=lambda r: -sum(v for v in r['moves'].values() if v > 0))
    else:
        filtered.sort(key=lambda r: r['code'])

    container.markdown(f'**단품 × 채널 매트릭스 — {len(filtered):,}건**')

    def woc_color(w):
        if w is None or w == '' or pd.isna(w): return ''
        try:
            v = float(str(w).replace('주', ''))
        except: return ''
        if v < 2: return 'background-color: #5B1E1E; color: #FF5A5F; font-weight:bold'
        if v < 4: return 'background-color: #5A4500; color: #FFC000; font-weight:bold'
        return 'background-color: #1B4D3E; color: #4AE3B5; font-weight:bold'

    def mv_color(v):
        if v is None or v == 0 or pd.isna(v) or v == '': return ''
        try:
            vv = int(str(v).replace('+', ''))
        except: return ''
        if vv > 0: return 'background-color: #1B4D3E; color: #4AE3B5; font-weight:bold; text-align:center'
        return 'background-color: #5B1E1E; color: #FF5A5F; font-weight:bold; text-align:center'

    # Top N 제한 (성능)
    MAX_ROWS = 1000
    if len(filtered) > MAX_ROWS:
        container.caption(f'⚠️ {len(filtered):,}건 中 상위 {MAX_ROWS}개만 표시 (성능). 정렬·필터로 좁히세요.')
        filtered = filtered[:MAX_ROWS]

    # DataFrame
    rows = []
    for r in filtered:
        d = r['data']; mv = r['moves']; af = r['after']; inv = d['inv']
        # 단품명 18자 cap
        name = d['name']
        if len(name) > 18: name = name[:17] + '…'
        row = [d.get('rank_online', '-'), name, f"{int(d['ship_rate']*100)}%", r['mode']]
        # 현 재고보유주수: 정수 + "주"
        for c in CHANNELS:
            o = d['orders'].get(c, 0)
            w = inv.get(c, 0) / o if o > 0 else None
            row.append(f'{round(w)}주' if w is not None else '')
        # 이동수량 (반응 + 6채널) — 부호 표시
        v = mv.get(BW_NAME, 0)
        row.append('0' if v == 0 else f'{v:+d}')
        for c in CHANNELS:
            v = mv.get(c, 0)
            row.append('0' if v == 0 else f'{v:+d}')
        # 이동 후 재고보유주수
        for c in CHANNELS:
            w = af.get(c)
            row.append(f'{round(w)}주' if w is not None else '')
        # 효과 (만원)
        row.append(round(r['revenue'] / 10000))
        rows.append(row)

    if rows:
        columns = pd.MultiIndex.from_tuples(
            [('', '온라인순위'), ('', '단품명'), ('', '출고율'), ('', '모드')] +
            [('현 재고보유주수', CH_SHORT[c]) for c in CHANNELS] +
            [('이동수량 (장)', BW_SHORT)] + [('이동수량 (장)', CH_SHORT[c]) for c in CHANNELS] +
            [('이동 후 재고보유주수', CH_SHORT[c]) for c in CHANNELS] +
            [('효과', '만원')]
        )
        df = pd.DataFrame(rows, columns=columns)

        woc_cols = [('현 재고보유주수', CH_SHORT[c]) for c in CHANNELS] + \
                   [('이동 후 재고보유주수', CH_SHORT[c]) for c in CHANNELS]
        mv_cols = [('이동수량 (장)', BW_SHORT)] + [('이동수량 (장)', CH_SHORT[c]) for c in CHANNELS]

        styled = df.style.map(woc_color, subset=woc_cols).map(mv_color, subset=mv_cols)
        styled = styled.format({('효과', '만원'): '{:,}'.format})

        # 그룹 경계선 — 현재고/이동수량/이동후 경계에 굵은 좌측 보더
        first_inv = [('현 재고보유주수', CH_SHORT[CHANNELS[0]])]
        first_mv = [('이동수량 (장)', BW_SHORT)]
        first_after = [('이동 후 재고보유주수', CH_SHORT[CHANNELS[0]])]
        effect_col = [('효과', '만원')]
        styled = styled.set_properties(
            subset=first_inv, **{'border-left': '3px solid #4AE3B5'}
        ).set_properties(
            subset=first_mv, **{'border-left': '3px solid #FFC000'}
        ).set_properties(
            subset=first_after, **{'border-left': '3px solid #B388FF'}
        ).set_properties(
            subset=effect_col, **{'border-left': '3px solid #FF7B7B'}
        )
        # 헤더 그룹별 배경색 — set_table_styles로 colspan 헤더에 적용
        styled = styled.set_table_styles([
            {'selector': 'th.col_heading.level0', 'props': [
                ('text-align', 'center'),
                ('font-weight', 'bold'),
                ('padding', '8px 4px'),
                ('border-bottom', '2px solid #4AE3B5'),
            ]},
        ], overwrite=False)

        container.dataframe(styled, use_container_width=True, height=700, hide_index=True)
    else:
        container.info('필터 조건에 맞는 단품이 없습니다.')

    container.caption(
        '🎨 **재고보유주수**: 🔴 < 2주   🟡 2~4주   🟢 ≥ 4주    |    '
        '**이동수량**: 🟢 +IN  🔴 -OUT  ⚪ 0    |    '
        '단위: 재고/이동후 = "주" · 이동 = "장(±)" · 효과 = "만원"'
    )

    col_b1, col_b2, col_b3 = container.columns([2, 2, 4])
    with col_b1:
        if st.button('✅ 전체 1-클릭 승인', use_container_width=True, type='primary', key=f'approve_{scenario_key}'):
            st.success(f'✓ {moved_count}개 단품 / {total_in:,}장 → SAP BAPI 전송 완료 (mock)')
            st.balloons()
    with col_b2:
        if st.button('✋ Override 화면', use_container_width=True, key=f'override_{scenario_key}'):
            st.info('실 배포 시 단품별 수정 다이얼로그 (현재 PoC mock)')
    with col_b3:
        container.caption('실 배포: 승인 → SAP BAPI 자동 호출 → audit log 기록')


with tab_d:
    render_scenario('🛡️ 방어형 (추천)', st, allow_slider=False)

with tab_a:
    render_scenario('⚡ 공격형', st, allow_slider=False)

with tab_c:
    render_scenario('🎛️ 사용자 정의', st, allow_slider=True)

st.caption('© 2026 Fashion BG · CAIO실 AX 혁신팀 · 강훈구  |  PoC v1.4')
