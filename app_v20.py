# -*- coding: utf-8 -*-
"""
v2.0 화면 — 자동분배 제거 · 리오더코드 병합 · 외부창고(AENS/ADU3/ADQS) 분리
(페이지 설정·비밀번호 게이트·공통 CSS는 app.py 담당)
"""
import streamlit as st
import pandas as pd

from rebalance_engine import calc_rebalance, calc_after_woc, calc_expected_revenue
from mock_data import (
    get_combined_data, get_last_update_time, get_reorder_info,
    CHANNELS, EXT_WAREHOUSE,
)

CH_SHORT = {
    '공홈': '공홈', '이랜드몰': '이몰', '무신사': '무신',
    '지그재그': '지재', '네이버': '네이', '카카오선물하기': '카카오',
}
EXT_CHANNELS = [c for c in CHANNELS if c in EXT_WAREHOUSE]  # 무신사·지그재그·네이버

SCENARIOS = {
    '🛡️ 방어형 (추천)': {
        'desc': '부족 1주 / 목표 4주 — 결품 임박 시 4주까지 충분히 충전. 운영 부담 최소·효과 극대',
        'shortage_th': 1.0, 'target_woc': 4.0,
        'ship_th': 0.90, 'min_move': 0,
    },
    '⚡ 공격형': {
        'desc': '부족 2주 / 목표 4주 — 결품 발생 전 선제 재배치. 이동량 증가, 효과는 방어형과 유사',
        'shortage_th': 2.0, 'target_woc': 4.0,
        'ship_th': 0.90, 'min_move': 0,
    },
    '🎛️ 사용자 정의': {
        'desc': '사이드바 슬라이더로 직접 조정',
        'shortage_th': 1.0, 'target_woc': 2.0,
        'ship_th': 0.90, 'min_move': 10,
    },
}


@st.cache_data(show_spinner=False)
def load_data_v20():
    return get_combined_data('v2')


@st.cache_data(show_spinner=False)
def calc_results_v20(params_key):
    skus = load_data_v20()
    params = {
        'shortage_threshold': params_key[0], 'target_woc': params_key[1],
        'ship_rate_threshold': params_key[2], 'min_move_qty': params_key[3],
    }
    results = []
    for code, d in skus.items():
        moves = calc_rebalance(d, params, CHANNELS)
        after = calc_after_woc(d, moves, CHANNELS)
        rev = calc_expected_revenue(d, moves, CHANNELS, d['price'])
        results.append({'code': code, 'data': d, 'moves': moves,
                        'after': after, 'revenue': rev})
    return results


def render_scenario(scenario_key, container, allow_slider=False):
    preset = SCENARIOS[scenario_key]

    if allow_slider:
        st.sidebar.markdown('### 🎛️ 사용자 정의 파라미터')
        shortage_th = st.sidebar.slider('부족 임계 (주)', 0.5, 4.0, preset['shortage_th'], 0.5)
        target_woc = st.sidebar.slider('목표 재고주수 (주)', 1.0, 6.0, preset['target_woc'], 0.5)
        ship_th = st.sidebar.slider('출고율 분기 (%)', 50, 100, int(preset['ship_th']*100), 5) / 100
        min_move = st.sidebar.slider('이동 ≥ N장만 (비부가 제거)', 0, 50, preset['min_move'], 1)
    else:
        shortage_th = preset['shortage_th']
        target_woc = preset['target_woc']
        ship_th = preset['ship_th']
        min_move = preset['min_move']

    container.markdown(f'<div class="scenario-box">{preset["desc"]}</div>', unsafe_allow_html=True)

    with st.spinner('계산 중...'):
        params_key = (shortage_th, target_woc, ship_th, min_move)
        results = calc_results_v20(params_key)

    total_skus = len(results)
    moved_count = sum(1 for r in results if any(v != 0 for v in r['moves'].values()))
    total_in = sum(sum(v for v in r['moves'].values() if v > 0) for r in results)
    total_rev = sum(r['revenue'] for r in results)

    def kpi_card(col, label, value, sub=''):
        col.markdown(f"""<div class="kpi-card"><div class="kpi-label">{label}</div>
            <div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>""", unsafe_allow_html=True)

    k1, k2, k3, k4, k5 = container.columns(5)
    kpi_card(k1, '전체 단품', f'{total_skus:,}', '6채널 · 리오더 병합 후')
    kpi_card(k2, '이동 발생', f'{moved_count:,}', f'{moved_count/max(1,total_skus)*100:.1f}%')
    kpi_card(k3, '총 이동량', f'{total_in:,}장', '주간 IN')
    kpi_card(k4, '회수 매출', f'{total_rev/100000000:.2f}억', '주간')
    kpi_card(k5, '연 환산', f'{total_rev*52/100000000:.0f}억', '× 52주')

    col_f1, col_f2, col_f3, col_f4 = container.columns([2, 2, 2, 2])
    with col_f1:
        show_only_moved = st.checkbox('이동 발생만', value=True, key=f'moved_{scenario_key}')
    with col_f2:
        show_only_reorder = st.checkbox('리오더 병합만', value=False, key=f'reorder_{scenario_key}')
    with col_f3:
        sort_by = st.selectbox('정렬', ['온라인 매출 순위 ↑', '기대효과 ↓', '이동수량 ↓', '단품코드'], key=f'sort_{scenario_key}')
    with col_f4:
        hide_locked = st.checkbox('잠금 SKU 숨김', value=False, key=f'lock_{scenario_key}')

    filtered = results
    if show_only_moved:
        filtered = [r for r in filtered if any(v != 0 for v in r['moves'].values())]
    if show_only_reorder:
        filtered = [r for r in filtered if r['data'].get('reorder_codes')]
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

    def wh_color(v):
        if v in (None, '', 0) or pd.isna(v): return ''
        return 'background-color: #1C2836; color: #8AB4F8; text-align:center'

    MAX_ROWS = 1000
    if len(filtered) > MAX_ROWS:
        container.caption(f'⚠️ {len(filtered):,}건 中 상위 {MAX_ROWS}개만 표시 (성능). 정렬·필터로 좁히세요.')
        filtered = filtered[:MAX_ROWS]

    rows = []
    for r in filtered:
        d = r['data']; mv = r['moves']; af = r['after']; inv = d['inv']
        name = d['name']
        if len(name) > 18: name = name[:17] + '…'
        n_reo = len(d.get('reorder_codes', []))
        row = [d.get('rank_online', '-'), name,
               f'+{n_reo}' if n_reo else '', f"{int(d['ship_rate']*100)}%"]
        for c in CHANNELS:
            o = d['orders'].get(c, 0)
            w = inv.get(c, 0) / o if o > 0 else None
            row.append(f'{round(w)}주' if w is not None else '')
        for c in EXT_CHANNELS:
            q = d.get('ext_wh', {}).get(c, 0)
            row.append(int(q) if q else 0)
        for c in CHANNELS:
            v = mv.get(c, 0)
            row.append('0' if v == 0 else f'{v:+d}')
        for c in CHANNELS:
            w = af.get(c)
            row.append(f'{round(w)}주' if w is not None else '')
        row.append(round(r['revenue'] / 10000))
        rows.append(row)

    if rows:
        wh_sub = {c: f'{CH_SHORT[c]}({EXT_WAREHOUSE[c][1]})' for c in EXT_CHANNELS}
        columns = pd.MultiIndex.from_tuples(
            [('', '온라인순위'), ('', '단품명'), ('', '리오더'), ('', '출고율')] +
            [('현 재고보유주수', CH_SHORT[c]) for c in CHANNELS] +
            [('외부창고 재고량 (장)', wh_sub[c]) for c in EXT_CHANNELS] +
            [('이동수량 (장)', CH_SHORT[c]) for c in CHANNELS] +
            [('이동 후 재고보유주수', CH_SHORT[c]) for c in CHANNELS] +
            [('효과', '만원')]
        )
        df = pd.DataFrame(rows, columns=columns)

        woc_cols = [('현 재고보유주수', CH_SHORT[c]) for c in CHANNELS] + \
                   [('이동 후 재고보유주수', CH_SHORT[c]) for c in CHANNELS]
        mv_cols = [('이동수량 (장)', CH_SHORT[c]) for c in CHANNELS]
        wh_cols = [('외부창고 재고량 (장)', wh_sub[c]) for c in EXT_CHANNELS]

        styled = df.style.map(woc_color, subset=woc_cols).map(mv_color, subset=mv_cols)
        styled = styled.map(wh_color, subset=wh_cols)
        styled = styled.format({('효과', '만원'): '{:,}'.format})

        container.dataframe(styled, use_container_width=True, height=700, hide_index=True)
    else:
        container.info('필터 조건에 맞는 단품이 없습니다.')

    container.caption(
        '🎨 **재고보유주수**: 🔴 < 2주   🟡 2~4주   🟢 ≥ 4주    |    '
        '**이동수량**: 🟢 +IN  🔴 -OUT  ⚪ 0    |    '
        '**외부창고**: 무신사 풀필먼트(AENS) · 지그재그 천안(ADU3) · 네이버 CMS(ADQS) — '
        '채널 재고에 포함되나 타 채널 회수(OUT) 대상에서 제외    |    '
        '**리오더**: +N = 리오더코드 N건 병합 (기존코드 기준 노출)    |    '
        '단위: 재고/이동후 = "주" · 이동/외부창고 = "장" · 효과 = "만원"'
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




def render():
    st.markdown('<div class="title-bar">REBA_재고재배치 Agent — 운영 대시보드<span class="ver-badge">v2.0</span></div>', unsafe_allow_html=True)
    last = get_last_update_time()
    reorder_info = get_reorder_info()
    if reorder_info['file']:
        reorder_txt = f"리오더 병합: {reorder_info['merged']:,}건 ({reorder_info['file']})"
    else:
        reorder_txt = '리오더 매핑 파일 없음 (reorder_mapping.csv 추가 시 자동 병합)'
    col_a, col_b, col_c = st.columns([4, 1, 1])
    with col_a:
        st.caption(
            f'마지막 갱신: **{last.strftime("%Y-%m-%d %H:%M")}**   |   '
            f'다음 갱신: 매일 06:00 (Airflow · EHUB 06:00 & 샵링크 06:30 배치 후)   |   '
            f'{reorder_txt}'
        )
    with col_b:
        if st.button('🔄 새로고침', use_container_width=True):
            st.rerun()
    with col_c:
        st.caption('v2.0')


    tab_d, tab_a, tab_c = st.tabs(list(SCENARIOS.keys()))


    with tab_d:
        render_scenario('🛡️ 방어형 (추천)', st, allow_slider=False)

    with tab_a:
        render_scenario('⚡ 공격형', st, allow_slider=False)

    with tab_c:
        render_scenario('🎛️ 사용자 정의', st, allow_slider=True)

    st.caption('© 2026 Fashion BG · CAIO실 AX 혁신팀 · 강훈구  |  v2.0 — 자동분배 제거 · 리오더 병합 · 외부창고 분리')

