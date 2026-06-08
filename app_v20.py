# -*- coding: utf-8 -*-
"""
v4.2 화면 — 자동분배 제거 · 리오더코드 병합 · 외부창고 분리(엔진) + v1.6 기능 복원
복원: 단품코드 검색(앞 10자리) · 🚫 제외 스타일 탭 · 📊 채널 별 세부 탭(외부창고 컬럼은 여기만)
      · 체크박스 단품 선택 승인 · 사용자 정의 기준 명칭
(페이지 설정·비밀번호 게이트·공통 CSS는 app.py 담당)
"""
import streamlit as st
import pandas as pd

from rebalance_engine import calc_rebalance_group, calc_after_woc, calc_expected_revenue
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
    '🛡️ 방어형 (추천)': {
        'desc': '부족 1주 / 목표 4주 — 결품 임박 시 4주까지 충분히 충전. 운영 부담 최소·효과 극대',
        'shortage_th': 1.0, 'target_woc': 4.0,
        'ship_th': 0.90, 'min_move': 0, 'min_recv': 4,
    },
    '🎛️ 사용자 정의': {
        'desc': '상단 슬라이더로 직접 조정',
        'shortage_th': 1.0, 'target_woc': 2.0,
        'ship_th': 0.90, 'min_move': 10, 'min_recv': 4,
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
        'min_recv_order': params_key[4],
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


def render_scenario(scenario_key, container, allow_slider=False):
    preset = SCENARIOS[scenario_key]

    if allow_slider:
        container.markdown('### 🎛️ 사용자 정의 기준')
        sl1, sl2, sl3, sl4, sl5 = container.columns(5)
        with sl1:
            shortage_th = st.slider('재배치 대상 (재고주수 0주 이하)', 0.5, 4.0, preset['shortage_th'], 0.5, key=f'sh_{scenario_key}')
        with sl2:
            target_woc = st.slider('목표 재고주수 (주)', 1.0, 6.0, preset['target_woc'], 0.5, key=f'tg_{scenario_key}')
        with sl3:
            ship_th = st.slider('현 출고율 (%)', 50, 100, int(preset['ship_th']*100), 5, key=f'sp_{scenario_key}') / 100
        with sl4:
            min_move = st.slider('이동 ≥ N장만 (비부가 제거)', 0, 50, preset['min_move'], 1, key=f'mn_{scenario_key}')
        with sl5:
            min_recv = st.slider('소액 채널 제외 (주간주문 N장 미만)', 0, 20, preset.get('min_recv', 4), 1, key=f'mr_{scenario_key}')
    else:
        shortage_th = preset['shortage_th']
        target_woc = preset['target_woc']
        ship_th = preset['ship_th']
        min_move = preset['min_move']
        min_recv = preset.get('min_recv', 4)

    container.markdown(f'<div class="scenario-box">{preset["desc"]}</div>', unsafe_allow_html=True)

    with st.spinner('계산 중...'):
        params_key = (shortage_th, target_woc, ship_th, min_move, min_recv)
        results = calc_results_v20(params_key)
    results = _apply_exclusion(results)

    total_skus = len(results)
    moved_count = sum(1 for r in results if any(v != 0 for v in r['moves'].values()))
    total_units = sum(sum(r['data']['inv'].get(c, 0) for c in CHANNELS) for r in results)
    total_units_amt = sum(sum(r['data']['inv'].get(c, 0) for c in CHANNELS) * r['data']['price'] for r in results)
    total_in = sum(sum(v for v in r['moves'].values() if v > 0) for r in results)
    total_amt = sum(sum(v for v in r['moves'].values() if v > 0) * r['data']['price'] for r in results)
    total_rev = sum(r['revenue'] for r in results)

    def kpi_card(col, label, value, sub=''):
        col.markdown(f"""<div class="kpi-card"><div class="kpi-label">{label}</div>
            <div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>""", unsafe_allow_html=True)

    kpi_ph = container.container()  # 체크박스 선택 반영 위해 매트릭스 구성 후 채움

    col_f1, col_fs, col_f3 = container.columns([1.6, 4, 2])
    with col_f1:
        show_only_moved = st.checkbox('이동 발생만', value=True, key=f'moved_{scenario_key}')
    with col_fs:
        search_code = st.text_input(
            '단품코드 검색',
            placeholder='앞 10자리만 입력해도 OK (예: SPPPG25U05)',
            key=f'search_{scenario_key}',
        ).strip().upper()
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

    # ── KPI 채움: 좌측 체크박스 선택 시 선택분 기준으로 자동 갱신 ──
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
    else:
        _units, _units_amt, _in, _amt, _rev, _sub = total_units, total_units_amt, total_in, total_amt, total_rev, '전체 기준'
    with kpi_ph:
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        kpi_card(k1, '총 단품량', f'{_units:,}장', f'6채널 재고 합계 · {_sub}')
        kpi_card(k2, '총 이동량', f'{_in:,}장', f'주간 IN · {_sub}')
        kpi_card(k3, '총 재고금액', f'{_units_amt/100000000:.1f}억', f'재고수량 × 정상가 · {_sub}')
        kpi_card(k4, '총 이동 금액', f'{_amt/100000000:.2f}억', f'이동수량 × 정상가 · {_sub}')
        kpi_card(k5, '회수 매출', f'{_rev/100000000:.2f}억', f'주간 · {_sub}')
        kpi_card(k6, '연 환산', f'{_rev*52/100000000:.0f}억', '× 52주')

    rows = []
    for r in filtered:
        d = r['data']; mv = r['moves']; af = r['after']; inv = d['inv']
        name = d['name']
        if len(name) > 14: name = name[:13] + '…'
        row = [d.get('rank_online', '-'), r['code'], name,
               f"{d.get('cum_rate', 0)*100:.0f}%", f"{d.get('wk_rate', 0)*100:.0f}%", f"{int(d['ship_rate']*100)}%"]
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
    selected_rows = []
    if rows:
        columns = pd.MultiIndex.from_tuples(
            [('', '온라인순위'), ('', '단품코드'), ('', '단품명'), ('', '누판율'), ('', '주판율'), ('', '출고율')] +
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
        '단위: 재고/이동후 = "주" · 이동 = "장(±)" · 효과 = "만원"    |    '
        '※ 이동수량 산정 시 외부창고(AENS·ADU3·ADQS) 보관분 제외 — 재고주수는 포함 (상세: 채널 별 세부 탭)    |    '
        '🎯 분배: 결품 실해소 가능 채널에 우선 배분(소량 무의미 이동 제외) · 동률 시 저수수료 순(공홈>네이버>이몰>무신>카카오>지재)'
    )

    sel_items = []
    if rows:
        sel_items = [filtered[i] for i in selected_rows] if selected_rows else list(filtered)
    sel_qty = sum(sum(v for v in it['moves'].values() if v > 0) for it in sel_items)
    sel_rev = sum(it['revenue'] for it in sel_items)

    col_b1, col_b2, col_b3 = container.columns([2, 2, 4])
    with col_b1:
        if st.button(f'✅ 선택 {sel_count}건 승인', use_container_width=True, type='primary', key=f'approve_{scenario_key}'):
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


def render_channel_tab():
    st.markdown('### 📊 채널 담당자용 상세 데이터')

    channel_pick = st.radio('채널 선택', CHANNELS, horizontal=True, key='ch_pick')

    preset = SCENARIOS['🛡️ 방어형 (추천)']
    params_key = (preset['shortage_th'], preset['target_woc'], preset['ship_th'], preset['min_move'], preset.get('min_recv', 4))
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


def render():
    st.markdown('<div class="title-bar">REBA_재고재배치 Agent — 운영 대시보드<span class="ver-badge">v4.2</span></div>', unsafe_allow_html=True)
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
        st.caption('v4.2')

    tab_d, tab_c, tab_x, tab_ch, tab_re, tab_fx = st.tabs(
        list(SCENARIOS.keys()) + ['🚫 제외 스타일', '📊 채널 별 세부', '🔁 리오더 매핑', '📈 실행 효과']
    )

    with tab_d:
        render_scenario('🛡️ 방어형 (추천)', st, allow_slider=False)

    with tab_c:
        render_scenario('🎛️ 사용자 정의', st, allow_slider=True)

    with tab_x:
        render_excluded_tab()

    with tab_ch:
        render_channel_tab()

    with tab_re:
        render_reorder_tab()

    with tab_fx:
        render_effect_tab()

    st.caption('© 2026 Fashion BG · CAIO실 AX 혁신팀 · 강훈구  |  v4.2 — 자동분배 제거 · 리오더 병합 · 외부창고 분리(엔진) · 검색/제외 스타일/채널 별 세부/선택 승인')
