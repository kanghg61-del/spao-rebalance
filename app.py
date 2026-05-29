# -*- coding: utf-8 -*-
"""
AI 온라인 재고 자동 재배치 — PoC 대시보드 v1.4

v1.6 변경:
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
    '공홈': '공홈', '이랜드몰': '이랜몰', '무신사': '무신사',
    '지그재그': '지그재', '네이버': '네이버', '카카오선물하기': '카카오',
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
    .stDataFrame { background-color: #15202C; font-size: 10px; color: #FFFFFF; }
    /* 셀 간격 축소 — 한 화면 표시 */
    .stDataFrame td, .stDataFrame th { padding: 2px 4px !important; }
    .stDataFrame thead th { font-size: 11px !important; padding: 4px 4px !important; }
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
    st.caption('PoC v1.6')

# ========== 탭 ==========
tab_d, tab_a, tab_c, tab_x, tab_ch = st.tabs(
    list(SCENARIOS.keys()) + ['🚫 제외 스타일', '📊 채널 별 세부']
)


@st.cache_data(show_spinner=False)
def load_data():
    return get_combined_data()


# v1.5 — 외부창고 제외 로직 반영 (캐시 강제 무효화)
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
        mode = '자동회전' if ship >= params['ship_rate_threshold'] else (
            '자동분배' if d['online_ratio'] >= params['online_ratio_threshold'] else '제외')
        results.append({'code': code, 'data': d, 'moves': moves,
                        'after': after, 'revenue': rev, 'mode': mode})
    return results


def render_scenario(scenario_key, container, allow_slider=False):
    preset = SCENARIOS[scenario_key]

    if allow_slider:
        # 탭 본문 상단에 5열 슬라이더 인라인 배치 — 사이드바 접혀 있어도 항상 보임
        container.markdown('### 🎛️ 사용자 정의 파라미터')
        sl_c1, sl_c2, sl_c3, sl_c4, sl_c5 = container.columns(5)
        with sl_c1:
            shortage_th = st.slider('부족 임계 (주)', 0.5, 4.0, preset['shortage_th'], 0.5, key=f'sh_{scenario_key}')
        with sl_c2:
            target_woc = st.slider('목표 재고주수 (주)', 1.0, 6.0, preset['target_woc'], 0.5, key=f'tg_{scenario_key}')
        with sl_c3:
            ship_th = st.slider('출고율 분기 (%)', 50, 100, int(preset['ship_th']*100), 5, key=f'sp_{scenario_key}') / 100
        with sl_c4:
            online_th = st.slider('온라인 비중 임계 (%)', 0, 50, int(preset['online_th']*100), 5, key=f'on_{scenario_key}') / 100
        with sl_c5:
            min_move = st.slider('이동 ≥ N장만', 0, 50, preset['min_move'], 1, key=f'mn_{scenario_key}')
    else:
        shortage_th = preset['shortage_th']
        target_woc = preset['target_woc']
        ship_th = preset['ship_th']
        online_th = preset['online_th']
        min_move = preset['min_move']

    container.markdown(f'<div class="scenario-box">{preset["desc"]}</div>', unsafe_allow_html=True)

    with st.spinner('계산 중...'):
        params_key = (shortage_th, target_woc, ship_th, online_th, min_move, 'v1.6_search_cache_bust')
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
    col_f1, col_f2, col_f_search, col_f3, col_f4 = container.columns([1.5, 1.8, 3, 2, 1.7])
    with col_f1:
        show_only_moved = st.checkbox(f'이동 발생만', value=True, key=f'moved_{scenario_key}')
    with col_f2:
        mode_filter = st.multiselect('모드', ['자동회전', '자동분배', '제외'], default=['자동회전', '자동분배'], key=f'mode_{scenario_key}')
    with col_f_search:
        search_code = st.text_input(
            '단품코드 검색',
            placeholder='앞 10자리만 입력해도 OK (예: SPPPG25U05)',
            key=f'search_{scenario_key}',
        ).strip().upper()
    with col_f3:
        sort_by = st.selectbox('정렬', ['온라인 매출 순위 ↑', '기대효과 ↓', '이동수량 ↓', '단품코드'], key=f'sort_{scenario_key}')
    with col_f4:
        hide_locked = st.checkbox('잠금 SKU 숨김', value=False, key=f'lock_{scenario_key}')

    # 제외 스타일 적용 (session_state) — 해당 단품은 mode='-'로 강제 → 이동 제외
    excluded_codes = st.session_state.get('excluded_codes', set())
    for r in results:
        code = r.get('code', '')
        if any(ex.strip() and ex.strip() in code for ex in excluded_codes):
            r['mode'] = '제외'  # 제외 스타일
            r['moves'] = {k: 0 for k in r['moves']}
            r['revenue'] = 0

    filtered = [r for r in results if r['mode'] in mode_filter]
    if show_only_moved:
        filtered = [r for r in filtered if any(v != 0 for v in r['moves'].values())]
    if hide_locked:
        filtered = [r for r in filtered if not r['data'].get('locked')]
    # 단품코드 검색 (앞부분 일치 — 10자리 입력해도 매칭)
    if search_code:
        filtered = [r for r in filtered if r['code'].upper().startswith(search_code)]

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
        # 단품명 14자 cap
        name = d['name']
        if len(name) > 14: name = name[:13] + '…'
        row = [r['code'], d.get('rank_online', '-'), name, f"{int(d['ship_rate']*100)}%", r['mode']]
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
            [('', '단품코드'), ('', '온라인순위'), ('', '단품명'), ('', '출고율'), ('', '모드')] +
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

        # st.dataframe 행 선택 — MultiIndex + Styler 색상 유지 + 체크박스(좌측)
        # selection_mode="multi-row"는 자동으로 좌측에 선택 컬럼 추가
        container.caption('💡 좌측 ☑ 박스 클릭으로 단품 선택 · 헤더 클릭으로 전체 선택')

        event = container.dataframe(
            styled,
            use_container_width=True,
            height=620,
            hide_index=True,
            on_select='rerun',
            selection_mode='multi-row',
            key=f'mat_{scenario_key}',
        )
        selected_rows = event.selection.rows if (event and event.selection) else []
        sel_count = len(selected_rows) if selected_rows else len(df)
        if not selected_rows:
            container.caption(f'✅ 미선택 시 전체 {len(df):,}건 실행 대상')
        else:
            container.caption(f'✅ 선택: **{sel_count:,}건** / 전체 {len(df):,}건')
    else:
        container.info('필터 조건에 맞는 단품이 없습니다.')
        sel_count = 0

    container.caption(
        '🎨 **재고보유주수**: 🔴 < 2주   🟡 2~4주   🟢 ≥ 4주    |    '
        '**이동수량**: 🟢 +IN  🔴 -OUT  ⚪ 0    |    '
        '단위: 재고/이동후 = "주" · 이동 = "장(±)" · 효과 = "만원"'
    )

    col_b1, col_b2, col_b3 = container.columns([2, 2, 4])
    with col_b1:
        if st.button(f'✅ 선택 {sel_count}건 승인', use_container_width=True, type='primary', key=f'approve_{scenario_key}'):
            st.success(f'✓ 선택 {sel_count}건 → SAP BAPI 전송 완료 (mock)')
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

# === 🚫 제외 스타일 탭 ===
with tab_x:
    st.markdown('### 🚫 자동 재배치 제외 스타일')
    st.caption('예약판매·기획전·단독 스타일 등 자동 이동에서 제외할 단품코드를 입력하세요. '
               '코드의 일부만 입력해도 매칭됩니다 (예: SPACG24 → SPACG24로 시작하는 모든 단품 제외).')

    col_in, col_stat = st.columns([3, 1])
    with col_in:
        excluded_text = st.text_area(
            '제외 단품코드 (줄바꿈 또는 쉼표로 구분)',
            value=st.session_state.get('excluded_text', ''),
            height=200,
            placeholder='예시:\nSPJJG25G0119095\nSPACG24A5\n(부분 일치도 가능)',
            key='excluded_text_input',
        )
        # 파싱 + 저장
        codes_set = set()
        for line in excluded_text.replace(',', '\n').split('\n'):
            code = line.strip()
            if code:
                codes_set.add(code)
        st.session_state['excluded_codes'] = codes_set
        st.session_state['excluded_text'] = excluded_text

    with col_stat:
        st.metric('제외 패턴 수', f'{len(codes_set):,}')
        # 실제 매칭되는 단품 수 계산
        try:
            skus, _ = load_data()
            matched = 0
            for code in skus:
                if any(ex in code for ex in codes_set):
                    matched += 1
            st.metric('매칭 단품 수', f'{matched:,}')
        except Exception:
            st.metric('매칭 단품 수', '-')

        if st.button('🗑️ 전체 초기화', use_container_width=True):
            st.session_state['excluded_text'] = ''
            st.session_state['excluded_codes'] = set()
            st.rerun()

    st.markdown('---')
    st.caption('💡 **사용 예시**')
    st.markdown('''
    - **예약판매**: 예약 단품 코드 그대로 붙여넣기
    - **기획전**: `SPACG24A5` 처럼 시작 코드만 입력하면 해당 시즌 전체 제외
    - **단독 스타일**: 무신사 단독·지그재그 단독 등 채널별 단독 단품
    ''')

# === 📊 채널 별 세부 탭 ===
with tab_ch:
    st.markdown('### 📊 채널 담당자용 상세 데이터')

    channel_pick = st.radio(
        '채널 선택',
        CHANNELS,
        horizontal=True,
        key='ch_pick',
    )

    # 데이터 로드 (방어형 파라미터로 계산)
    preset = SCENARIOS['🛡️ 방어형 (추천)']
    params_key = (preset['shortage_th'], preset['target_woc'],
                  preset['ship_th'], preset['online_th'], preset['min_move'], 'v1.6_search_cache_bust')
    results_ch = calc_results(id(None), params_key)

    # 채널별 통계
    ch_total_inv = sum(r['data']['inv'].get(channel_pick, 0) for r in results_ch)
    ch_total_ord = sum(r['data']['orders'].get(channel_pick, 0) for r in results_ch)
    ch_skus_w_ord = sum(1 for r in results_ch if r['data']['orders'].get(channel_pick, 0) > 0)
    ch_in = sum(max(0, r['moves'].get(channel_pick, 0)) for r in results_ch)
    ch_out = sum(min(0, r['moves'].get(channel_pick, 0)) for r in results_ch)
    ch_shortage = sum(1 for r in results_ch
                      if r['data']['orders'].get(channel_pick, 0) > 0
                      and r['data']['inv'].get(channel_pick, 0) / max(1, r['data']['orders'].get(channel_pick, 1)) < 1)

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric('총 재고', f'{ch_total_inv:,}장')
    k2.metric('주간 주문', f'{ch_total_ord:,}장')
    k3.metric('운영 SKU', f'{ch_skus_w_ord:,}건')
    k4.metric('결품 SKU', f'{ch_shortage:,}건', f'{ch_shortage/max(1,ch_skus_w_ord)*100:.1f}%')
    k5.metric('금주 IN', f'{ch_in:,}장')
    k6.metric('금주 OUT', f'{abs(ch_out):,}장')

    st.markdown(f'#### {channel_pick} 단품 상세')

    # 정렬·필터
    cf1, cf2, cf3 = st.columns([2, 2, 2])
    with cf1:
        only_ord = st.checkbox('주문 발생 단품만', value=True, key='ch_only_ord')
    with cf2:
        only_moved = st.checkbox('이동 발생 단품만', value=False, key='ch_only_moved')
    with cf3:
        ch_sort = st.selectbox('정렬', ['주문 ↓', '재고주수 ↑ (결품순)', '이동량 ↓', '온라인 순위 ↑'], key='ch_sort')

    ch_rows = []
    for r in results_ch:
        o = r['data']['orders'].get(channel_pick, 0)
        i = r['data']['inv'].get(channel_pick, 0)
        mv = r['moves'].get(channel_pick, 0)
        if only_ord and o == 0:
            continue
        if only_moved and mv == 0:
            continue
        woc = i / o if o > 0 else None
        ch_rows.append({
            '단품코드': r['code'],
            '단품명': (r['data']['name'][:18] + '…') if len(r['data']['name']) > 18 else r['data']['name'],
            '온라인순위': r['data'].get('rank_online', 9999),
            '정상가': r['data'].get('price', 0),
            '재고(장)': i,
            '주문(장/주)': o,
            '재고주수': round(woc, 1) if woc is not None else None,
            '결품여부': '🔴' if (woc is not None and woc < 1) else '🟡' if (woc is not None and woc < 2) else '🟢' if woc is not None else '',
            '추천이동(장)': mv,
            '이동후재고': i + mv,
        })

    if ch_sort == '주문 ↓':
        ch_rows.sort(key=lambda x: -x['주문(장/주)'])
    elif ch_sort == '재고주수 ↑ (결품순)':
        ch_rows.sort(key=lambda x: x['재고주수'] if x['재고주수'] is not None else 999)
    elif ch_sort == '이동량 ↓':
        ch_rows.sort(key=lambda x: -abs(x['추천이동(장)']))
    else:
        ch_rows.sort(key=lambda x: x['온라인순위'])

    # Top 500만 표시
    if len(ch_rows) > 500:
        st.caption(f'⚠️ {len(ch_rows):,}건 中 상위 500건 표시')
        ch_rows = ch_rows[:500]

    if ch_rows:
        df_ch = pd.DataFrame(ch_rows)
        st.dataframe(df_ch, use_container_width=True, height=500, hide_index=True)
    else:
        st.info('표시할 단품이 없습니다.')

    st.caption('🎨 결품여부: 🔴 1주 미만 (긴급)  🟡 1~2주  🟢 2주 이상')

st.caption('© 2026 Fashion BG · CAIO실 AX 혁신팀 · 강훈구  |  PoC v1.6')
