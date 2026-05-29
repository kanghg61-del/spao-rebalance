# -*- coding: utf-8 -*-
"""
AI 온라인 재고 자동 재배치 — PoC 대시보드 v1.3

v1.2 변경:
  - 시나리오 선택 (방어형 / 공격형 / 사용자 정의)
  - 단품 500개로 확장 (KPI 회수 매출 현실화)
  - MultiIndex 헤더 (재고 / 이동 / 이동 후 그룹)
  - 표 높이 700px (Excel 수준 가독성)
"""
import streamlit as st
import pandas as pd
from datetime import datetime

from rebalance_engine import calc_rebalance, calc_after_woc, calc_expected_revenue
from mock_data import (
    get_combined_data, get_last_update_time,
    CHANNELS, BW_NAME
)

CH_SHORT = {'공홈':'공홈','이랜드몰':'이몰','무신사':'무신','지그재그':'지재','네이버':'네이','사방넷':'사방'}
BW_SHORT = '반응'

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


# 시나리오 프리셋 (PPT 9페이지 시뮬 결과 기준)
SCENARIOS = {
    '🛡️ 방어형 (추천)': {
        'desc': '부족 임계 1주 / 목표 2주 — 결품 임박 단품만 보수적 트리거. SAP 부하·물류 부담 최소화',
        'shortage_th': 1.0, 'target_woc': 2.0,
        'ship_th': 0.90, 'online_th': 0.10, 'min_move': 10,
    },
    '⚡ 공격형': {
        'desc': '부족 임계 2주 / 목표 4주 — 결품 발생 전 선제 재배치. 이동량 35%↑ 효과 차이 미미',
        'shortage_th': 2.0, 'target_woc': 4.0,
        'ship_th': 0.90, 'online_th': 0.10, 'min_move': 10,
    },
    '🎛️ 사용자 정의': {
        'desc': '슬라이더로 직접 조정',
        'shortage_th': 1.0, 'target_woc': 2.0,
        'ship_th': 0.90, 'online_th': 0.10, 'min_move': 10,
    },
}

# CSS
st.markdown("""
<style>
    .stApp { background-color: #0A141F; }
    .stSidebar { background-color: #15202C; }
    h1, h2, h3, h4 { color: #FFFFFF; }
    .kpi-card {
        background: #15202C;
        border: 1px solid #4AE3B5;
        border-radius: 8px;
        padding: 10px 12px;
        text-align: center;
    }
    .kpi-label { color: #B0B7C3; font-size: 11px; margin-bottom: 2px; }
    .kpi-value { color: #4AE3B5; font-size: 24px; font-weight: bold; }
    .kpi-sub   { color: #6F7A8B; font-size: 10px; margin-top: 2px; }
    .title-bar {
        border-left: 4px solid #4AE3B5;
        padding-left: 12px;
        color: white;
        font-size: 22px;
        font-weight: bold;
        margin: 4px 0 12px 0;
    }
    .scenario-box {
        background: #1C2836;
        border-left: 3px solid #4AE3B5;
        padding: 8px 12px;
        border-radius: 4px;
        color: #B0B7C3;
        font-size: 11px;
        margin-bottom: 8px;
    }
    .stDataFrame { background-color: #15202C; font-size: 11px; }
    .block-container { padding-top: 1rem !important; padding-bottom: 0.5rem !important; max-width: 100%; }
</style>
""", unsafe_allow_html=True)

# 헤더
st.markdown('<div class="title-bar">AI 온라인 재고 자동 재배치 — 운영 대시보드</div>', unsafe_allow_html=True)
last = get_last_update_time()
col_a, col_b, col_c = st.columns([4, 1, 1])
with col_a:
    st.caption(f'마지막 갱신: **{last.strftime("%Y-%m-%d %H:%M")}**   |   다음 갱신: 매일 03:00 (Airflow)   |   시나리오·파라미터는 좌측 ▶ 사이드바')
with col_b:
    if st.button('🔄 새로고침', use_container_width=True):
        st.rerun()
with col_c:
    st.caption('PoC v1.3')

# ========== 사이드바: 시나리오 + 파라미터 ==========
st.sidebar.markdown('### 🎯 시나리오')
scenario_key = st.sidebar.radio(
    '운영 모드 선택',
    list(SCENARIOS.keys()),
    index=0,  # 기본: 방어형
    label_visibility='collapsed',
)
preset = SCENARIOS[scenario_key]
st.sidebar.markdown(f'<div class="scenario-box">{preset["desc"]}</div>', unsafe_allow_html=True)

st.sidebar.markdown('---')
st.sidebar.markdown('### 🎛️ 파라미터')

is_custom = scenario_key == '🎛️ 사용자 정의'

if is_custom:
    shortage_th = st.sidebar.slider('부족 임계 (주)', 0.5, 4.0, preset['shortage_th'], 0.5)
    target_woc = st.sidebar.slider('목표 재고주수 (주)', 1.0, 6.0, preset['target_woc'], 0.5)
    ship_th = st.sidebar.slider('출고율 분기 (%)', 50, 100, int(preset['ship_th']*100), 5) / 100
    online_th = st.sidebar.slider('온라인 비중 임계 (%)', 0, 50, int(preset['online_th']*100), 5) / 100
    min_move = st.sidebar.slider('이동 ≥ N장만 (비부가 제거)', 0, 50, preset['min_move'], 1)
else:
    # 프리셋 표시만 (수정 불가)
    shortage_th = preset['shortage_th']
    target_woc = preset['target_woc']
    ship_th = preset['ship_th']
    online_th = preset['online_th']
    min_move = preset['min_move']
    st.sidebar.markdown(f"""
        - **부족 임계**: {shortage_th}주
        - **목표 재고주수**: {target_woc}주
        - **출고율 분기**: {int(ship_th*100)}%
        - **온라인 비중 임계**: {int(online_th*100)}%
        - **이동 ≥ N장 필터**: {min_move}장
    """)
    st.sidebar.caption('🎛️ 사용자 정의 선택 시 슬라이더로 조정 가능')

st.sidebar.markdown('---')
with st.sidebar.expander('데이터 소스', expanded=False):
    st.write('재고: SAP CDS View')
    st.write('주문: 6채널 API')
    st.warning('PoC mock — 500개 단품')
    seed = st.number_input('시드 (mock 변경)', value=42, step=1)

params = {
    'shortage_threshold': shortage_th, 'target_woc': target_woc,
    'ship_rate_threshold': ship_th, 'online_ratio_threshold': online_th,
    'min_move_qty': min_move,
}

# 데이터 + 계산
@st.cache_data(show_spinner=False)
def load_and_calc(seed, params):
    skus = get_combined_data(seed=seed)
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
    return skus, results

with st.spinner('계산 중...'):
    skus, results = load_and_calc(seed, params)

# KPI
total_skus = len(results)
moved_count = sum(1 for r in results if any(v != 0 for v in r['moves'].values()))
total_in = sum(sum(v for v in r['moves'].values() if v > 0) for r in results)
total_rev = sum(r['revenue'] for r in results)

def kpi_card(col, label, value, sub=''):
    col.markdown(f"""<div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        <div class="kpi-sub">{sub}</div></div>""", unsafe_allow_html=True)

k1, k2, k3, k4, k5 = st.columns(5)
kpi_card(k1, '전체 단품', f'{total_skus:,}', '6채널')
kpi_card(k2, '이동 발생', f'{moved_count:,}', f'{moved_count/max(1,total_skus)*100:.0f}%')
kpi_card(k3, '총 이동량', f'{total_in:,}장', '주간 IN')
kpi_card(k4, '회수 매출', f'{total_rev/100000000:.2f}억', '주간')
kpi_card(k5, '연 환산', f'{total_rev*52/100000000:.0f}억', '× 52주')

# 필터
col_f1, col_f2, col_f3, col_f4 = st.columns([2, 2, 2, 2])
with col_f1:
    show_only_moved = st.checkbox('이동 발생 단품만', value=True)
with col_f2:
    mode_filter = st.multiselect('모드', ['A', 'B', '-'], default=['A', 'B'])
with col_f3:
    sort_by = st.selectbox('정렬', ['기대효과 ↓', '이동수량 ↓', '단품코드 ↑'])
with col_f4:
    hide_locked = st.checkbox('잠금 SKU 숨김', value=False)

filtered = [r for r in results if r['mode'] in mode_filter]
if show_only_moved:
    filtered = [r for r in filtered if any(v != 0 for v in r['moves'].values())]
if hide_locked:
    filtered = [r for r in filtered if not r['data'].get('locked')]

if sort_by == '기대효과 ↓':
    filtered.sort(key=lambda r: -r['revenue'])
elif sort_by == '이동수량 ↓':
    filtered.sort(key=lambda r: -sum(v for v in r['moves'].values() if v > 0))
else:
    filtered.sort(key=lambda r: r['code'])

# 매트릭스
st.markdown(f'**단품 × 채널 매트릭스 ({len(filtered):,}건)** — 시나리오: **{scenario_key}**')

def woc_color(w):
    if w is None or w == '' or pd.isna(w): return ''
    try:
        wv = float(w)
    except: return ''
    if wv < 2: return 'background-color: #5B1E1E; color: #FF5A5F; font-weight:bold'
    if wv < 4: return 'background-color: #5A4500; color: #FFC000; font-weight:bold'
    return 'background-color: #1B4D3E; color: #4AE3B5; font-weight:bold'

def mv_color(v):
    if v is None or v == 0 or pd.isna(v): return ''
    if v > 0: return 'background-color: #1B4D3E; color: #4AE3B5; font-weight:bold; text-align:center'
    return 'background-color: #5B1E1E; color: #FF5A5F; font-weight:bold; text-align:center'

# DataFrame 구성 — MultiIndex 헤더
rows = []
for r in filtered:
    d = r['data']; mv = r['moves']; af = r['after']; inv = d['inv']
    name = d['name']
    if len(name) > 14: name = name[:13] + '…'
    row = [name, f"{int(d['ship_rate']*100)}%", r['mode']]
    # 재고주수 (정수)
    for c in CHANNELS:
        o = d['orders'].get(c, 0)
        w = inv.get(c, 0) / o if o > 0 else None
        row.append(round(w) if w is not None else None)
    # 이동
    row.append(mv.get(BW_NAME, 0))
    for c in CHANNELS:
        row.append(mv.get(c, 0))
    # 이동 후
    for c in CHANNELS:
        w = af.get(c)
        row.append(round(w) if w is not None else None)
    # 효과 (만원)
    row.append(round(r['revenue'] / 10000))
    rows.append(row)

if rows:
    # MultiIndex 컬럼
    columns = pd.MultiIndex.from_tuples(
        [('', '단품명'), ('', '출고율'), ('', '모드')] +
        [('재고 (주)', CH_SHORT[c]) for c in CHANNELS] +
        [('이동 (장)', BW_SHORT)] + [('이동 (장)', CH_SHORT[c]) for c in CHANNELS] +
        [('이동 후 (주)', CH_SHORT[c]) for c in CHANNELS] +
        [('효과', '만원')]
    )
    df = pd.DataFrame(rows, columns=columns)

    # 스타일링
    woc_cols = [('재고 (주)', CH_SHORT[c]) for c in CHANNELS] + \
               [('이동 후 (주)', CH_SHORT[c]) for c in CHANNELS]
    mv_cols = [('이동 (장)', BW_SHORT)] + [('이동 (장)', CH_SHORT[c]) for c in CHANNELS]

    styled = df.style
    styled = styled.map(woc_color, subset=woc_cols)
    styled = styled.map(mv_color, subset=mv_cols)
    # 재고주수: "N주" 표기 (이동수량과 헷갈리지 않게)
    def fmt_woc(x):
        if pd.isna(x) or x is None or x == '': return ''
        return f'{int(x)}주'
    # 이동수량: 부호(±) 표기 (0은 그대로)
    def fmt_mv(x):
        if pd.isna(x) or x is None or x == '': return ''
        v = int(x)
        if v == 0: return '0'
        return f'{v:+d}'
    styled = styled.format(fmt_woc, subset=woc_cols)
    styled = styled.format(fmt_mv, subset=mv_cols)
    styled = styled.format({('효과', '만원'): '{:,}'.format})

    st.dataframe(
        styled,
        use_container_width=True,
        height=700,
        hide_index=True,
    )
else:
    st.info('필터 조건에 맞는 단품이 없습니다.')

# 색상 룰 (한 줄)
st.caption(
    '🎨 **재고주수 (주)**: 🔴 < 2주 (결품 임박)   🟡 2~4주 (주의)   🟢 ≥ 4주 (안전)   |   '
    '**이동수량 (장)**: 🟢 +IN  🔴 -OUT  ⚪ 0   |   '
    '단위: 재고/이동후 = "주" · 이동 = "장(±)" · 효과 = "만원"'
)

# 승인 / Override
col_btn1, col_btn2, col_btn3 = st.columns([2, 2, 4])
with col_btn1:
    if st.button('✅ 전체 1-클릭 승인', use_container_width=True, type='primary'):
        st.success(f'✓ {moved_count}개 단품 / {total_in:,}장 → SAP BAPI 전송 완료 (mock)')
        st.balloons()
with col_btn2:
    if st.button('✋ Override 화면', use_container_width=True):
        st.info('실 배포 시 단품별 수정 다이얼로그 (현재 PoC mock)')
with col_btn3:
    st.caption('실 배포: 승인 → SAP BAPI 자동 호출 → audit log 기록')

st.caption('© 2026 Fashion BG · CAIO실 AX 혁신팀 · 강훈구  |  PoC v1.3')
