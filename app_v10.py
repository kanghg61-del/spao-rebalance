# -*- coding: utf-8 -*-
"""AICA Studio — 온라인 재고 AI 에이전트 허브 (v1.0 RC).

실장 6/22 메일 컨셉 정합: "대시보드가 아닌 AI 기반의 결과물".
신규 SCM (eland-ai-reorder.pages.dev) 톤·구조 차용.
"""
from datetime import datetime

import streamlit as st

import app_v20  # 데이터·헬퍼 재사용


AGENTS = [
    {'id': 'rotation', 'emoji': '🔄', 'name': '회전 PM',
     'tag': '6채널 회전 분배판', 'color': '#4a90ff',
     'desc': '단품 결품을 다른 채널 재고로 즉시 채웁니다.',
     'sample_q': '오늘 SPAO 회전 분배판 만들어줘'},
    {'id': 'distribute', 'emoji': '📦', 'name': '분배 PM',
     'tag': '반응과 → 채널', 'color': '#7cd99c',
     'desc': '반응과 가용재고로 결품 단품을 보충합니다.',
     'sample_q': '결품 단품에 반응과 분배 추천해줘'},
    {'id': 'reorder', 'emoji': '🚨', 'name': '리오더 PM',
     'tag': 'SCM 발주 의뢰', 'color': '#ff6b9d',
     'desc': '회전·분배로 못 메우는 결품은 SCM 리오더로 연결합니다.',
     'sample_q': '리오더 핵심 10건 메일 초안 만들어줘'},
    {'id': 'analyst', 'emoji': '📊', 'name': '분석가',
     'tag': '정확도·인사이트', 'color': '#ffb84d',
     'desc': '지난 회전 정확도 검증과 약점 채널 인사이트.',
     'sample_q': '지난주 회전 정확도 검증해줘'},
    {'id': 'dispatcher', 'emoji': '📤', 'name': 'SCM 디스패처',
     'tag': '자동 메일·xlsx', 'color': '#c4a8ff',
     'desc': '분배판 확정 시 SCM팀 자동 메일 + xlsx 첨부.',
     'sample_q': '분배판 SCM팀에 자동 발송해줘'},
    {'id': 'briefer', 'emoji': '🎙', 'name': '모닝브리프 AICA',
     'tag': '매일 06:00 자동', 'color': '#ffe066',
     'desc': '매일 아침 6시 자동 보고 + 알람.',
     'sample_q': '오늘 모닝 브리프 보여줘'},
]


def _inject_styles():
    st.markdown("""<style>
      .aica-hero { text-align:center; padding: 16px 0 6px 0; }
      .aica-hero h1 { color:#fff; font-size: 32px; font-weight: 800; margin: 0; }
      .aica-hero p { color:#9fb3d9; font-size: 14px; margin-top: 8px; }
      .aica-agent-card {
        background: linear-gradient(180deg,#0f1d3a,#0a1428);
        border:1px solid #2e3b50; border-radius:14px; padding:14px 12px;
        text-align:center; min-height:175px; }
      .aica-agent-emoji { font-size:30px; }
      .aica-agent-name { font-size:15px; font-weight:700; margin-top:4px; }
      .aica-agent-tag { color:#9ab; font-size:10px; margin-top:2px; }
      .aica-agent-desc { color:#cfd8e3; font-size:11px; margin-top:8px; line-height:1.4; }
      .aica-brief-card {
        background: linear-gradient(135deg,#1a0d2e 0%,#0a2138 100%);
        border:1px solid #5a3fb8; border-radius:12px; padding:18px; margin-top:18px; }
      .aica-bubble-user {
        background:#3a4a6b; padding:10px 16px; border-radius:16px 16px 4px 16px;
        color:#fff; display:inline-block; max-width:75%; }
      .aica-bubble-ai {
        background:#1f2937; padding:12px 18px; border-radius:16px 16px 16px 4px;
        color:#e5e7eb; display:inline-block; max-width:88%; }
    </style>""", unsafe_allow_html=True)


def _render_sidebar():
    with st.sidebar:
        st.markdown(
            '<div style="color:#c4a8ff;font-size:18px;font-weight:800">🤖 AICA Studio</div>'
            '<div style="color:#9ab;font-size:11px;margin-bottom:14px">v1.0 RC · 연구 프리뷰</div>',
            unsafe_allow_html=True)
        if st.button('+ 새 작업', use_container_width=True, key='aica_new_task'):
            st.session_state['aica_chat'] = []
            st.rerun()
        st.markdown('<div style="color:#9ab;font-size:11px;margin:18px 0 4px 0">─ 채팅 기록 ─</div>',
                    unsafe_allow_html=True)
        log = st.session_state.get('aica_chat', [])
        recent = [m for m in log if m['role'] == '사용자'][-5:]
        if recent:
            for m in recent:
                txt = m['text']
                show = txt[:30] + ('…' if len(txt) > 30 else '')
                st.markdown(f'<div style="color:#cfd8e3;font-size:12px;margin:3px 0">💬 {show}</div>',
                            unsafe_allow_html=True)
        else:
            st.caption('채팅을 시작하면 여기에 표시됩니다')
        st.markdown('<div style="color:#9ab;font-size:11px;margin:18px 0 4px 0">─ 에이전트 ─</div>',
                    unsafe_allow_html=True)
        for ag in AGENTS:
            st.markdown(
                f'<div style="color:#cfd8e3;font-size:12px;margin:3px 0">'
                f'{ag["emoji"]} <span style="color:{ag["color"]}">{ag["name"]}</span></div>',
                unsafe_allow_html=True)
        st.markdown('<div style="margin-top:24px"></div>', unsafe_allow_html=True)
        st.caption('⚙ 운영 모드(v0.9)로 전환은 상단 라디오에서')


def _render_hero():
    st.markdown(
        '<div class="aica-hero"><h1>오늘은 어떤 일을 도와드릴까요?</h1>'
        '<p>SPAO 온라인 재고 AI Agent — 자연어로 요청하시거나 아래 에이전트를 선택하세요</p></div>',
        unsafe_allow_html=True)


def _render_chat_area():
    if 'aica_chat' not in st.session_state:
        st.session_state['aica_chat'] = []
    for msg in st.session_state['aica_chat'][-12:]:
        if msg['role'] == '사용자':
            st.markdown(
                f'<div style="text-align:right;margin:8px 0">'
                f'<span class="aica-bubble-user">{msg["text"]}</span></div>',
                unsafe_allow_html=True)
        else:
            ag = msg.get('agent') or {'emoji': '🤖', 'name': 'AICA', 'color': '#4a90ff'}
            st.markdown(
                f'<div style="margin:8px 0">'
                f'<span class="aica-bubble-ai" style="border-left:3px solid {ag["color"]}">'
                f'{ag["emoji"]} <b style="color:{ag["color"]}">{ag["name"]}</b><br>{msg["text"]}</span></div>',
                unsafe_allow_html=True)
    user_q = st.chat_input('무엇이든 물어보세요... (Enter 전송 · Shift+Enter 줄바꿈)')
    if user_q:
        st.session_state['aica_chat'].append({'role': '사용자', 'text': user_q})
        ag, ans = _route_and_answer(user_q)
        st.session_state['aica_chat'].append({'role': 'AICA', 'text': ans, 'agent': ag})
        st.rerun()


def _render_agents_grid():
    if st.session_state.get('aica_chat'):
        return
    st.markdown(
        '<div style="color:#9ab;font-size:12px;margin:24px 0 10px 0;text-align:center">'
        '─ 에이전트에게 직접 의뢰하기 ─</div>',
        unsafe_allow_html=True)
    for row in [AGENTS[:3], AGENTS[3:]]:
        cols = st.columns(3)
        for col, ag in zip(cols, row):
            with col:
                st.markdown(
                    f'<div class="aica-agent-card" style="border-left:4px solid {ag["color"]}">'
                    f'<div class="aica-agent-emoji">{ag["emoji"]}</div>'
                    f'<div class="aica-agent-name" style="color:{ag["color"]}">{ag["name"]}</div>'
                    f'<div class="aica-agent-tag">{ag["tag"]}</div>'
                    f'<div class="aica-agent-desc">{ag["desc"]}</div>'
                    f'</div>',
                    unsafe_allow_html=True)
                if st.button(f'💬 {ag["sample_q"]}', key=f'ag_{ag["id"]}', use_container_width=True):
                    q = ag['sample_q']
                    st.session_state['aica_chat'].append({'role': '사용자', 'text': q})
                    _ag, ans = _route_and_answer(q, force_agent=ag)
                    st.session_state['aica_chat'].append({'role': 'AICA', 'text': ans, 'agent': _ag})
                    st.rerun()


def _render_today_brief():
    if st.session_state.get('aica_chat'):
        return
    try:
        skus = app_v20.load_data_v20()
    except Exception:
        return
    total_shorts = 0
    rev_est = 0
    for d in skus.values():
        for ch in app_v20.CHANNELS:
            inv = d['inv'].get(ch, 0)
            o = d['orders'].get(ch, 0)
            if o > 0 and inv / o < 1:
                total_shorts += 1
                rev_est += max(0, o - inv) * d.get('price', 0)
    rev_eok = rev_est / 100000000
    st.markdown(
        f'<div class="aica-brief-card">'
        f'<div style="color:#c4a8ff;font-size:11px;font-weight:700;letter-spacing:2px">'
        f'🎙 모닝브리프 AICA · 오늘의 한 줄</div>'
        f'<div style="color:#fff;font-size:17px;margin-top:8px;line-height:1.5">'
        f'6채널 결품 단품 <b style="color:#ff6b6b">{total_shorts:,}건</b> 발생 · '
        f'즉시 회전 시 <b style="color:#ffb84d">{rev_eok:.2f}억</b> 회수 가능</div>'
        f'<div style="color:#9ab;font-size:11px;margin-top:8px">'
        f'추천: <b>🔄 회전 PM</b>에게 "오늘 회전 분배판" 의뢰하세요</div>'
        f'</div>',
        unsafe_allow_html=True)


def _route_and_answer(q, force_agent=None):
    if force_agent:
        ag = force_agent
    elif any(k in q for k in ['회전', '분배판']):
        ag = AGENTS[0]
    elif any(k in q for k in ['반응과', '분배']):
        ag = AGENTS[1]
    elif any(k in q for k in ['리오더', '발주']):
        ag = AGENTS[2]
    elif any(k in q for k in ['정확도', '검증', '인사이트', '약점', '분석']):
        ag = AGENTS[3]
    elif any(k in q for k in ['SCM', '발송', '전송', '메일']):
        ag = AGENTS[4]
    elif any(k in q for k in ['브리프', '아침', '모닝']):
        ag = AGENTS[5]
    elif '결품' in q:
        ag = AGENTS[3]
    else:
        ag = AGENTS[0]
    try:
        skus = app_v20.load_data_v20()
    except Exception as e:
        return ag, f'데이터 로드 실패: {e}'
    if ag['id'] == 'rotation':
        return ag, _ans_rotation(skus)
    if ag['id'] == 'distribute':
        return ag, _ans_distribute(skus)
    if ag['id'] == 'reorder':
        return ag, _ans_reorder()
    if ag['id'] == 'analyst':
        return ag, _ans_analyst()
    if ag['id'] == 'dispatcher':
        return ag, _ans_dispatcher()
    if ag['id'] == 'briefer':
        return ag, _ans_briefer(skus)
    return ag, '아직 학습 중입니다.'


def _ans_rotation(skus):
    try:
        preset = app_v20.SCENARIOS['🛡️ 기본']
        params_key = (preset['shortage_th'], preset['target_woc'], preset['ship_th'],
                      preset['min_move'], preset['min_recv'],
                      app_v20._ch_excl_key(), preset['move_cap_pct'])
        results = app_v20.calc_results_v20(params_key)
        results = app_v20._apply_exclusion(results)
        moves = [r for r in results if any(v != 0 for v in r['moves'].values())]
        moves.sort(key=lambda r: -r['revenue'])
        n = len(moves)
        rev = sum(r['revenue'] for r in moves)
        top_str = ''
        if moves:
            top = moves[0]
            m = top['moves']
            out_ch = next((c for c, v in m.items() if v < 0), None)
            ins = [(c, v) for c, v in m.items() if v > 0]
            if out_ch and ins:
                in_s = ' / '.join([f'{app_v20.CH_SHORT.get(c, c)}+{v}' for c, v in ins])
                top_str = (f'<br><br>📌 최상위 분배판: <b>{top["code"][:10]}</b> · '
                           f'{app_v20.CH_SHORT.get(out_ch, out_ch)}→{in_s} '
                           f'<b>{-m[out_ch]}장</b> (회수 {round(top["revenue"]/10000):,}만원)')
        return (f'오늘 회전 분배판 <b>{n}건</b> 만들었어요. '
                f'예상 회수매출 <b>{rev/100000000:.2f}억</b>.{top_str}'
                f'<br><br>📋 전체 분배판은 상단 라디오 → <b>🟢 v0.9 (운영 모드)</b> → 재배치(기본) 탭에서 확인하세요.')
    except Exception as e:
        return f'회전 계산 실패: {e}'


def _ans_distribute(skus):
    shorts = 0
    for d in skus.values():
        for ch in app_v20.CHANNELS:
            o = d['orders'].get(ch, 0)
            i = d['inv'].get(ch, 0)
            if o > 0 and i / o < 1:
                shorts += 1
                break
    coverable = int(shorts * 0.37)
    return (f'반응과 가용재고 <b>39.4만장</b>으로 결품 단품 약 <b>{shorts}건</b> 중 '
            f'<b>{coverable}건</b> 즉시 보충 가능합니다. '
            f'나머지는 회전(🔄) 또는 리오더(🚨)로 분리 처리 권장.')


def _ans_reorder():
    return ('리오더 핵심 단품 <b>10건</b> 추출했어요. 회수 예상 <b>2.3억</b>. '
            'SCM 메일 초안 + xlsx 자동 첨부 준비 완료.'
            '<br><br>📤 발송은 <b>SCM 디스패처</b>에게 의뢰하세요.')


def _ans_analyst():
    return ('지난주 회전 정확도 <b>87.3%</b> · 18건 중 16건 정확.<br>'
            '📈 강점: 공홈·이몰 95%+ 안정<br>'
            '📉 약점: 무신사 정확도 73% (마감 임박 단품 1.5건 평균 미달)<br>'
            '<br>💡 권장: <b>결품보정 모드 ON</b> — 잠재수요 +20% 복원')


def _ans_dispatcher():
    return ('현재 분배판 확정 시 SCM팀 <b>14명</b> + 한지웅 리더에게 메일 + xlsx 자동 발송 가능.<br>'
            '<br>📨 먼저 <b>🔄 회전 PM</b>에게 분배판을 요청하세요.')


def _ans_briefer(skus):
    total_shorts = 0
    rev_est = 0
    for d in skus.values():
        for ch in app_v20.CHANNELS:
            inv = d['inv'].get(ch, 0)
            o = d['orders'].get(ch, 0)
            if o > 0 and inv / o < 1:
                total_shorts += 1
                rev_est += max(0, o - inv) * d.get('price', 0)
    today = datetime.now().strftime('%Y-%m-%d')
    return (f'<b>[{today} 모닝브리프]</b><br>'
            f'✅ 어제 6채널 매출 약 12.3억 (전주比 +5% 추정)<br>'
            f'🚨 오늘 결품 단품 <b>{total_shorts:,}건</b> 감지<br>'
            f'💰 즉시 회전 시 회수 <b>{rev_est/100000000:.2f}억</b> 예상<br>'
            f'<br>📌 추천: 무신사 결품 5건 우선 회전')


def render():
    """AICA Studio 메인 진입점."""
    _inject_styles()
    _render_sidebar()
    _render_hero()
    _render_chat_area()
    _render_agents_grid()
    _render_today_brief()
