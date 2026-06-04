# -*- coding: utf-8 -*-
"""
v2.1 화면 — 자동분배 제거 · 리오더코드 병합 · 외부창고 분리(엔진) + v1.6 기능 복원
복원: 단품코드 검색(앞 10자리) · 🚫 제외 스타일 탭 · 📊 채널 별 세부 탭(외부창고 컬럼은 여기만)
      · 체크박스 단품 선택 승인 · 사용자 정의 기준 명칭
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
        'desc': '상단 슬라이더로 직접 조정',
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
        mode = '자동회전' if d['ship_rate'] >= params['ship_rate_threshold'] else '제외'
        results.append({'code': code, 'data': d, 'moves': moves,
                        'after': after, 'revenue': rev, 'mode': mode})
    return results


def _apply_exclusion(results):
    """🚫 제외 스타일 적용 — 매칭 단품은 이동 0·모드 '제외' (캐시 비파괴 copy)"""
    excluded = st.session_state.get('excluded_codes', set())
    if not excluded:
        return results
    out = []
    for r in results:
        if any(ex and ex in r['code'] for ex in excluded):
            r2 = dict(r)
            r2['mode'] = '제외'
            r2['moves'] = {k: 0 for k in r['moves']}
            r2['after'] = calc_after_woc(r['data'], r2['moves'], CHANNELS)
            r2['revenue'] = 0
            out.append(r2)
        else:
            out.append(r)
    return out


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


def render_scenario(scenario_key, container, allow_slider=False):
    preset = SCENARIOS[scenario_key]

    if allow_slider:
        container.markdown('### 🎛️ 사용자 정의 기준')
        sl1, sl2, sl3, sl4 = container.columns(4)
        with sl1:
            shortage_th = st.slider('재배치 대상 (재고주수 0주 이하)', 0.5, 4.0, preset['shortage_th'], 0.5, key=f'sh_{scenario_key}')
        with sl2:
            target_woc = st.slider('목표 재고주수 (주)', 1.0, 6.0, preset['target_woc'], 0.5, key=f'tg_{scenario_key}')
        with sl3:
            ship_th = st.slider('현 출고율 (%)', 50, 100, int(preset['ship_th']*100), 5, key=f'sp_{scenario_key}') / 100
        with sl4:
            min_move = st.slider('이동 ≥ N장만 (비부가 제거)', 0, 50, preset['min_move'], 1, key=f'mn_{scenario_key}')
    else:
        shortage_th = preset['shortage_th']
        target_woc = preset['target_woc']
        ship_th = preset['ship_th']
        min_move = preset['min_move']

    container.markdown(f'<div class="scenario-box">{preset["desc"]}</div>', unsafe_allow_html=True)

    with st.spinner('계산 중...'):
        params_key = (shortage_th, target_woc, ship_th, min_move)
        results = calc_results_v20(params_key)
    results = _apply_exclusion(results)

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

    col_f1, col_f2, col_fs, col_f3, col_f4 = container.columns([1.4, 1.6, 3, 1.8, 1.6])
    with col_f1:
        show_only_moved = st.checkbox('이동 발생만', value=True, key=f'moved_{scenario_key}')
    with col_f2:
        mode_filter = st.multiselect('모드', ['자동회전', '제외'], default=['자동회전'], key=f'mode_{scenario_key}')
    with col_fs:
        search_code = st.text_input(
            '단품코드 검색',
            placeholder='앞 10자리만 입력해도 OK (예: SPPPG25U05)',
            key=f'search_{scenario_key}',
        ).strip().upper()
    with col_f3:
        sort_by = st.selectbox('정렬', ['온라인 매출 순위 ↑', '기대효과 ↓', '이동수량 ↓', '단품코드'], key=f'sort_{scenario_key}')
    with col_f4:
        show_only_reorder = st.checkbox('리오더 병합만', value=False, key=f'reorder_{scenario_key}')

    filtered = [r for r in results if r['mode'] in mode_filter]
    if show_only_moved and not search_code:
        filtered = [r for r in filtered if any(v != 0 for v in r['moves'].values())]
    if show_only_reorder:
        filtered = [r for r in filtered if r['data'].get('reorder_codes')]
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

    MAX_ROWS = 1000
    if len(filtered) > MAX_ROWS:
        container.caption(f'⚠️ {len(filtered):,}건 中 상위 {MAX_ROWS}개만 표시 (성능). 정렬·필터로 좁히세요.')
        filtered = filtered[:MAX_ROWS]

    rows = []
    for r in filtered:
        d = r['data']; mv = r['moves']; af = r['after']; inv = d['inv']
        name = d['name']
        if len(name) > 14: name = name[:13] + '…'
        n_reo = len(d.get('reorder_codes', []))
        row = [d.get('rank_online', '-'), r['code'], name,
               f'+{n_reo}' if n_reo else '', f"{int(d['ship_rate']*100)}%", r['mode']]
        for c in CHANNELS:
            o = d['orders'].get(c, 0)
            w = inv.get(c, 0) / o if o > 0 else None
            row.append(f'{round(w)}주' if w is not None else '')
        for c in CHANNELS:
            v = mv.get(c, 0)
            row.append('0' if v == 0 else f'{v:+d}')
        for c in CHANNELS:
            w = af.get(c)
            row.append(f'{round(w)}주' if w is not None else '')
        row.append(round(r['revenue'] / 10000))
        rows.append(row)

    sel_count = 0
    if rows:
        columns = pd.MultiIndex.from_tuples(
            [('', '온라인순위'), ('', '단품코드'), ('', '단품명'), ('', '리오더'), ('', '출고율'), ('', '모드')] +
            [('현 재고보유주수', CH_SHORT[c]) for c in CHANNELS] +
            [('이동수량 (장)', CH_SHORT[c]) for c in CHANNELS] +
            [('이동 후 재고보유주수', CH_SHORT[c]) for c in CHANNELS] +
            [('효과', '만원')]
        )
        df = pd.DataFrame(rows, columns=columns)

        woc_cols = [('현 재고보유주수', CH_SHORT[c]) for c in CHANNELS] + \
                   [('이동 후 재고보유주수', CH_SHORT[c]) for c in CHANNELS]
        mv_cols = [('이동수량 (장)', CH_SHORT[c]) for c in CHANNELS]

        styled = df.style.map(woc_color, subset=woc_cols).map(mv_color, subset=mv_cols)
        styled = styled.format({('효과', '만원'): '{:,}'.format})

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

    container.caption(
        '🎨 **재고보유주수**: 🔴 < 2주   🟡 2~4주   🟢 ≥ 4주    |    '
        '**이동수량**: 🟢 +IN  🔴 -OUT  ⚪ 0    |    '
        '**리오더**: +N = 리오더코드 N건 병합 (기존코드 기준 노출)    |    '
        '단위: 재고/이동후 = "주" · 이동 = "장(±)" · 효과 = "만원"    |    '
        '※ 이동수량 산정 시 외부창고(AENS·ADU3·ADQS) 보관분 제외 — 재고주수는 포함 (상세: 채널 별 세부 탭)'
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


def render_excluded_tab():
    st.markdown('### 🚫 자동 재배치 제외 스타일')
    st.caption('예약판매·기획전·채널단독 스타일 등 자동 이동에서 제외할 단품코드를 입력하세요. '
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
        codes_set = set()
        for line in excluded_text.replace(',', '\n').split('\n'):
            code = line.strip()
            if code:
                codes_set.add(code)
        st.session_state['excluded_codes'] = codes_set
        st.session_state['excluded_text'] = excluded_text

    with col_stat:
        st.metric('제외 패턴 수', f'{len(codes_set):,}')
        try:
            skus = load_data_v20()
            matched = sum(1 for code in skus if any(ex in code for ex in codes_set))
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


def render_channel_tab():
    st.markdown('### 📊 채널 담당자용 상세 데이터')

    channel_pick = st.radio('채널 선택', CHANNELS, horizontal=True, key='ch_pick')

    preset = SCENARIOS['🛡️ 방어형 (추천)']
    params_key = (preset['shortage_th'], preset['target_woc'], preset['ship_th'], preset['min_move'])
    results_ch = _apply_exclusion(calc_results_v20(params_key))

    is_ext = channel_pick in EXT_WAREHOUSE
    wh_label = f"{EXT_WAREHOUSE[channel_pick][0]}({EXT_WAREHOUSE[channel_pick][1]})" if is_ext else None

    ch_total_inv = sum(r['data']['inv'].get(channel_pick, 0) for r in results_ch)
    ch_total_ord = sum(r['data']['orders'].get(channel_pick, 0) for r in results_ch)
    ch_skus_w_ord = sum(1 for r in results_ch if r['data']['orders'].get(channel_pick, 0) > 0)
    ch_in = sum(max(0, r['moves'].get(channel_pick, 0)) for r in results_ch)
    ch_out = sum(min(0, r['moves'].get(channel_pick, 0)) for r in results_ch)
    ch_shortage = sum(1 for r in results_ch
                      if r['data']['orders'].get(channel_pick, 0) > 0
                      and r['data']['inv'].get(channel_pick, 0) / max(1, r['data']['orders'].get(channel_pick, 1)) < 1)
    ch_ext_wh = sum(r['data'].get('ext_wh', {}).get(channel_pick, 0) for r in results_ch) if is_ext else 0

    cols = st.columns(7 if is_ext else 6)
    cols[0].metric('총 재고', f'{ch_total_inv:,}장')
    cols[1].metric('주간 주문', f'{ch_total_ord:,}장')
    cols[2].metric('운영 SKU', f'{ch_skus_w_ord:,}건')
    cols[3].metric('결품 SKU', f'{ch_shortage:,}건', f'{ch_shortage/max(1,ch_skus_w_ord)*100:.1f}%')
    cols[4].metric('금주 IN', f'{ch_in:,}장')
    cols[5].metric('금주 OUT', f'{abs(ch_out):,}장')
    if is_ext:
        cols[6].metric(f'외부창고 재고', f'{ch_ext_wh:,}장', wh_label, delta_color='off')

    st.markdown(f'#### {channel_pick} 단품 상세')
    if is_ext:
        st.caption(f'🏭 외부창고: **{wh_label}** — 외부창고 보관분은 채널 재고·재고주수에 포함되나, 타 채널 이동(OUT) 산정에서는 제외됩니다.')

    cf1, cf2, cf3, cf4 = st.columns([2, 2, 3, 2])
    with cf1:
        only_ord = st.checkbox('주문 발생 단품만', value=True, key='ch_only_ord')
    with cf2:
        only_moved = st.checkbox('이동 발생 단품만', value=False, key='ch_only_moved')
    with cf3:
        ch_search = st.text_input('단품코드 검색', placeholder='앞 10자리만 입력해도 OK', key='ch_search').strip().upper()
    with cf4:
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
        if ch_search and not r['code'].upper().startswith(ch_search):
            continue
        woc = i / o if o > 0 else None
        row = {
            '단품코드': r['code'],
            '단품명': (r['data']['name'][:18] + '…') if len(r['data']['name']) > 18 else r['data']['name'],
            '온라인순위': r['data'].get('rank_online', 9999),
            '정상가': r['data'].get('price', 0),
            '재고(장)': i,
        }
        if is_ext:
            row['외부창고 재고량(장)'] = r['data'].get('ext_wh', {}).get(channel_pick, 0)
        row.update({
            '주문(장/주)': o,
            '재고주수': round(woc, 1) if woc is not None else None,
            '결품여부': '🔴' if (woc is not None and woc < 1) else '🟡' if (woc is not None and woc < 2) else '🟢' if woc is not None else '',
            '추천이동(장)': mv,
            '이동후재고': i + mv,
        })
        ch_rows.append(row)

    if ch_sort == '주문 ↓':
        ch_rows.sort(key=lambda x: -x['주문(장/주)'])
    elif ch_sort == '재고주수 ↑ (결품순)':
        ch_rows.sort(key=lambda x: x['재고주수'] if x['재고주수'] is not None else 999)
    elif ch_sort == '이동량 ↓':
        ch_rows.sort(key=lambda x: -abs(x['추천이동(장)']))
    else:
        ch_rows.sort(key=lambda x: x['온라인순위'])

    if len(ch_rows) > 500:
        st.caption(f'⚠️ {len(ch_rows):,}건 中 상위 500건 표시')
        ch_rows = ch_rows[:500]

    if ch_rows:
        df_ch = pd.DataFrame(ch_rows)
        st.dataframe(df_ch, use_container_width=True, height=500, hide_index=True)
    else:
        st.info('표시할 단품이 없습니다.')

    st.caption('🎨 결품여부: 🔴 1주 미만 (긴급)  🟡 1~2주  🟢 2주 이상')


def render():
    st.markdown('<div class="title-bar">REBA_재고재배치 Agent — 운영 대시보드<span class="ver-badge">v2.1</span></div>', unsafe_allow_html=True)
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
        st.caption('v2.1')

    tab_d, tab_a, tab_c, tab_x, tab_ch = st.tabs(
        list(SCENARIOS.keys()) + ['🚫 제외 스타일', '📊 채널 별 세부']
    )

    with tab_d:
        render_scenario('🛡️ 방어형 (추천)', st, allow_slider=False)

    with tab_a:
        render_scenario('⚡ 공격형', st, allow_slider=False)

    with tab_c:
        render_scenario('🎛️ 사용자 정의', st, allow_slider=True)

    with tab_x:
        render_excluded_tab()

    with tab_ch:
        render_channel_tab()

    st.caption('© 2026 Fashion BG · CAIO실 AX 혁신팀 · 강훈구  |  v2.1 — 자동분배 제거 · 리오더 병합 · 외부창고 분리(엔진) · 검색/제외 스타일/채널 별 세부/선택 승인')
