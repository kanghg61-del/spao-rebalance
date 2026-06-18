# -*- coding: utf-8 -*-
"""
v4.4 화면 — 누판율·주판율 데이터바 · 출고율 기준 완전 제거(슬라이더 삭제) · 재고/주문 RAW 정합 · 리오더 병합(컬러 동일) · 외부창고 분리
복원: 단품코드 검색(앞 10자리) · 🚫 제외 스타일 탭 · 📊 채널 별 세부 탭(외부창고 컬럼은 여기만)
      · 체크박스 단품 선택 승인 · 사용자 정의 기준 명칭
(페이지 설정·비밀번호 게이트·공통 CSS는 app.py 담당)
"""
import streamlit as st
import pandas as pd

from rebalance_engine import calc_rebalance_group, calc_after_woc, calc_expected_revenue, calc_distribution
import effect_log
from mock_data import (
    get_combined_data, get_last_update_time, get_reorder_info,
    get_reorder_mapping, parse_reorder_bytes, save_reorder_mapping,
    CHANNELS, EXT_WAREHOUSE,
)

CH_SHORT = {
    '공홈': '공홈', '이랜드몰': '이몰', '무신사': '무신',
    '지그재그': '지재', '네이버': '네이', '카카오선물하기': '카카오',
}
EXT_CHANNELS = [c for c in CHANNELS if c in EXT_WAREHOUSE]  # 무신사·지그재그·네이버

SCENARIOS = {
    '🛡️ 기본': {
        'desc': '결품 기준 1주 미만 → 목표 2주 확보. 회전(온라인 6채널 잉여→결품)으로 보충. 이동 상한: 각 채널 현재고의 50%',
        'shortage_th': 1.0, 'target_woc': 2.0,
        'ship_th': 0.90, 'min_move': 0, 'min_recv': 0, 'move_cap_pct': 0.50,
    },
    '🎛️ 사용자 정의': {
        'desc': '상단 슬라이더로 직접 조정 (이동 상한 % 포함)',
        'shortage_th': 1.0, 'target_woc': 2.0,
        'ship_th': 0.90, 'min_move': 0, 'min_recv': 0, 'move_cap_pct': 0.50,
    },
}


@st.cache_data(show_spinner=False)
def load_data_v20():
    return get_combined_data('v2')


@st.cache_data(show_spinner=False)
def calc_results_v20(params_key):
    skus = load_data_v20()
    ch_excl = {}
    if len(params_key) > 5 and params_key[5]:
        for ch, direction, pats in params_key[5]:
            ch_excl.setdefault(ch, {})[direction] = set(pats)
    params = {
        'shortage_threshold': params_key[0], 'target_woc': params_key[1],
        'ship_rate_threshold': params_key[2], 'min_move_qty': params_key[3],
        'min_recv_order': params_key[4], 'ch_excl': ch_excl,
        'move_cap_pct': params_key[6] if len(params_key) > 6 else 0.5,
    }
    # 컬러(단품코드 12자리) 단위로 묶어 그룹 재배치 — 아소트 깨짐 방지
    from collections import defaultdict
    groups = defaultdict(dict)
    for code, d in skus.items():
        groups[code[:12]][code] = d
    move_map = {}
    for color, g in groups.items():
        move_map.update(calc_rebalance_group(g, params, CHANNELS))
    results = []
    for code, d in skus.items():
        moves = move_map.get(code, {c: 0 for c in CHANNELS})
        after = calc_after_woc(d, moves, CHANNELS)
        rev = calc_expected_revenue(d, moves, CHANNELS, d['price'])
        mode = '제외' if d.get('locked', False) else '자동회전'
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


def _apply_overrides(results):
    """이동량 직접 수정(세션) 반영 — 해당 단품 moves를 사용자 입력값으로 교체하고 after/효과 재계산."""
    ov = st.session_state.get('move_overrides', {})
    if not ov:
        return results
    out = []
    for r in results:
        o = ov.get(r['code'])
        if o:
            r2 = dict(r)
            moves = {c: int(o.get(c, 0)) for c in CHANNELS}
            r2['moves'] = moves
            r2['after'] = calc_after_woc(r['data'], moves, CHANNELS)
            r2['revenue'] = calc_expected_revenue(r['data'], moves, CHANNELS, r['data']['price'])
            out.append(r2)
        else:
            out.append(r)
    return out


def _ch_excl_key():
    """채널별 IN/OUT 제외(세션) → 캐시 키용 해시가능 튜플."""
    st_ex = st.session_state.get('ch_excl', {})
    return tuple(sorted(
        (ch, dr, tuple(sorted(st_ex.get(ch, {}).get(dr, []))))
        for ch in CHANNELS for dr in ('in', 'out')
        if st_ex.get(ch, {}).get(dr)
    ))


def woc_color(w):
    if w is None or w == '' or pd.isna(w): return ''
    try:
        v = float(str(w).replace('주', ''))
    except: return ''
    if v < 1: return 'background-color: #5B1E1E; color: #FF5A5F; font-weight:bold'   # 빨강: 1주 미만
    if v < 4: return 'background-color: #5A4500; color: #FFC000; font-weight:bold'   # 노랑: 1~4주
    return 'background-color: #1B4D3E; color: #4AE3B5; font-weight:bold'            # 초록: 4주 이상


def mv_color(v):
    if v is None or v == 0 or pd.isna(v) or v == '': return ''
    try:
        vv = int(str(v).replace('+', ''))
    except: return ''
    if vv > 0: return 'background-color: #1B4D3E; color: #4AE3B5; font-weight:bold; text-align:center'
    return 'background-color: #5B1E1E; color: #FF5A5F; font-weight:bold; text-align:center'


def qty_color(s):
    """이동 후 재고량 셀: 증가(+)=녹색음영 / 감소(-)=레드음영, 글자 흰색, 우측정렬."""
    if not isinstance(s, str) or s == '':
        return 'text-align:right'
    if '(+' in s:
        return 'background-color: #1B4D3E; color: #FFFFFF; font-weight:bold; text-align:right'
    if '(-' in s:
        return 'background-color: #5B1E1E; color: #FFFFFF; font-weight:bold; text-align:right'
    return 'color: #FFFFFF; text-align:right'



@st.dialog('✅ 재고 이동 전송 확인')
def _approve_dialog(scenario_key, sel_count, sel_qty, sel_amt, sel_rev, ch_in, ch_out, exec_id):
    st.markdown(f"""<div class="scenario-box">
    <b>SAP BAPI 전송 완료 (mock)</b> — 실행 ID <b>#{exec_id}</b> · 📈 실행 효과 탭에 이력 기록됨<br>
    실 배포 시: BAPI_GOODS_MVT_CREATE 호출 → 전표 생성 → audit log</div>""", unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric('승인 단품', f'{sel_count:,}건')
    m2.metric('총 이동량', f'{sel_qty:,}장')
    m3.metric('총 이동 금액', f'{sel_amt/100000000:.2f}억')
    m4.metric('기대 회수 매출', f'{sel_rev/100000000:.2f}억')
    rows = [{'채널': c, 'IN (장)': ch_in.get(c, 0), 'OUT (장)': ch_out.get(c, 0),
             '순증감': ch_in.get(c, 0) - ch_out.get(c, 0)} for c in CHANNELS
            if ch_in.get(c, 0) or ch_out.get(c, 0)]
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                     height=min(38 + 35 * len(rows), 260))
    st.caption('⚠️ 실제 재고 이동 여부는 익일 06:00 재고 갱신 후 "현 재고보유주수" 변화 및 📈 실행 효과 탭 실측으로 확인하세요.')
    if st.button('확인', type='primary', use_container_width=True, key=f'dlg_ok_{scenario_key}'):
        st.rerun()


def _chan_recovery_bar(items):
    """회수매출 채널 구성 — KPI 카드에 들어가는 100% 가로 스택 막대 + 상위 채널 범례."""
    rev = {c: 0 for c in CHANNELS}
    for r in items:
        d = r['data']
        for c in CHANNELS:
            o = d['orders'].get(c, 0); i = d['inv'].get(c, 0); mvc = r['moves'].get(c, 0)
            rev[c] += (max(0, o - i) - max(0, o - (i + mvc))) * d['price']
    tot = sum(rev.values()) or 1
    pal = {'공홈': '#4AE3B5', '네이버': '#8AB4F8', '무신사': '#2FB7A4',
           '지그재그': '#FFC000', '이랜드몰': '#9B8CFF', '카카오선물하기': '#FF8FA3'}
    order = [c for c in sorted(CHANNELS, key=lambda x: -rev[x]) if rev[c] > 0]
    seg = ''.join(
        f'<span title="{CH_SHORT[c]} {rev[c]/1e8:.2f}억 ({rev[c]/tot*100:.0f}%)" '
        f'style="width:{rev[c]/tot*100:.2f}%;background:{pal[c]};height:12px;display:inline-block"></span>'
        for c in order)
    leg = '  '.join(
        f'<span style="color:{pal[c]};font-size:11px">●</span>'
        f'<span style="color:#FFFFFF;font-size:10px"> {CH_SHORT[c]} {rev[c]/1e8:.2f}억</span>'
        for c in order[:4])
    return (f'<div style="display:flex;width:100%;border-radius:3px;overflow:hidden;margin:6px 0 4px">{seg}</div>'
            f'<div style="line-height:1.3">{leg}</div>')


def render_scenario(scenario_key, container, allow_slider=False):
    preset = SCENARIOS[scenario_key]

    ship_th = 0.0
    if allow_slider:
        container.markdown('### 🎛️ 사용자 정의 기준')
        sl1, sl2, sl3, sl4, sl5 = container.columns(5)
        with sl1:
            shortage_th = st.slider('재배치 대상 (재고주수 0주 이하)', 0.5, 4.0, preset['shortage_th'], 0.5, key=f'sh_{scenario_key}')
        with sl2:
            target_woc = st.slider('목표 재고주수 (주)', 1.0, 6.0, preset['target_woc'], 0.5, key=f'tg_{scenario_key}')
        with sl3:
            min_move = st.slider('이동 ≥ N장만 (비부가 제거)', 0, 50, preset['min_move'], 1, key=f'mn_{scenario_key}')
        with sl4:
            min_recv = st.slider('소액 채널 제외 (주간주문 N장 미만)', 0, 20, preset.get('min_recv', 4), 1, key=f'mr_{scenario_key}')
        with sl5:
            move_cap_pct = st.slider('채널별 이동 상한 (현재고 %)', 0, 100, int(round(preset.get('move_cap_pct', 0.5) * 100)), 5, key=f'cap_{scenario_key}') / 100.0
    else:
        shortage_th = preset['shortage_th']
        target_woc = preset['target_woc']
        min_move = preset['min_move']
        min_recv = preset.get('min_recv', 4)
        move_cap_pct = preset.get('move_cap_pct', 0.5)

    container.markdown(f'<div class="scenario-box">{preset["desc"]}</div>', unsafe_allow_html=True)

    with st.spinner('계산 중...'):
        params_key = (shortage_th, target_woc, ship_th, min_move, min_recv, _ch_excl_key(), move_cap_pct)
        results = calc_results_v20(params_key)
    results = _apply_exclusion(results)
    results = _apply_overrides(results)

    total_units = sum(sum(r['data']['inv'].get(c, 0) for c in CHANNELS) for r in results)
    total_units_amt = sum(sum(r['data']['inv'].get(c, 0) for c in CHANNELS) * r['data']['price'] for r in results)
    total_in = sum(sum(v for v in r['moves'].values() if v > 0) for r in results)
    total_amt = sum(sum(v for v in r['moves'].values() if v > 0) * r['data']['price'] for r in results)
    total_rev = sum(r['revenue'] for r in results)

    def kpi_card(col, label, value, sub=''):
        col.markdown(f"""<div class="kpi-card" style="min-height:120px;display:flex;flex-direction:column;justify-content:center">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>""", unsafe_allow_html=True)

    kpi_ph = container.container()

    col_f1, col_fs, col_f3 = container.columns([1.6, 4, 2])
    with col_f1:
        show_only_moved = st.checkbox('이동 발생만', value=True, key=f'moved_{scenario_key}')
    with col_fs:
        search_code = st.text_input('단품코드 검색', placeholder='앞 10자리만 입력해도 OK (예: SPPPG25U05)', key=f'search_{scenario_key}').strip().upper()
    with col_f3:
        sort_by = st.selectbox('정렬', ['온라인 매출 순위 ↑', '기대효과 ↓', '이동수량 ↓', '단품코드'], key=f'sort_{scenario_key}')

    filtered = list(results)
    if show_only_moved and not search_code:
        filtered = [r for r in filtered if any(v != 0 for v in r['moves'].values())]
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

    MAX_ROWS = 2000
    if len(filtered) > MAX_ROWS:
        container.caption(f'⚠️ {len(filtered):,}건 中 상위 {MAX_ROWS}개만 표시 (성능). 정렬·필터로 좁히세요.')
        filtered = filtered[:MAX_ROWS]

    _sel_state = st.session_state.get(f'mat_{scenario_key}')
    _pre_rows = []
    try:
        _pre_rows = [i for i in _sel_state.selection.rows if i < len(filtered)]
    except Exception:
        _pre_rows = []
    if _pre_rows:
        _base = [filtered[i] for i in _pre_rows]
        _units = sum(sum(r['data']['inv'].get(c, 0) for c in CHANNELS) for r in _base)
        _units_amt = sum(sum(r['data']['inv'].get(c, 0) for c in CHANNELS) * r['data']['price'] for r in _base)
        _in = sum(sum(v for v in r['moves'].values() if v > 0) for r in _base)
        _amt = sum(sum(v for v in r['moves'].values() if v > 0) * r['data']['price'] for r in _base)
        _rev = sum(r['revenue'] for r in _base)
        _sub = f'☑ 선택 {len(_base):,}건 기준'
        _chart_items = _base
    else:
        _units, _units_amt, _in, _amt, _rev, _sub = total_units, total_units_amt, total_in, total_amt, total_rev, '전체 기준'
        _chart_items = filtered
    with kpi_ph:
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        kpi_card(k1, '총 단품량', f'{_units:,}장', f'6채널 재고 합계 · {_sub}')
        kpi_card(k2, '총 이동량(회전)', f'{_in:,}장', f'주간 IN · {_sub}')
        kpi_card(k3, '총 재고금액', f'{_units_amt/100000000:.1f}억', '재고수량 × 정상가')
        kpi_card(k4, '총 이동 금액', f'{_amt/100000000:.2f}억', '이동수량 × 정상가')
        k5.markdown(
            f'<div class="kpi-card" style="min-height:120px"><div class="kpi-label">회수 매출 · 채널 구성</div>'
            f'<div class="kpi-value">{_rev/100000000:.2f}억</div>'
            f'{_chan_recovery_bar(_chart_items)}</div>', unsafe_allow_html=True)
        kpi_card(k6, '연 환산', f'{_rev*52/100000000:.0f}억', '× 52주')

    rows = []
    for r in filtered:
        d = r['data']; mv = r['moves']; af = r['after']; inv = d['inv']
        name = d['name']
        cum = d.get('cum_rate', 0) * 100; wk = d.get('wk_rate', 0) * 100
        sv = d.get('wk_sales', 0)
        sales_str = f"{round(sv/10000):,}만" if sv else '-'
        row = [r['code'], name, sales_str, f"{cum:.0f}%", f"{wk:.0f}%", f"{int(d['ship_rate']*100)}%",
               f"{inv.get('반응과', 0):,}"]
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
        for c in CHANNELS:
            v = mv.get(c, 0); ni = inv.get(c, 0) + v
            row.append(f'{ni:,}' if v == 0 else f'{ni:,} ({v:+d})')
        row.append(round(r['revenue'] / 10000))
        rows.append(row)

    sel_count = 0
    selected_rows = []
    if rows:
        columns = pd.MultiIndex.from_tuples(
            [('', '단품코드'), ('', '단품명'), ('', '주간외형매출'), ('', '누판'), ('', '주판'), ('', '출고'), ('', '반응과재고')] +
            [('현 재고보유주수', CH_SHORT[c]) for c in CHANNELS] +
            [('이동수량 (장)', CH_SHORT[c]) for c in CHANNELS] +
            [('이동 후 재고보유주수', CH_SHORT[c]) for c in CHANNELS] +
            [('이동 후 재고량 (장,±)', CH_SHORT[c]) for c in CHANNELS] +
            [('효과', '만원')]
        )
        df = pd.DataFrame(rows, columns=columns)

        woc_cols = [('현 재고보유주수', CH_SHORT[c]) for c in CHANNELS] + \
                   [('이동 후 재고보유주수', CH_SHORT[c]) for c in CHANNELS]
        mv_cols = [('이동수량 (장)', CH_SHORT[c]) for c in CHANNELS]
        qty_cols = [('이동 후 재고량 (장,±)', CH_SHORT[c]) for c in CHANNELS]

        styled = (df.style
                  .map(woc_color, subset=woc_cols)
                  .map(mv_color, subset=mv_cols)
                  .map(qty_color, subset=qty_cols))
        styled = styled.format({('효과', '만원'): '{:,}'.format})

        container.caption('💡 좌측 ☑ 박스(행) 클릭 → 단품 선택 · 헤더 클릭으로 전체 선택')
        event = container.dataframe(
            styled, use_container_width=True, height=620, hide_index=True,
            on_select='rerun', selection_mode='multi-row', key=f'mat_{scenario_key}')
        selected_rows = event.selection.rows if (event and event.selection) else []
        sel_count = len(selected_rows) if selected_rows else len(df)
        if not selected_rows:
            container.caption(f'✅ 미선택 시 전체 {len(df):,}건 실행 대상')
        else:
            container.caption(f'✅ 선택: **{sel_count:,}건** / 전체 {len(df):,}건  ·  선택분만 승인 대상')
    else:
        container.info('필터 조건에 맞는 단품이 없습니다.')

    container.caption(
        '🎨 재고보유주수: 🔴 < 1주  🟡 1~4주  🟢 ≥ 4주   |   🔁 회전 = 온라인 6채널 간 이동(합계 0)   |   '
        '효과 = 결품해소 회수매출(만원)   |   ※ 이동수량은 외부창고(AENS·ADU3·ADQS) 보관분 제외'
    )

    sel_items = []
    if rows:
        sel_items = [filtered[i] for i in selected_rows] if selected_rows else list(filtered)
    sel_qty = sum(sum(v for v in it['moves'].values() if v > 0) for it in sel_items)
    sel_rev = sum(it['revenue'] for it in sel_items)

    col_b1, col_b2, col_b3 = container.columns([2, 2, 4])
    with col_b1:
        if st.button(f'✅ 선택 {sel_count}건 승인(회전)', use_container_width=True, type='primary', key=f'approve_{scenario_key}'):
            details = []
            ch_in, ch_out = {}, {}
            sel_amt = 0
            for it in sel_items:
                for ch, v in it['moves'].items():
                    if v > 0:
                        details.append((it['code'], ch, it['data']['inv'].get(ch, 0), v, it['data']['price']))
                        ch_in[ch] = ch_in.get(ch, 0) + v
                        sel_amt += v * it['data']['price']
                    elif v < 0:
                        ch_out[ch] = ch_out.get(ch, 0) - v
            exec_id = effect_log.log_execution(scenario_key, len(sel_items), sel_qty, sel_rev, details=details)
            _approve_dialog(scenario_key, sel_count, sel_qty, sel_amt, sel_rev, ch_in, ch_out, exec_id)
    with col_b2:
        if st.button('✋ Override 화면', use_container_width=True, key=f'override_{scenario_key}'):
            st.info('실 배포 시 단품별 수정 다이얼로그 (현재 PoC mock)')
    with col_b3:
        container.caption('실 배포: 승인 → SAP BAPI 자동 호출 → audit log 기록')


def render_excluded_tab():
    st.markdown('### 🚫 채널별 IN·OUT 제외 관리 (채널 담당 MD)')
    st.caption('채널 MD가 자동 재배치에서 제외할 스타일을 채널별로 직접 관리합니다.  '
               '**🟢 IN 제외** = 이 채널로 재고를 받지 않음(수신 차단)  ·  **🔴 OUT 제외** = 이 채널에서 재고를 빼지 않음(반출 차단).  '
               '코드 일부만 입력해도 매칭(예: `SPACG24`).  입력 후 다른 탭으로 이동하면 재배치에 반영됩니다.')

    try:
        skus = load_data_v20()
    except Exception:
        skus = None

    ch_excl = st.session_state.get('ch_excl', {})
    tabs = st.tabs([str(c) for c in CHANNELS])
    for tab, c in zip(tabs, CHANNELS):
        with tab:
            ca, cb = st.columns(2)
            with ca:
                in_txt = st.text_area('🟢 IN 제외 (이 채널로 받지 않을 스타일)',
                                      value=st.session_state.get(f'excl_in_{c}', ''), height=170,
                                      placeholder='예:\nSPACG24A5\nSPJJG25G01', key=f'ta_in_{c}')
            with cb:
                out_txt = st.text_area('🔴 OUT 제외 (이 채널에서 빼지 않을 스타일)',
                                       value=st.session_state.get(f'excl_out_{c}', ''), height=170,
                                       placeholder='예:\nSPACG24A5', key=f'ta_out_{c}')
            in_set = {x.strip() for x in in_txt.replace(',', '\n').split('\n') if x.strip()}
            out_set = {x.strip() for x in out_txt.replace(',', '\n').split('\n') if x.strip()}
            st.session_state[f'excl_in_{c}'] = in_txt
            st.session_state[f'excl_out_{c}'] = out_txt
            ch_excl.setdefault(c, {})['in'] = in_set
            ch_excl[c]['out'] = out_set
            m_in = sum(1 for code in skus if any(p in code for p in in_set)) if (skus and in_set) else 0
            m_out = sum(1 for code in skus if any(p in code for p in out_set)) if (skus and out_set) else 0
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric('IN 제외 패턴', f'{len(in_set):,}')
            mc2.metric('OUT 제외 패턴', f'{len(out_set):,}')
            mc3.metric('매칭 단품 (IN / OUT)', f'{m_in:,} / {m_out:,}')
            if st.button('🗑️ 이 채널 제외 초기화', key=f'clr_{c}'):
                st.session_state[f'excl_in_{c}'] = ''
                st.session_state[f'excl_out_{c}'] = ''
                ch_excl[c] = {'in': set(), 'out': set()}
                st.rerun()
    st.session_state['ch_excl'] = ch_excl

    st.markdown('---')
    with st.expander('🚫 전체 이동 제외 (예약판매·기획전 등 — 모든 채널에서 이동 자체를 막음)', expanded=False):
        excluded_text = st.text_area('제외 단품코드 (줄바꿈 또는 쉼표로 구분)',
                                     value=st.session_state.get('excluded_text', ''), height=130,
                                     placeholder='예:\nSPJJG25G0119095\nSPACG24A5', key='excluded_text_input')
        codes_set = {x.strip() for x in excluded_text.replace(',', '\n').split('\n') if x.strip()}
        st.session_state['excluded_codes'] = codes_set
        st.session_state['excluded_text'] = excluded_text
        if skus and codes_set:
            st.caption(f'매칭 단품 {sum(1 for code in skus if any(ex in code for ex in codes_set)):,}건')
        if st.button('🗑️ 전체 이동 제외 초기화'):
            st.session_state['excluded_text'] = ''
            st.session_state['excluded_codes'] = set()
            st.rerun()



def render_reorder_tab():
    st.markdown('### 🔁 리오더 매핑 관리')
    st.caption('리오더(코드변경) 발생 시 주 1회~월 1회 갱신. 스타일코드(10자리)·단품코드(15자리) 모두 지원 — '
               '스타일코드 입력 시 사이즈까지 자동 prefix 매칭됩니다. 적용 즉시 전 탭 재계산.')

    info = get_reorder_info()
    pairs = get_reorder_mapping()

    m1, m2, m3 = st.columns(3)
    m1.metric('매핑 행수', f"{info['mapping_rows']:,}")
    m2.metric('병합 적용 단품', f"{info['merged']:,}건")
    m3.metric('적용 파일', info['file'] or '없음')

    st.markdown('---')
    col_up, col_add = st.columns(2)

    with col_up:
        st.markdown('#### 📂 파일 업로드 (전체 교체)')
        up = st.file_uploader('csv 또는 xlsx — 컬럼: 기존코드 / 리오더(추가)코드 자동 인식',
                              type=['csv', 'xlsx'], key='reorder_upload')
        if up is not None:
            try:
                new_pairs = parse_reorder_bytes(up.getvalue(), up.name)
                st.success(f'{up.name} → 유효 매핑 {len(new_pairs):,}행 인식')
                st.dataframe(pd.DataFrame(new_pairs, columns=['기존코드', '리오더코드']).head(10),
                             use_container_width=True, hide_index=True, height=200)
                if st.button(f'✅ 적용 — 기존 매핑을 {len(new_pairs):,}행으로 교체', type='primary',
                             use_container_width=True, key='apply_upload'):
                    save_reorder_mapping(new_pairs)
                    st.cache_data.clear()
                    st.success('적용 완료 — 전 탭 재계산됨')
                    st.rerun()
            except Exception as e:
                st.error(f'파일 해석 실패: {e}')

    with col_add:
        st.markdown('#### ⌨️ 직접 입력 (1건 추가)')
        with st.form('reorder_add_form', clear_on_submit=True):
            org_in = st.text_input('원오더(기존) 코드', placeholder='예: SPJJG23KU2 또는 15자리 단품코드')
            reo_in = st.text_input('리오더(추가) 코드', placeholder='예: SPJJG24KU1')
            ok = st.form_submit_button('➕ 매핑 추가', use_container_width=True, type='primary')
        if ok:
            org_v, reo_v = org_in.strip().upper(), reo_in.strip().upper()
            if not org_v or not reo_v or org_v == reo_v:
                st.error('기존/리오더 코드를 서로 다르게 입력하세요.')
            elif any(r == reo_v for _, r in pairs):
                st.warning(f'{reo_v} 는 이미 매핑에 존재합니다.')
            else:
                save_reorder_mapping(pairs + [(org_v, reo_v)])
                st.cache_data.clear()
                st.success(f'추가 완료: {reo_v} → {org_v}')
                st.rerun()

    st.markdown('---')
    st.markdown(f'#### 현재 매핑 ({len(pairs):,}행)')
    if pairs:
        df_map = pd.DataFrame(pairs, columns=['기존코드', '리오더코드'])
        sc1, sc2 = st.columns([3, 1])
        with sc1:
            q = st.text_input('매핑 검색', placeholder='코드 일부 입력', key='reorder_search').strip().upper()
        if q:
            df_map = df_map[df_map['기존코드'].str.contains(q) | df_map['리오더코드'].str.contains(q)]
        st.dataframe(df_map, use_container_width=True, hide_index=True, height=320)
        with sc2:
            csv_bytes = ('기존코드,리오더코드\n' + '\n'.join(f'{o},{r}' for o, r in pairs)).encode('utf-8-sig')
            st.download_button('⬇️ CSV 다운로드', csv_bytes, 'reorder_mapping.csv', 'text/csv',
                               use_container_width=True)
    else:
        st.info('등록된 매핑이 없습니다. 파일 업로드 또는 직접 입력으로 추가하세요.')

    st.caption('⚠️ 웹에서 적용한 변경은 앱 **재시작·재배포 시 패키지 파일 기준으로 초기화**됩니다. '
               '영구 반영하려면 ⬇️ CSV를 다운로드해 GitHub 레포의 reorder_mapping.csv 로 커밋하거나 Claude에게 전달하세요.')


def _stat_color(s):
    if not isinstance(s, str):
        return ''
    if '긴급' in s:
        return 'background-color:#5B1E1E; color:#FF6B70; font-weight:bold'
    if '주의' in s:
        return 'background-color:#5A4500; color:#FFC000; font-weight:bold'
    if '정상' in s:
        return 'background-color:#1B4D3E; color:#4AE3B5; font-weight:bold'
    return 'color:#9FB0C0'


def _move_color(v):
    try:
        n = int(str(v).replace('+', '').replace(',', ''))
    except Exception:
        return 'text-align:right'
    if n > 0:
        return 'background-color:#1B4D3E; color:#FFFFFF; font-weight:bold; text-align:right'
    if n < 0:
        return 'background-color:#5B1E1E; color:#FFFFFF; font-weight:bold; text-align:right'
    return 'color:#9FB0C0; text-align:right'


def _rate_color(v):
    try:
        x = float(v)
    except Exception:
        return ''
    if x >= 25:
        return 'background-color:#5B1E1E; color:#FF6B70; font-weight:bold'
    if x >= 10:
        return 'background-color:#5A4500; color:#FFC000; font-weight:bold'
    return 'background-color:#1B4D3E; color:#4AE3B5; font-weight:bold'


def _hl_sum(row):
    v0 = str(row.iloc[0])
    is_sum = v0 == '합계' or v0 == '— 합계 —'
    sty = 'background-color:#1E2D40; color:#FFFFFF; font-weight:bold' if is_sum else ''
    return [sty] * len(row)


def _int0(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ''
    if f != f:
        return ''
    return f'{int(round(f))}'


def _woc(v):
    """재고주수 포맷 — 기본탭과 동일: '0주', '1주' 형태."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ''
    if f != f:
        return ''
    return f'{int(round(f))}주'


BOK_LIST = ['A', 'C', 'G', 'K', 'M', 'U', 'W']


def _bok(code):
    return code[7] if len(code) > 7 else '?'


def _item(code):
    return code[2:4] if len(code) > 3 else '?'


def _ch_effect(d, mv_ch, ch):
    o = d['orders'].get(ch, 0); i = d['inv'].get(ch, 0); p = d.get('price', 0)
    return (max(0, o - i) - max(0, o - (i + mv_ch))) * p


def _render_group(results_ch, keyfn, g_inv, g_ord, g_move, g_eff, g_ext, keycol, namefn=False):
    """아이템별/스타일별 집계표 — 단품 상세와 동일 지표를 그룹 합산하여 렌더(맨 위 합계행)."""
    agg = {}
    nm = {}
    for r in results_ch:
        d = r['data']; k = keyfn(r['code']); p = d.get('price', 0)
        o = g_ord(d); i = g_inv(d)
        a = agg.setdefault(k, dict(sku=0, ordd=0, inv=0, invamt=0, salesamt=0, ext=0, mv=0, eff=0, item=0, urg=0))
        a['sku'] += 1; a['ordd'] += o; a['inv'] += i; a['invamt'] += i * p; a['salesamt'] += o * p
        a['ext'] += g_ext(d); a['mv'] += max(0, g_move(r)); a['eff'] += g_eff(r)
        if o > 0:
            a['item'] += 1
            if i / o < 1:
                a['urg'] += 1
        if namefn:
            nm.setdefault(k, d['name'])
    tot_ord = sum(a['ordd'] for a in agg.values()) or 1

    def mk(k, a):
        woc = a['inv'] / a['ordd'] if a['ordd'] > 0 else None
        daily = a['ordd'] / 7
        row = {keycol: k}
        if namefn:
            v = nm.get(k, '')
            row['대표 상품명'] = (v[:18] + '…') if len(v) > 18 else v
        row.update({
            'SKU수': a['sku'], '주간 판매량': a['ordd'], '일평균 판매량': round(daily, 1),
            '일평균 매출(만원)': round(a['salesamt'] / 7 / 10000), '현 재고량': a['inv'],
            '현 재고금액(만원)': round(a['invamt'] / 10000), '외부창고': a['ext'],
            '현 재고주수': round(woc) if woc is not None else None,
            '소진예상(일)': round(a['inv'] / daily) if daily > 0 else None,
            '추천이동(회전)': a['mv'], '효과(만원)': round(a['eff'] / 10000),
            '판매량 비중(%)': round(a['ordd'] / tot_ord * 100, 2),
            '결품률(%)': round(a['urg'] / a['item'] * 100, 1) if a['item'] else 0.0,
        })
        return row

    body = [mk(k, a) for k, a in agg.items() if not (a['inv'] == 0 and a['ordd'] == 0)]
    body.sort(key=lambda x: -x['주간 판매량'])
    if not body:
        st.info('표시할 항목이 없습니다.')
        return
    T = {f: sum(a[f] for a in agg.values()) for f in ('sku', 'ordd', 'inv', 'invamt', 'salesamt', 'ext', 'mv', 'eff', 'item', 'urg')}
    woc = T['inv'] / T['ordd'] if T['ordd'] > 0 else None
    daily = T['ordd'] / 7
    sumrow = {keycol: '합계'}
    if namefn:
        sumrow['대표 상품명'] = f'{len(body):,}개'
    sumrow.update({
        'SKU수': T['sku'], '주간 판매량': T['ordd'], '일평균 판매량': round(daily, 1),
        '일평균 매출(만원)': round(T['salesamt'] / 7 / 10000), '현 재고량': T['inv'],
        '현 재고금액(만원)': round(T['invamt'] / 10000), '외부창고': T['ext'],
        '현 재고주수': round(woc) if woc is not None else None,
        '소진예상(일)': round(T['inv'] / daily) if daily > 0 else None,
        '추천이동(회전)': T['mv'], '효과(만원)': round(T['eff'] / 10000),
        '판매량 비중(%)': 100.0, '결품률(%)': round(T['urg'] / T['item'] * 100, 1) if T['item'] else 0.0,
    })
    df = pd.DataFrame([sumrow] + body)
    styled = (df.style.map(_rate_color, subset=['결품률(%)'])
              .map(woc_color, subset=['현 재고주수'])
              .map(mv_color, subset=['추천이동(회전)'])
              .apply(_hl_sum, axis=1)
              .format({'SKU수': '{:,}'.format, '주간 판매량': '{:,}'.format, '일평균 판매량': '{:.1f}'.format,
                       '일평균 매출(만원)': '{:,}'.format, '현 재고량': '{:,}'.format, '현 재고금액(만원)': '{:,}'.format,
                       '외부창고': '{:,}'.format, '현 재고주수': _woc, '소진예상(일)': _int0,
                       '추천이동(회전)': '{:,}'.format, '효과(만원)': '{:,}'.format,
                       '판매량 비중(%)': '{:.2f}'.format, '결품률(%)': '{:.1f}'.format}))
    st.dataframe(styled, use_container_width=True, height=440, hide_index=True)


def render_channel_tab():
    st.markdown("""
    <style>
    .stTabs div[role="radiogroup"] label:has(input:checked){background:#FFC000 !important; border-color:#FFC000 !important;}
    .stTabs div[role="radiogroup"] label:has(input:checked) p{color:#0A141F !important;}
    .stTabs .stTabs [data-baseweb="tab"][aria-selected="true"]{background:#FFC000 !important; color:#0A141F !important;}
    .stTabs .stTabs [data-baseweb="tab"][aria-selected="true"] p{color:#0A141F !important;}
    </style>
    """, unsafe_allow_html=True)

    picks = ['전체'] + list(CHANNELS)
    channel_pick = st.radio('채널 선택', picks, horizontal=True, key='ch_pick', label_visibility='collapsed')
    is_all = channel_pick == '전체'
    is_ext = (not is_all) and channel_pick in EXT_WAREHOUSE
    wh_label = f'{EXT_WAREHOUSE[channel_pick][0]}({EXT_WAREHOUSE[channel_pick][1]})' if is_ext else None

    preset = SCENARIOS['🛡️ 기본']
    params_key = (preset['shortage_th'], preset['target_woc'], preset['ship_th'],
                  preset['min_move'], preset.get('min_recv', 4), _ch_excl_key())
    results_ch = _apply_exclusion(calc_results_v20(params_key))

    def g_inv(d):
        return sum(d['inv'].get(c, 0) for c in CHANNELS) if is_all else d['inv'].get(channel_pick, 0)

    def g_ord(d):
        return sum(d['orders'].get(c, 0) for c in CHANNELS) if is_all else d['orders'].get(channel_pick, 0)

    def g_move(r):
        if is_all:
            return sum(v for v in r['moves'].values() if v > 0)
        return r['moves'].get(channel_pick, 0)

    def g_ext(d):
        if is_all:
            return sum(d.get('ext_wh', {}).get(c, 0) for c in EXT_WAREHOUSE)
        return d.get('ext_wh', {}).get(channel_pick, 0) if is_ext else 0

    def g_eff(r):
        return r['revenue'] if is_all else _ch_effect(r['data'], r['moves'].get(channel_pick, 0), channel_pick)

    def kcard(col, label, value, sub=''):
        col.markdown(f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
                     f'<div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>',
                     unsafe_allow_html=True)

    sub_overview, sub_item, sub_style, sub_sku = st.tabs(['📋 재고 현황', '🧺 아이템별', '🎨 스타일별', '🔎 단품 상세'])

    # ───────────── 재고 현황 ─────────────
    with sub_overview:
        tot_inv = sum(g_inv(r['data']) for r in results_ch)
        tot_amt = sum(g_inv(r['data']) * r['data'].get('price', 0) for r in results_ch)
        n_item = sum(1 for r in results_ch if g_ord(r['data']) > 0)
        n_urgent = sum(1 for r in results_ch if g_ord(r['data']) > 0 and g_inv(r['data']) / max(1, g_ord(r['data'])) < 1)
        rate = n_urgent / max(1, n_item) * 100
        tot_in = sum(max(0, g_move(r)) for r in results_ch)
        tot_ext = sum(g_ext(r['data']) for r in results_ch)
        ext_pct = tot_ext / max(1, tot_inv) * 100
        union_item = union_urg = 0
        if is_all:
            for r in results_ch:
                d = r['data']
                act = [c for c in CHANNELS if d['orders'].get(c, 0) > 0]
                if act:
                    union_item += 1
                    if any(d['inv'].get(c, 0) / d['orders'][c] < 1 for c in act):
                        union_urg += 1
        union_rate = union_urg / max(1, union_item) * 100

        if is_all:
            c = st.columns(8)
            kcard(c[0], '품목 수', f'{n_item:,}', '주문 발생 SKU')
            kcard(c[1], '총 재고량', f'{tot_inv:,}장', f'재고금액 {tot_amt/1e8:.0f}억')
            kcard(c[2], '긴급 결품', f'{n_urgent:,}건', '재고주수 < 1주')
            kcard(c[3], '결품률(합산)', f'{rate:.1f}%', '6채널 재고 합산')
            kcard(c[4], '결품(채널)', f'{union_rate:.1f}%', '한 채널이라도 결품')
            kcard(c[5], '추천 이동(IN)', f'{tot_in:,}장', '금주 충전')
            kcard(c[6], '외부창고', f'{tot_ext:,}장', 'AENS·ADU3·ADQS')
            kcard(c[7], '외부창고 비중', f'{ext_pct:.1f}%', '외부창고 / 총재고')
            st.caption('ℹ️ 결품률(합산)은 6채널 재고를 합쳐 봐 낮게(7%대) 보입니다(풀링 효과). 운영 체감은 "한 채널이라도 결품"인 결품(채널)을 보세요.')
        else:
            n = 6 if is_ext else 5
            c = st.columns(n)
            kcard(c[0], '품목 수', f'{n_item:,}', '주문 발생 SKU')
            kcard(c[1], '총 재고량', f'{tot_inv:,}장', f'{channel_pick}')
            kcard(c[2], '긴급 결품', f'{n_urgent:,}건', '재고주수 < 1주')
            kcard(c[3], '결품률', f'{rate:.1f}%', f'{n_urgent:,}/{n_item:,}')
            kcard(c[4], '추천 이동(IN)', f'{tot_in:,}장', '금주 충전')
            if is_ext:
                kcard(c[5], '외부창고', f'{tot_ext:,}장', f'{wh_label} · 비중 {ext_pct:.1f}%')
            st.caption(f'ℹ️ {channel_pick} 결품률 {rate:.1f}% — 마이너 채널은 운영 SKU·SKU당 재고가 적어 구조적으로 높습니다(데이터 오류 아님).')

        bstat = {b: [0, 0] for b in BOK_LIST}
        for r in results_ch:
            b = _bok(r['code'])
            if b in bstat:
                o = g_ord(r['data']); i = g_inv(r['data'])
                if o > 0:
                    bstat[b][0] += 1
                    if i / o < 1:
                        bstat[b][1] += 1
        st.markdown('##### 🧬 복종별 결품률')
        bc = st.columns(len(BOK_LIST))
        for j, b in enumerate(BOK_LIST):
            item, urg = bstat[b]
            br = urg / item * 100 if item else 0
            clr = '#FF6B70' if br >= 25 else '#FFC000' if br >= 10 else '#4AE3B5'
            bc[j].markdown(
                f'<div class="kpi-card"><div class="kpi-label">복종 {b}</div>'
                f'<div class="kpi-value" style="color:{clr}">{br:.1f}%</div>'
                f'<div class="kpi-sub">{urg:,}/{item:,}</div></div>', unsafe_allow_html=True)
        urgent_loss = 0
        for r in results_ch:
            d = r['data']; o = g_ord(d); i = g_inv(d)
            if o > 0 and i / o < 1:
                urgent_loss += (o - i) * d.get('price', 0)
        bw_total = sum(r['data']['inv'].get('반응과', 0) for r in results_ch)
        wb = max(BOK_LIST, key=lambda b: (bstat[b][1] / bstat[b][0]) if bstat[b][0] else 0)
        wb_rate = (bstat[wb][1] / bstat[wb][0] * 100) if bstat[wb][0] else 0
        dist_note = '반응과 재고가 0이라 현재 분배 불가 → 리오더 요청 우선' if bw_total <= 0 else f'반응과 {bw_total:,}장으로 분배(SCM 요청) 가능'
        st.markdown('##### 🧠 AI 진단 · 제안')
        st.markdown(
            '<div class="scenario-box" style="border-left-color:#8AB4F8">'
            '<div style="color:#8AB4F8;font-weight:bold;margin-bottom:4px">🧠 AI 진단 · 제안 '
            '<span style="color:#9FB0C0;font-weight:normal;font-size:11px">(통계·규칙 기반 자동 진단)</span></div>'
            '<div style="color:#FFFFFF;font-size:13px;line-height:1.7">'
            f'<b>진단</b> — {channel_pick} 운영 SKU {n_item:,}건 중 <b>{n_urgent:,}건({rate:.1f}%)</b>이 1주 내 결품 위험, '
            f'노출 손실 약 <b>{urgent_loss/1e8:.1f}억원</b> 규모. 복종별로는 <b>{wb}({wb_rate:.1f}%)</b>가 가장 취약 → 우선 점검.<br>'
            '<b>제안</b> — ① 회전(온라인 잉여→결품 채널) 우선 충전 · '
            f'② {dist_note} · ③ 회전·분배로 못 메우는 단품은 리오더 요청(🤖 AICA 2.0 허브) 처리 권장.'
            '</div></div>', unsafe_allow_html=True)

    # ───────────── 아이템별 ─────────────
    with sub_item:
        st.caption('아이템 = 상품코드 3~4번째 자리(예: SPPG23U07 → PG). 선택 채널 기준 집계 · 단품 상세 지표 동일 · 맨 위 합계.')
        _render_group(results_ch, _item, g_inv, g_ord, g_move, g_eff, g_ext, '아이템')

    # ───────────── 스타일별 (상품코드 10자리) ─────────────
    with sub_style:
        st.caption('스타일 = 상품코드 10자리 기준. 선택 채널 기준 집계 · 단품 상세 지표 동일 · 맨 위 합계.')
        _render_group(results_ch, lambda c: c[:10], g_inv, g_ord, g_move, g_eff, g_ext, '스타일코드', namefn=True)

    # ───────────── 단품 상세 ─────────────
    with sub_sku:
        f1, f2, f3, f4, f5 = st.columns([1.6, 1.6, 1.3, 2.4, 2])
        with f1:
            only_urgent = st.checkbox('🔴 결품(주의)만', value=False, key='ch_only_urgent')
        with f2:
            only_moved = st.checkbox('이동 발생만', value=False, key='ch_only_moved')
        with f3:
            bok_pick = st.selectbox('복종', ['전체'] + BOK_LIST, key='ch_bok')
        with f4:
            ch_search = st.text_input('검색 (상품코드/SKU)', placeholder='앞 10자리만 입력해도 OK', key='ch_search').strip().upper()
        with f5:
            ch_sort = st.selectbox('정렬', ['온라인 매출 순위 ↑', '기대효과 ↓', '이동수량 ↓', '단품코드'], key='ch_sort')

        rows = []
        s_daily = s_damt = s_inv = s_iamt = s_ext = s_mv = s_ni = s_eff = 0.0
        for r in results_ch:
            d = r['data']
            o = g_ord(d); i = g_inv(d); mv = g_move(r); p = d.get('price', 0)
            if only_moved and mv == 0:
                continue
            woc = (i / o) if o > 0 else None
            if only_urgent and not (woc is not None and woc < 2):
                continue
            if bok_pick != '전체' and _bok(r['code']) != bok_pick:
                continue
            if ch_search and not r['code'].upper().startswith(ch_search):
                continue
            daily = o / 7 if o > 0 else 0
            sojin = round(i / daily) if daily > 0 else None
            ni = i + (0 if is_all else mv)
            woc2 = (ni / o) if o > 0 else None
            ext = g_ext(d); eff = g_eff(r)
            if woc is None:
                stat = '– 무판매'
            elif woc < 1:
                stat = '🔴 긴급결품'
            elif woc < 2:
                stat = '🟡 주의'
            else:
                stat = '🟢 정상'
            row = {
                '상태': stat, '복종': _bok(r['code']),
                '상품코드': r['code'][:10], '단품코드(SKU)': r['code'],
                '상품명': (d['name'][:22] + '…') if len(d['name']) > 22 else d['name'],
                '일평균 판매량': round(daily, 1), '일평균 매출(만원)': round(daily * p / 10000, 1),
                '현 재고량': i, '현 재고금액(만원)': round(i * p / 10000),
                '내부창고': '—', '🔌항만': '—', '🔌부평': '—', '외부창고': ext,
                '현 재고주수': round(woc) if woc is not None else None,
                '소진예상(일)': sojin if sojin is not None else None,
                '추천이동': mv, '이동후재고': ni,
                '이동 후 재고주수': round(woc2) if woc2 is not None else None,
                '효과(만원)': round(eff / 10000),
            }
            rows.append((row, (sojin if sojin is not None else 10 ** 9), eff, abs(mv), d.get('rank_online', 9999), r['code']))
            s_daily += daily; s_damt += daily * p / 10000; s_inv += i; s_iamt += i * p / 10000
            s_ext += ext; s_mv += mv; s_ni += ni; s_eff += eff / 10000

        if ch_sort == '온라인 매출 순위 ↑':
            rows.sort(key=lambda x: x[4])
        elif ch_sort == '기대효과 ↓':
            rows.sort(key=lambda x: -x[2])
        elif ch_sort == '이동수량 ↓':
            rows.sort(key=lambda x: -x[3])
        else:
            rows.sort(key=lambda x: x[5])

        data = [x[0] for x in rows]
        st.caption(f'총 {len(data):,}건' + (' · 합계 외 상위 500건 표시' if len(data) > 500 else '') + ' · 맨 위 합계')
        sumrow = {
            '상태': '— 합계 —', '복종': '', '상품코드': '', '단품코드(SKU)': f'{len(data):,}건', '상품명': '',
            '일평균 판매량': round(s_daily, 1), '일평균 매출(만원)': round(s_damt, 1),
            '현 재고량': int(s_inv), '현 재고금액(만원)': round(s_iamt),
            '내부창고': '', '🔌항만': '', '🔌부평': '', '외부창고': int(s_ext),
            '현 재고주수': '', '소진예상(일)': '', '추천이동': int(s_mv), '이동후재고': int(s_ni),
            '이동 후 재고주수': '', '효과(만원)': round(s_eff),
        }
        disp = [sumrow] + data[:500]

        if data:
            df_ch = pd.DataFrame(disp)
            styled = (df_ch.style
                      .map(_stat_color, subset=['상태'])
                      .map(woc_color, subset=['현 재고주수', '이동 후 재고주수'])
                      .map(_move_color, subset=['추천이동'])
                      .apply(_hl_sum, axis=1)
                      .format({'일평균 판매량': '{:.1f}'.format, '일평균 매출(만원)': '{:.1f}'.format,
                               '현 재고량': '{:,}'.format, '현 재고금액(만원)': '{:,}'.format,
                               '현 재고주수': _woc, '이동 후 재고주수': _woc, '소진예상(일)': _int0,
                               '추천이동': '{:,}'.format, '이동후재고': '{:,}'.format, '외부창고': '{:,}'.format,
                               '효과(만원)': '{:,}'.format}))
            st.dataframe(styled, use_container_width=True, height=520, hide_index=True,
                         column_config={'복종': st.column_config.TextColumn('복종', width='small')})
        else:
            st.info('표시할 단품이 없습니다.')

        st.caption('🎨 상태: 🔴 긴급결품(<1주) · 🟡 주의(1~2주) · 🟢 정상(≥2주)   |   효과=선택 채널 기준(전체=합산)   |   외부창고=AENS·ADU3·ADQS 실데이터   |   🔌 내부창고·항만·부평=물류 API 연동(9/1) 후 표시')


def render_effect_tab():
    st.markdown('### 📈 실행 효과 누적 관리')
    st.caption('재배치 **승인 실행 시 자동 기록** (단품×채널 전일재고 스냅샷 포함) → 기대효과 대비 **실제 효과(실측)** 누적 추적.')
    st.markdown('<div class="scenario-box">📐 <b>실제효과 산식 (보수 집계)</b> — 이동(IN) 받은 단품×채널에서 '
                '<b>전일(이동 전) 재고로는 판매 불가능했던 추가 판매분만</b> 인정: '
                '추가판매 = min(이동IN, max(0, 실제판매 − 전일재고)) → 실제효과 = Σ 추가판매 × 정상가. '
                '이동 없이도 팔 수 있었던 물량은 제외. 실측일 = <b>당일 매출 기준</b> (매일 06:00 매출 갱신 후 집계). 아래 일일 매출 자료 업로드 시 자동 반영.</div>',
                unsafe_allow_html=True)

    log_rows = effect_log.load_log()

    def _f(v):
        try: return float(v)
        except Exception: return 0.0

    n_exec = len(log_rows)
    cum_qty = sum(int(_f(r.get('이동량_장'))) for r in log_rows)
    cum_exp = sum(_f(r.get('기대효과_만원')) for r in log_rows)
    measured = [r for r in log_rows if str(r.get('실제효과_만원') or '').strip()]
    cum_act = sum(_f(r.get('실제효과_만원')) for r in measured)
    cum_exp_measured = sum(_f(r.get('기대효과_만원')) for r in measured)
    rate = cum_act / cum_exp_measured * 100 if cum_exp_measured > 0 else None

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric('누적 실행', f'{n_exec:,}회', f'실측 완료 {len(measured):,}건')
    k2.metric('누적 이동량', f'{cum_qty:,}장')
    k3.metric('누적 기대효과', f'{cum_exp/10000:.2f}억')
    cum_extra = sum(int(_f(r.get('추가판매_장'))) for r in log_rows)
    k4.metric('누적 실제효과', f'{cum_act/10000:.2f}억', f'추가판매 {cum_extra:,}장 (전일재고 초과분만)')
    k5.metric('달성률 (실제/기대)', f'{rate:.1f}%' if rate is not None else '-', '실측분 기준')

    if not log_rows:
        st.info('아직 실행 이력이 없습니다. 시나리오 탭에서 "✅ 선택 N건 승인"을 실행하면 자동 기록됩니다.')
        return

    # 누적 추이 차트 (기대 vs 실제, 억원)
    df_log = pd.DataFrame(log_rows)
    df_log['기대효과_만원'] = pd.to_numeric(df_log['기대효과_만원'], errors='coerce').fillna(0)
    df_log['실제효과_만원'] = pd.to_numeric(df_log['실제효과_만원'], errors='coerce').fillna(0)
    df_chart = df_log[['실행일시']].copy()
    df_chart['누적 기대효과 (억)'] = (df_log['기대효과_만원'].cumsum() / 10000).round(3)
    df_chart['누적 실제효과 (억)'] = (df_log['실제효과_만원'].cumsum() / 10000).round(3)
    df_chart = df_chart.set_index('실행일시')
    st.line_chart(df_chart, height=240, color=['#8AB4F8', '#4AE3B5'])

    st.markdown('#### 실행 이력 · 실측 입력')
    st.caption('💡 **실제효과_만원**·**메모** 칸을 직접 수정 후 "실측 입력 저장" — 입력 시 상태가 자동으로 "실측 완료(수동)"로 변경. 1행 = Σ 합계(자동 계산, 수정 불가)')
    cum_sku = sum(int(_f(r.get('단품수'))) for r in log_rows)
    total_row = {
        'id': 'Σ', '실행일시': '— 합계 —', '시나리오': f'{n_exec}회 실행',
        '단품수': cum_sku, '이동량_장': cum_qty,
        '기대효과_만원': round(cum_exp), '실제효과_만원': round(cum_act),
        '추가판매_장': cum_extra, '실측일': '',
        '상태': f'실측 {len(measured)}/{n_exec}', '메모': '',
    }
    df_disp = pd.concat([pd.DataFrame([total_row]), df_log], ignore_index=True)

    def _hl_total(row):
        sty = 'background-color: #1E2D40; color: #4AE3B5; font-weight: bold' if str(row.get('id')) == 'Σ' else ''
        return [sty] * len(row)

    edited = st.data_editor(
        df_disp.style.apply(_hl_total, axis=1),
        use_container_width=True,
        height=320,
        hide_index=True,
        disabled=['id', '실행일시', '시나리오', '단품수', '이동량_장', '기대효과_만원', '실측일', '상태'],
        key='effect_editor',
    )

    b1, b2, b3, b4, b5 = st.columns([2, 2.4, 2, 2, 2])
    with b1:
        if st.button('💾 실측 입력 저장', type='primary', use_container_width=True, key='fx_save'):
            recs = [r for r in edited.to_dict('records') if str(r.get('id')) not in ('Σ', '합계')]
            effect_log.save_rows(recs)
            st.success('저장 완료')
            st.rerun()
    with b2:
        if st.button('🤖 실측 자동 산출 (mock·추가판매분)', use_container_width=True, key='fx_mock'):
            n = effect_log.mock_fill_actuals()
            st.success(f'{n}건 실측 채움 — 전일재고 대비 추가판매분만 집계 (실데이터 연동 전 데모)')
            st.rerun()
    with b3:
        st.download_button('⬇️ 이력 백업 (CSV)', effect_log.export_csv_bytes(),
                           'execution_log.csv', 'text/csv', use_container_width=True, key='fx_dl')
    with b4:
        up = st.file_uploader('복원', type=['csv'], key='fx_restore', label_visibility='collapsed')
        if up is not None and st.button('📂 백업 복원 (교체)', use_container_width=True, key='fx_restore_btn'):
            n = effect_log.restore_from_bytes(up.getvalue())
            st.success(f'{n}행 복원')
            st.rerun()
    with b5:
        confirm = st.checkbox('초기화 확인', key='fx_clear_ok')
        if st.button('🗑️ 이력 초기화', use_container_width=True, key='fx_clear', disabled=not confirm):
            effect_log.clear_log()
            st.rerun()

    st.markdown('#### 📂 일일 매출 자료 업로드 — 당일 실측 자동 반영')
    st.caption('매일 06:00 매출 갱신 후 업로드. 컬럼 자동 인식: 단품코드 / 채널(선택) / 판매수량 — 채널 없으면 이동IN 비중으로 배분. '
               '실측 대기 실행에 추가판매분(min(이동IN, 판매−전일재고))만 집계.')
    su1, su2 = st.columns([3, 1])
    with su1:
        sales_up = st.file_uploader('매출 자료 (csv/xlsx)', type=['csv', 'xlsx'], key='fx_sales_up', label_visibility='collapsed')
    with su2:
        if sales_up is not None and st.button('✅ 실측 반영', type='primary', use_container_width=True, key='fx_sales_apply'):
            n_exec, matched = effect_log.apply_sales_bytes(sales_up.getvalue(), sales_up.name)
            if n_exec:
                st.success(f'{n_exec}개 실행 실측 완료 (단품×채널 {matched}건 매칭)')
            else:
                st.warning('매칭된 실측 대기 실행이 없습니다 (이미 실측 완료이거나 코드 불일치).')
            st.rerun()

    with st.expander('🔍 실행별 상세 내역 (단품×채널 — 전일재고·이동IN·실제판매·추가판매)'):
        ids = [r['id'] for r in log_rows]
        pick = st.selectbox('실행 ID', ids, index=len(ids)-1, key='fx_detail_pick')
        det = effect_log.load_details(pick)
        if det:
            df_det = pd.DataFrame(det)
            st.dataframe(df_det, use_container_width=True, height=300, hide_index=True)
            st.download_button('⬇️ 상세 내역 전체 (CSV)', effect_log.export_details_bytes(),
                               'execution_details.csv', 'text/csv', key='fx_det_dl')
        else:
            st.info('이 실행에는 상세 스냅샷이 없습니다 (구버전 이력 — 실측 시 기대효과 대비 보수 추정 적용).')

    st.caption('⚠️ 이력은 앱 **재시작·재배포 시 초기화**됩니다. 주기적으로 ⬇️ 백업 CSV를 보관하고, 필요 시 📂 복원하세요. '
               '(실 배포 시 DB 저장 + audit log로 전환)')


# ============================================================
# 테스트(AICA 2.0)에서 흡수한 탭 — 🧩 추가 분배 / 🚨 리오더 요청 / 📦 입고 예정
# 진단등급·필업요청·리오더 추출·입고보정은 실데이터, 🔌 표시는 9/1 연동 예정(mock)
# ============================================================
def _kpi(col, label, value, sub=''):
    col.markdown(
        f'<div class="kpi-card" style="min-height:96px;display:flex;flex-direction:column;justify-content:center">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>'
        f'<div class="kpi-sub">{sub}</div></div>', unsafe_allow_html=True)


def _mock_int(code, salt, lo, hi):
    """코드 기반 결정적 mock 정수 — 데모 표시용(실데이터 아님)."""
    h = abs(hash(code + salt))
    return lo + (h % (hi - lo + 1))


@st.cache_data(show_spinner=False)
def imminent_rows():
    """결품 임박(온라인 합산 재고주수 < 1주, 주문>0) 단품 — 실데이터."""
    skus = load_data_v20()
    rows = []
    for c, d in skus.items():
        ti = sum(d['inv'].get(ch, 0) for ch in CHANNELS)
        to = sum(d['orders'].get(ch, 0) for ch in CHANNELS)
        if to > 0 and ti / to < 1.0:
            wk4 = to * 4
            short = max(0, wk4 - ti)
            rows.append({
                'code': c, 'name': d['name'], 'rank': d.get('rank_online', 9999),
                'inv': ti, 'ord': to, 'woc': round(ti / to, 2),
                'wk4': wk4, 'short': short, 'loss': short * d['price'], 'price': d['price'],
            })
    rows.sort(key=lambda r: -r['loss'])
    return rows



def _grade_color(s):
    if not isinstance(s, str):
        return ''
    if 'X' in s:
        return 'background-color:#5B1E1E; color:#FF6B70; font-weight:bold'
    if 'M' in s:
        return 'background-color:#5A4500; color:#FFC000; font-weight:bold'
    if 'S' in s:
        return 'background-color:#1B4D3E; color:#4AE3B5; font-weight:bold'
    return 'color:#9FB0C0'


def render_onepan_tab():
    st.markdown('### 🧩 추가 분배')
    st.markdown(
        '<div class="scenario-box">스파오 6개 엑셀(공홈 결품체크·계산기, 네이버/지그재그/키즈 한판, 지그재그 마케팅)을 '
        '한 화면으로 흡수하는 통합 단품판. <b>진단등급(S/M/X)·현재고·주판·재고주수·필업 요청수량·주력채널은 실데이터</b>, '
        '<b>🔌 필업박스(아소트 박스당 피스)·마케팅(메가위크/라이브 가중)은 9/1 연동/마스터 확보 후 표시</b>입니다. '
        '진단: 🟢S 우수(≥2주) · 🟡M 주의(1~2주) · 🔴X 결품임박(&lt;1주). 필업요청 = 목표 4주 − 현재고(공홈 계산기 안전계수).</div>',
        unsafe_allow_html=True)

    skus = load_data_v20()
    rows = []
    nX = nM = nS = 0
    fill_q = 0
    fill_amt = 0
    for code, d in skus.items():
        ti = sum(d['inv'].get(ch, 0) for ch in CHANNELS)
        to = sum(d['orders'].get(ch, 0) for ch in CHANNELS)
        if to <= 0 and ti <= 0:
            continue
        woc = ti / to if to > 0 else None
        if woc is None:
            grade = '– 무판매'
        elif woc < 1:
            grade = '🔴 X 결품임박'; nX += 1
        elif woc < 2:
            grade = '🟡 M 주의'; nM += 1
        else:
            grade = '🟢 S 우수'; nS += 1
        fillq = max(0, round(4 * to - ti)) if to > 0 else 0
        fill_q += fillq
        fill_amt += fillq * d.get('price', 0)
        topch = max(CHANNELS, key=lambda ch: d['orders'].get(ch, 0)) if to > 0 else '-'
        rows.append({
            '진단': grade, '단품코드': code,
            '상품명': (d['name'][:20] + '…') if len(d['name']) > 20 else d['name'],
            '주력채널': CH_SHORT.get(topch, topch), '현재고': ti, '주판': to,
            '재고주수': round(woc, 1) if woc is not None else None,
            '필업요청(장)': fillq, '🔌필업박스': '—', '🔌마케팅': '—',
            '_sort': fillq,
        })

    k = st.columns(5)
    _kpi(k[0], '🔴 결품임박(X)', f'{nX:,}건', '재고주수 < 1주')
    _kpi(k[1], '🟡 주의(M)', f'{nM:,}건', '1~2주')
    _kpi(k[2], '🟢 우수(S)', f'{nS:,}건', '≥ 2주')
    _kpi(k[3], '📦 필업 요청수량', f'{fill_q:,}장', '목표 4주 − 현재고')
    _kpi(k[4], '💰 필업 요청금액', f'{fill_amt/1e8:.1f}억', '필업 × 정상가')

    f1, f2, f3 = st.columns([1.5, 3, 2])
    with f1:
        g = st.selectbox('진단', ['전체', '🔴 X 결품임박', '🟡 M 주의', '🟢 S 우수'], key='op_grade')
    with f2:
        q = st.text_input('검색 (단품코드 앞 10자리)', key='op_q').strip().upper()
    with f3:
        srt = st.selectbox('정렬', ['필업요청 ↓', '주판 ↓', '재고주수 ↑'], key='op_sort')

    view = rows
    if g != '전체':
        view = [r for r in view if r['진단'] == g]
    if q:
        view = [r for r in view if r['단품코드'].startswith(q)]
    if srt == '필업요청 ↓':
        view.sort(key=lambda r: -r['_sort'])
    elif srt == '주판 ↓':
        view.sort(key=lambda r: -r['주판'])
    else:
        view.sort(key=lambda r: (r['재고주수'] if r['재고주수'] is not None else 999))
    st.caption(f'총 {len(view):,}건' + (' · 상위 500건 표시' if len(view) > 500 else ''))
    view = view[:500]

    if view:
        df = pd.DataFrame([{kk: vv for kk, vv in r.items() if kk != '_sort'} for r in view])
        styled = (df.style.map(_grade_color, subset=['진단'])
                  .map(woc_color, subset=['재고주수'])
                  .format({'현재고': '{:,}'.format, '주판': '{:,}'.format,
                           '필업요청(장)': '{:,}'.format, '재고주수': lambda v: '' if v is None else f'{v:.1f}'}))
        st.dataframe(styled, use_container_width=True, height=520, hide_index=True)
    else:
        st.info('조건에 맞는 단품이 없습니다.')

    st.caption('✉️ ARS 자동메일: 매주 월 06:00 결품임박(X) 단품을 SCM팀에 자동 작성·발송 (🚨 리오더 요청 탭에서 초안 확인). '
               '🔌 필업박스·마케팅 뱃지는 박스 마스터·마케팅 캘린더 연동 후 활성화.')


def render_reorder_request_tab():
    st.markdown('### 🚨 리오더 요청')
    st.caption('결품 임박(온라인 합산 재고주수 < 1주) 단품을 자동 추출합니다. 회전(재배치)으로 못 메우는 잠재 결품을 '
               '리오더로 연결 — ARS가 베스트만 관리하는 것과 달리 **워스트(잠재 결품)까지 관리**합니다. (실데이터)')
    rows = imminent_rows()
    c1, c2, c3 = st.columns(3)
    _kpi(c1, '결품 임박 단품', f'{len(rows):,}건', '재고주수 < 1주')
    _kpi(c2, '4주 결품 노출액', f"{sum(r['loss'] for r in rows)/1e8:.1f}억", '부족분 × 정상가')
    _kpi(c3, '리오더 권장 물량', f"{sum(r['short'] for r in rows):,}장", '4주 수요 − 현재고')

    f1, f2 = st.columns([3, 2])
    with f1:
        q = st.text_input('단품코드 검색', placeholder='앞 10자리 입력 (예: SPCKG24G01)', key='aica_reo_q').strip().upper()
    with f2:
        topn = st.selectbox('표시 건수', [30, 50, 100, 200], index=1, key='aica_reo_top')
    view = [r for r in rows if (not q or r['code'].startswith(q))][:topn]

    df = pd.DataFrame([{
        '온라인순위': r['rank'], '단품코드': r['code'],
        '단품명': (r['name'][:20] + '…') if len(r['name']) > 20 else r['name'],
        '현재고(장)': r['inv'], '주간판매(장)': r['ord'], '재고주수': f"{r['woc']}주",
        '4주 수요(장)': r['wk4'], '리오더 권장(장)': r['short'], '노출액(만원)': round(r['loss'] / 10000),
    } for r in view])
    if not df.empty:
        styled = df.style.map(woc_color, subset=['재고주수']).format({'노출액(만원)': '{:,}'.format})
        st.dataframe(styled, use_container_width=True, height=430, hide_index=True)
    else:
        st.info('조건에 맞는 단품이 없습니다.')

    st.markdown('#### ✉️ 리오더 요청 메일 초안 (상위 노출 단품)')
    st.caption('직접 명령하지 않고, **요청 가능한 상태 + 4주 판매량 데이터**까지만 제공합니다(6/12 합의).')
    n_mail = min(10, len(view))
    body = [
        '제목: [리오더 요청] 결품 임박 단품 ' + f'{n_mail}건 검토 요청 (자동 추출)',
        '',
        '안녕하세요. 온라인 재고 모니터링 기준 1주 내 결품이 예상되는 단품입니다.',
        '4주 판매량 대비 부족분 기준 리오더 검토 부탁드립니다.',
        '',
        f"{'단품코드':<17}{'4주수요':>7}{'현재고':>7}{'권장리오더':>9}  단품명",
    ]
    for r in view[:n_mail]:
        body.append(f"{r['code']:<17}{r['wk4']:>7}{r['inv']:>7}{r['short']:>9}  {r['name'][:18]}")
    body += ['', '※ 본 메일은 자동 추출한 초안입니다. 실제 발주는 MD 검토 후 진행해 주세요.']
    st.text_area('메일 초안 (복사해서 사용)', value='\n'.join(body), height=260, key='aica_reo_mail')


def render_inbound_tab():
    st.markdown('### 📦 입고 예정')
    st.markdown('<div class="scenario-box">🔌 <b>신규 데이터 — 9/1 API/수기 연동 예정</b>. 발주완료·이동중·항만입항(입항 중) '
                '수량을 가용재고에 더해 결품 판정을 보정합니다. <b>아래 입고예정 수치는 데모(mock)</b>이며, 현재고·주간판매는 실데이터입니다.</div>',
                unsafe_allow_html=True)
    apply_in = st.toggle('입고 예정 반영 (가용재고 = 현재고 + 입고예정)', value=True, key='aica_in_apply')

    rows = imminent_rows()[:60]
    out = []
    resolved = 0
    for r in rows:
        po = _mock_int(r['code'], 'po', 0, max(1, r['short']))            # 발주완료
        transit = _mock_int(r['code'], 'tr', 0, max(1, r['short'] // 2))  # 이동중
        port = _mock_int(r['code'], 'pt', 0, max(1, r['short'] // 3))     # 항만입항
        incoming = po + transit + port
        avail = r['inv'] + (incoming if apply_in else 0)
        woc2 = round(avail / r['ord'], 2) if r['ord'] else None
        if apply_in and woc2 is not None and woc2 >= 1:
            resolved += 1
        out.append({
            '단품코드': r['code'], '현재고': r['inv'], '주간판매': r['ord'], '현재고주수': f"{r['woc']}주",
            '🔌발주완료': po, '🔌이동중': transit, '🔌항만입항': port, '🔌입고예정계': incoming,
            '보정 가용재고': avail, '보정 재고주수': (f"{woc2}주" if woc2 is not None else ''),
        })
    c1, c2 = st.columns(2)
    _kpi(c1, '입고예정 반영 시 결품 해소', f'{resolved:,}건' if apply_in else '—', '보정 재고주수 ≥ 1주 (mock)')
    _kpi(c2, '검토 대상', f'{len(rows):,}건', '결품 임박 상위')
    df = pd.DataFrame(out)
    if not df.empty:
        styled = df.style.map(woc_color, subset=['현재고주수', '보정 재고주수'])
        st.dataframe(styled, use_container_width=True, height=430, hide_index=True)
    st.caption('💡 운영 효과: 입고예정이 충분한 단품은 리오더 요청에서 자동 제외 → 중복 발주 방지. (연동 후 실수치로 동작)')


def render():
    st.markdown('<div class="title-bar">온라인 재고관리 Agent — 운영 대시보드<span class="ver-badge">v5.7</span></div>', unsafe_allow_html=True)
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
        st.caption('v5.7')

    # 메뉴군 구분 여백 — 2군(리오더 요청, 5번째)·3군(채널 IN-OUT, 8번째) 앞에 간격.
    # 최상위 탭리스트에만 적용(중첩 탭은 tab-panel 안에 있어 제외).
    st.markdown("""
    <style>
    div[data-baseweb="tab-list"]:not([data-baseweb="tab-panel"] *) [data-baseweb="tab"]:nth-child(5),
    div[data-baseweb="tab-list"]:not([data-baseweb="tab-panel"] *) [data-baseweb="tab"]:nth-child(8){
        margin-left: 34px;
    }
    </style>
    """, unsafe_allow_html=True)

    labels = ['🛡️ 재배치(기본)', '🎛️ 재배치(임의)', '🧩 추가 분배', '📈 실행 효과',
              '🚨 리오더 요청', '📊 채널 별 세부', '📦 입고 예정',
              '🚫 채널 IN-OUT (MD 기입)', '🔁 리오더 매핑 (SCM 기입)']
    t = st.tabs(labels)
    with t[0]:
        render_scenario('🛡️ 기본', st, allow_slider=False)
    with t[1]:
        render_scenario('🎛️ 사용자 정의', st, allow_slider=True)
    with t[2]:
        render_onepan_tab()
    with t[3]:
        render_effect_tab()
    with t[4]:
        render_reorder_request_tab()
    with t[5]:
        render_channel_tab()
    w