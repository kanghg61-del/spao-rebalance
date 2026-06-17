# -*- coding: utf-8 -*-
"""
AICA 2.0 (테스트) 화면 — 6/12·6/16 스파오 미팅 아젠다 반영 프로토타입

v5.6 엔진·데이터는 그대로(읽기 전용) 위에, 미팅에서 요청된 4대 확장 기능을 얹는다:
  ① 🚨 리오더 요청 허브   — 결품 임박(≤1주) 단품 자동 추출 + 4주 판매량 + 리오더 요청 메일 초안
                           (ARS는 베스트만, AICA는 워스트=잠재결품까지 관리 — 6/12 ③ 대전환)
  ② 📦 입고 예정 반영     — 발주완료·이동중·항만입항 수량을 가용재고에 반영해 결품 판정 보정 (6/12 ④)
  ③ 🏬 통합 재고 뷰       — 온라인+외부창고+매장/본부 재고를 한 화면 조회 (6/12 ①②)
  ④ 🎚️ 목표주수 완화      — 목표 4주 → 2주 프리셋 비교 (6/12 ⑤ · 현 무재고 정책상 빨강 과다 대응)

정직성 라벨: 외부창고 재고는 실데이터. '입고예정·매장/본부 재고'는 신규 데이터 소스(채널/물류 API,
9/1 연동 예정)라 현재 화면은 데모(mock)이며 🔌 표시로 명확히 구분한다. 리오더·목표완화는 실데이터 산출.
"""
import streamlit as st
import pandas as pd

from app_v20 import load_data_v20, calc_results_v20, CH_SHORT
from mock_data import CHANNELS, EXT_WAREHOUSE, get_last_update_time

# 기본 시나리오 키 (부족1주/목표4주/상한50%) 와 완화 시나리오 키 (목표2주)
KEY_4W = (1.0, 4.0, 0.90, 0, 0, (), 0.50)
KEY_2W = (1.0, 2.0, 0.90, 0, 0, (), 0.50)


def _kpi(col, label, value, sub=''):
    col.markdown(
        f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>'
        f'<div class="kpi-sub">{sub}</div></div>', unsafe_allow_html=True)


def woc_color(v):
    try:
        x = float(str(v).replace('주', ''))
    except Exception:
        return ''
    if x < 1:
        return 'background-color:#5B1E1E; color:#FF6B70; font-weight:bold'
    if x < 4:
        return 'background-color:#5A4500; color:#FFC000; font-weight:bold'
    return 'background-color:#1B4D3E; color:#4AE3B5; font-weight:bold'


def _mock_int(code, salt, lo, hi):
    """코드 기반 결정적(deterministic) mock 정수 — 데모 표시용 (실데이터 아님)."""
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


@st.cache_data(show_spinner=False)
def scenario_kpis():
    """목표 4주 vs 2주 — 이동량·회수효과 비교 (실데이터 엔진 산출)."""
    out = {}
    for label, key in [('4주', KEY_4W), ('2주', KEY_2W)]:
        res = calc_results_v20(key)
        moved = sum(1 for r in res if any(v != 0 for v in r['moves'].values()))
        ins = sum(sum(v for v in r['moves'].values() if v > 0) for r in res)
        rev = sum(r['revenue'] for r in res)
        out[label] = {'moved': moved, 'in': ins, 'rev': rev}
    return out


# ============================================================
def render():
    st.markdown('<div class="title-bar">AICA 2.0 <span class="ver-badge">테스트 · 스파오 미팅 반영</span></div>',
                unsafe_allow_html=True)
    last = get_last_update_time()
    st.caption(f'온라인 통합 재고 + 리오더 의사결정 허브 (프로토타입)  ·  데이터 기준 {last.strftime("%Y-%m-%d %H:%M")}  ·  '
               '6/12·6/16 스파오 현업 미팅 아젠다 반영')
    st.markdown(
        '<div class="scenario-box">🧪 <b>테스트 버전 안내</b> — v5.6 엔진·데이터 위에 미팅 요청 4대 기능을 얹은 시연용입니다. '
        '<b>외부창고 재고·리오더·목표완화는 실데이터 산출</b>, '
        '<b>🔌 표시(입고예정·매장/본부 재고)는 신규 데이터 소스로 9/1 API 연동 예정 → 현재는 데모(mock)</b>입니다.</div>',
        unsafe_allow_html=True)

    tabs = st.tabs(['🤖 브리핑', '🧩 단품 한판', '🚨 리오더 요청 허브', '📦 입고 예정 반영', '🏬 통합 재고 뷰', '🎚️ 목표주수 완화'])
    with tabs[0]:
        _tab_brief()
    with tabs[1]:
        _tab_onepan()
    with tabs[2]:
        _tab_reorder()
    with tabs[3]:
        _tab_inbound()
    with tabs[4]:
        _tab_unified()
    with tabs[5]:
        _tab_scenario()


# ── ① 브리핑 ──────────────────────────────────────────────
def _tab_brief():
    rows = imminent_rows()
    n = len(rows)
    loss = sum(r['loss'] for r in rows)
    sk = scenario_kpis()
    st.markdown('### 🤖 오늘의 브리핑')
    k1, k2, k3, k4 = st.columns(4)
    _kpi(k1, '결품 임박 단품', f'{n:,}건', '온라인 합산 재고주수 < 1주')
    _kpi(k2, '4주 결품 노출액', f'{loss/1e8:.1f}억', '부족분 × 정상가 (실데이터)')
    _kpi(k3, '회수 가능(목표4주)', f"{sk['4주']['rev']/1e8:.2f}억", f"주간 · 이동 {sk['4주']['in']:,}장")
    _kpi(k4, '회수 가능(목표2주)', f"{sk['2주']['rev']/1e8:.2f}억", f"주간 · 이동 {sk['2주']['in']:,}장")

    st.markdown('')
    st.markdown(
        f'<div class="scenario-box" style="font-size:13px; line-height:1.7">'
        f'현재 온라인 6채널에서 <b>{n:,}개 단품이 1주 내 결품 위험</b>이며, 4주 수요 기준 채우지 못하는 물량의 '
        f'정상가 노출액은 <b>{loss/1e8:.1f}억원</b> 규모입니다. 무재고·정판강화 정책상 재배치(회전)만으로는 한계가 있어, '
        f'<b>① 리오더 요청 허브</b>로 결품 임박 단품을 자동 추출해 4주 판매량과 함께 리오더 요청 초안을 만들고, '
        f'<b>② 입고 예정</b> 물량을 가용재고에 반영해 불필요한 리오더를 거르며, <b>③ 통합 재고 뷰</b>로 외부창고·매장/본부 '
        f'재고까지 한 화면에서 점검합니다. <b>④ 목표주수</b>는 현 환경에 맞춰 2주로 완화 시뮬레이션이 가능합니다.</div>',
        unsafe_allow_html=True)

    st.markdown('#### 📌 이번 테스트에 반영한 미팅 아젠다')
    df = pd.DataFrame([
        ['🚨 리오더 요청 허브', '6/12 ③ (대전환·★★)', '결품 임박 단품 + 4주 판매량 + 요청 메일 초안. ARS=베스트, AICA=워스트까지', '실데이터'],
        ['📦 입고 예정 반영', '6/12 ④ / 6/16 추가지표', '발주완료·이동중·항만입항을 가용재고에 반영해 결품 판정 보정', '🔌 연동예정(mock)'],
        ['🏬 통합 재고 뷰', '6/12 ①②', '온라인+외부창고(실)+매장/본부(mock) 통합 조회', '일부 🔌 mock'],
        ['🎚️ 목표주수 완화', '6/12 ⑤', '목표 4주 → 2주 프리셋 비교 (빨강 과다 대응)', '실데이터'],
    ], columns=['기능', '미팅 근거', '내용', '데이터'])
    st.dataframe(df, use_container_width=True, hide_index=True)


# ── ② 리오더 요청 허브 ────────────────────────────────────
def _tab_reorder():
    st.markdown('### 🚨 리오더 요청 허브')
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
    st.caption('AICA는 ARS에 직접 명령하지 않고, **요청 가능한 상태 + 4주 판매량 데이터**까지만 제공합니다(6/12 합의).')
    n_mail = min(10, len(view))
    body = [
        '제목: [리오더 요청] 결품 임박 단품 ' + f'{n_mail}건 검토 요청 (AICA 자동 추출)',
        '',
        '안녕하세요. 온라인 재고 모니터링(AICA) 기준 1주 내 결품이 예상되는 단품입니다.',
        '4주 판매량 대비 부족분 기준 리오더 검토 부탁드립니다.',
        '',
        f"{'단품코드':<17}{'4주수요':>7}{'현재고':>7}{'권장리오더':>9}  단품명",
    ]
    for r in view[:n_mail]:
        body.append(f"{r['code']:<17}{r['wk4']:>7}{r['inv']:>7}{r['short']:>9}  {r['name'][:18]}")
    body += ['', '※ 본 메일은 AICA가 자동 추출한 초안입니다. 실제 발주는 MD 검토 후 진행해 주세요.']
    st.text_area('메일 초안 (복사해서 사용)', value='\n'.join(body), height=260, key='aica_reo_mail')


# ── ③ 입고 예정 반영 ──────────────────────────────────────
def _tab_inbound():
    st.markdown('### 📦 입고 예정 반영')
    st.markdown('<div class="scenario-box">🔌 <b>신규 데이터 — 9/1 API/수기 연동 예정</b>. 발주완료·이동중·항만입항(입항 중) '
                '수량을 가용재고에 더해 결품 판정을 보정합니다. <b>아래 입고예정 수치는 데모(mock)</b>이며, 현재고·주간판매는 실데이터입니다.</div>',
                unsafe_allow_html=True)
    apply_in = st.toggle('입고 예정 반영 (가용재고 = 현재고 + 입고예정)', value=True, key='aica_in_apply')

    rows = imminent_rows()[:60]
    out = []
    resolved = 0
    for r in rows:
        # mock 입고예정: 발주완료/이동중/항만입항 (데모) — 코드 기반 결정적
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


# ── ④ 통합 재고 뷰 ────────────────────────────────────────
def _tab_unified():
    st.markdown('### 🏬 통합 재고 뷰')
    st.markdown('<div class="scenario-box">온라인 6채널 + 외부창고(실데이터) + 🔌매장/본부 재고(9/1 연동 예정·mock)를 '
                '한 화면에서 조회합니다. 6/12 미팅 ①② — "단순 회전 도구 → 온라인 통합 재고 허브" 확장 방향.</div>',
                unsafe_allow_html=True)
    skus = load_data_v20()
    # 채널별 집계 (온라인재고/외부창고 = 실데이터)
    agg = {ch: {'inv': 0, 'ext': 0} for ch in CHANNELS}
    for d in skus.values():
        for ch in CHANNELS:
            agg[ch]['inv'] += d['inv'].get(ch, 0)
            agg[ch]['ext'] += d.get('ext_wh', {}).get(ch, 0)
    rows = []
    tot = {'on': 0, 'ext': 0, 'store': 0, 'hub': 0}
    for ch in CHANNELS:
        on = agg[ch]['inv']
        ext = agg[ch]['ext']
        wh = EXT_WAREHOUSE.get(ch)
        wh_label = f'{wh[0]}({wh[1]})' if wh else '-'
        store = _mock_int(ch, 'store', 2000, 9000)   # 🔌 매장 재고 (mock)
        hub = _mock_int(ch, 'hub', 1000, 6000)       # 🔌 본부 재고 (mock)
        rows.append({
            '채널': ch, '온라인 재고(장)': on, '외부창고(장)': ext, '외부창고처': wh_label,
            '🔌매장재고(장)': store, '🔌본부재고(장)': hub, '통합 가용(장)': on + store + hub,
        })
        tot['on'] += on; tot['ext'] += ext; tot['store'] += store; tot['hub'] += hub
    c1, c2, c3, c4 = st.columns(4)
    _kpi(c1, '온라인 재고', f"{tot['on']:,}장", '6채널 합계 (실)')
    _kpi(c2, '외부창고', f"{tot['ext']:,}장", 'AENS·ADU3·ADQS (실)')
    _kpi(c3, '🔌 매장 재고', f"{tot['store']:,}장", '연동예정 (mock)')
    _kpi(c4, '🔌 본부 재고', f"{tot['hub']:,}장", '연동예정 (mock)')
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption('🔌 매장·본부 재고는 SCM팀 권한 영역으로 6/12 미팅에서 "조회까지라도" 요청된 항목 — 연동 후 실재고·메일링 자동화 예정.')


# ── ⑤ 목표주수 완화 ──────────────────────────────────────
def _tab_scenario():
    st.markdown('### 🎚️ 목표주수 완화 (4주 → 2주)')
    st.caption('현 무재고·정판강화 정책에서 목표 4주 기준은 거의 모든 단품이 빨강이 됩니다. 목표를 2주로 낮추면 '
               '회전 대상·이동량이 달라집니다 — 운영 안정화 기간 동안 조정안 비교. (실데이터 엔진 산출)')
    sk = scenario_kpis()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown('#### 🛡️ 현행 — 목표 4주')
        _kpi(st, '이동 발생 단품', f"{sk['4주']['moved']:,}건", '')
        _kpi(st, '총 이동량', f"{sk['4주']['in']:,}장", '주간 IN')
        _kpi(st, '회수 매출', f"{sk['4주']['rev']/1e8:.2f}억", f"연 {sk['4주']['rev']*52/1e8:.0f}억")
    with c2:
        st.markdown('#### 🎚️ 완화 — 목표 2주')
        _kpi(st, '이동 발생 단품', f"{sk['2주']['moved']:,}건", '')
        _kpi(st, '총 이동량', f"{sk['2주']['in']:,}장", '주간 IN')
        _kpi(st, '회수 매출', f"{sk['2주']['rev']/1e8:.2f}억", f"연 {sk['2주']['rev']*52/1e8:.0f}억")
    d_in = sk['2주']['in'] - sk['4주']['in']
    d_rev = (sk['2주']['rev'] - sk['4주']['rev']) / 1e8
    st.markdown(
        f'<div class="scenario-box">📊 <b>차이(2주 − 4주)</b> — 이동량 {d_in:+,}장 · 회수 매출 {d_rev:+.2f}억/주. '
        '목표를 낮추면 채워야 할 목표선이 내려가 이동량·회수효과가 줄지만, 그만큼 보수적으로 운영됩니다. '
        '정식 적용 전 운영 안정화 기간에 본 비교로 기준을 합의하세요. (확정 시 v5.6 기본값에 반영)</div>',
        unsafe_allow_html=True)


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


def _tab_onepan():
    st.markdown('### 🧩 단품 한판 (통합)')
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

    st.caption('✉️ ARS 자동메일: 매주 월 06:00 결품임박(X) 단품을 SCM팀에 자동 작성·발송 (🚨 리오더 요청 허브 탭에서 초안 확인). '
               '🔌 필업박스·마케팅 뱃지는 박스 마스터·마케팅 캘린더 연동 후 활성화.')
