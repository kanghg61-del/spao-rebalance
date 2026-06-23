# -*- coding: utf-8 -*-
"""AICA Studio (TEST) — 일일 브리핑 + 자연어 채팅.

실장 6/22 메일 컨셉: "대시보드가 아닌 AI 기반의 결과물".
귀여운 로봇 캐릭터가 매일 자동 브리핑 + 자연어 질의 응답.
"""
from datetime import datetime, timedelta
import re

import streamlit as st

import app_v20


def _inject_styles():
    st.markdown("""<style>
      .aica-hero { text-align:center; padding: 4px 0 0 0; }
      .aica-hero h1 { color:#fff; font-size: 32px; font-weight: 800; margin: 6px 0 0 0; }
      .aica-hero p { color:#9fb3d9; font-size: 14px; margin-top: 6px; }
      .aica-robot {
        display: inline-block; font-size: 96px; line-height: 1;
        filter: drop-shadow(0 4px 24px rgba(196,168,255,.35));
        animation: aicabob 2.4s ease-in-out infinite;
      }
      @keyframes aicabob {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-10px); }
      }
      .aica-brief {
        background: linear-gradient(135deg, #1a0d2e 0%, #0a2138 100%);
        border: 1px solid #5a3fb8; border-radius: 14px;
        padding: 22px 28px; margin-top: 18px;
        box-shadow: 0 0 30px rgba(90,63,184,.18);
      }
      .aica-brief-title {
        color: #c4a8ff; font-size: 13px; font-weight: 700; letter-spacing: 2px;
      }
      .aica-brief-body {
        color: #fff; font-size: 16px; line-height: 1.9; margin-top: 10px;
      }
      .aica-brief-body b { color: #ffb84d; font-weight: 800; }
      .aica-bubble-user {
        background:#3a4a6b; padding:10px 16px; border-radius:16px 16px 4px 16px;
        color:#fff; display:inline-block; max-width:75%;
      }
      .aica-bubble-ai {
        background:#1f2937; padding:12px 18px; border-radius:16px 16px 16px 4px;
        color:#e5e7eb; display:inline-block; max-width:88%; line-height:1.7;
      }
    </style>""", unsafe_allow_html=True)


def _render_hero():
    st.markdown(
        '<div class="aica-hero">'
        '<div class="aica-robot">🤖</div>'
        '<h1>오늘은 어떤 일을 도와드릴까요?</h1>'
        '<p>SPAO 온라인 재고 AICA — 자연어로 자유롭게 질문해보세요</p>'
        '</div>',
        unsafe_allow_html=True,
    )


def _compute_brief():
    """일일 브리핑 데이터 계산."""
    skus = app_v20.load_data_v20()
    smap = app_v20._load_style_map()
    daily_amt_total = 0.0
    ch_daily_amt = {c: 0.0 for c in app_v20.CHANNELS}
    style_qty = {}
    style_amt = {}
    style_name = {}
    short_cnt = 0
    for code, d in skus.items():
        price = d.get('price', 0)
        sty = code[:10]
        for c in app_v20.CHANNELS:
            o = d['orders'].get(c, 0)
            i = d['inv'].get(c, 0)
            amt = o * price
            ch_daily_amt[c] += amt / 7
            daily_amt_total += amt / 7
            if o > 0 and i / o < 1:
                short_cnt += 1
        tot_o = sum(d['orders'].get(c, 0) for c in app_v20.CHANNELS)
        if tot_o > 0:
            style_qty[sty] = style_qty.get(sty, 0) + tot_o
            style_amt[sty] = style_amt.get(sty, 0) + tot_o * price
            style_name[sty] = smap.get(sty, d.get('name', ''))
    top_10 = sorted(style_qty.items(), key=lambda x: -x[1])[:10]
    top_10_full = [(s, q // 7, style_name.get(s, '')) for s, q in top_10]
    preset = app_v20.SCENARIOS['🛡️ 기본']
    params_key = (preset['shortage_th'], preset['target_woc'], preset['ship_th'],
                  preset['min_move'], preset['min_recv'],
                  app_v20._ch_excl_key(), preset['move_cap_pct'])
    results = app_v20.calc_results_v20(params_key)
    results = app_v20._apply_exclusion(results)
    rotation_qty = sum(sum(v for v in r['moves'].values() if v > 0) for r in results)
    rotation_amt_sum = sum(r['revenue'] for r in results)
    dist_qty = 0
    dist_amt = 0
    for r in results:
        d = skus.get(r['code'])
        if not d:
            continue
        try:
            dist, _used = app_v20.calc_distribution(
                d, r['moves'], app_v20.CHANNELS,
                dist_target=preset['target_woc'], bw_name='반응과')
        except Exception:
            continue
        price = d.get('price', 0)
        for c, q in dist.items():
            if q > 0:
                dist_qty += q
                dist_amt += q * price
    return {
        'daily_amt_total': daily_amt_total,
        'ch_daily_amt': ch_daily_amt,
        'top_10': top_10_full,
        'short_cnt': short_cnt,
        'rotation_qty': rotation_qty,
        'rotation_amt_sum': rotation_amt_sum,
        'dist_qty': dist_qty,
        'dist_amt': dist_amt,
        'results': results,
        'skus': skus,
        'smap': smap,
        'style_qty': style_qty,
        'style_name': style_name,
    }


def _render_brief(K):
    today = datetime.now()
    yest = today - timedelta(days=1)
    yest_label = yest.strftime('%m/%d')
    daily_eok = K['daily_amt_total'] / 100000000
    daily_man_remainder = int((K['daily_amt_total'] % 100000000) / 10000)
    ch_strs = []
    for c in app_v20.CHANNELS:
        amt_man = int(K['ch_daily_amt'][c] / 10000)
        ch_strs.append(f"{app_v20.CH_SHORT.get(c, c)} <b>{amt_man:,}만원</b>")
    ch_html = ' / '.join(ch_strs)
    top_strs = []
    for i, (sty, dq, nm) in enumerate(K['top_10'], 1):
        nm_show = (nm or '')[:18]
        top_strs.append(f"{i}. <b>{sty}</b> {nm_show} — {dq:,}장")
    top_html = '<br>'.join(top_strs)
    rot_eok = K['rotation_amt_sum'] / 100000000
    dist_eok = K['dist_amt'] / 100000000
    not_covered = max(0, K['short_cnt'] - len([r for r in K['results'] if any(v > 0 for v in r['moves'].values())]))
    body = (
        f'<b>[전일 온라인 주문 기준 매출 보고]</b><br>'
        f'{yest_label}일 주문 기준 매출은 <b>{daily_eok:.2f}억 {daily_man_remainder:,}만원</b>입니다.<br>'
        f'채널별: {ch_html}<br><br>'
        f'<b>[전일 TOP 10 스타일]</b><br>'
        f'{top_html}<br><br>'
        f'<b>[회전·분배 추천]</b><br>'
        f'현재 6채널 결품 <b>{K["short_cnt"]:,}건</b> 발생하여 '
        f'총 회전량 <b>{K["rotation_qty"]:,}장 ({rot_eok:.2f}억)</b> 재배치 필요하며, '
        f'이동 시 기대매출은 <b>{rot_eok:.2f}억</b>입니다.<br>'
        f'회전으로 채우지 못하는 <b>{not_covered:,}건</b>에 대해서는 '
        f'반응과에서 <b>{K["dist_qty"]:,}장 ({dist_eok:.2f}억)</b> 필업 필요하며, '
        f'필업 시 기대매출은 <b>{dist_eok:.2f}억</b>입니다.'
    )
    st.markdown(
        f'<div class="aica-brief">'
        f'<div class="aica-brief-title">📡 AICA · DAILY BRIEFING</div>'
        f'<div class="aica-brief-body">{body}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_chat(K):
    if 'aica_chat' not in st.session_state:
        st.session_state['aica_chat'] = []
    for msg in st.session_state['aica_chat'][-12:]:
        if msg['role'] == 'user':
            st.markdown(
                f'<div style="text-align:right;margin:8px 0">'
                f'<span class="aica-bubble-user">{msg["text"]}</span></div>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div style="margin:8px 0">'
                f'<span class="aica-bubble-ai" style="border-left:3px solid #4a90ff">'
                f'🤖 <b style="color:#c4a8ff">AICA</b><br>{msg["text"]}</span></div>',
                unsafe_allow_html=True)
    user_q = st.chat_input('자유롭게 물어보세요 (예: 회전 TOP 5 스타일과 기대매출은?)')
    if user_q:
        st.session_state['aica_chat'].append({'role': 'user', 'text': user_q})
        ans = _answer(user_q, K)
        st.session_state['aica_chat'].append({'role': 'ai', 'text': ans})
        st.rerun()


def _answer(q, K):
    """동적 답변 — 키워드 + 숫자 매칭 + 실데이터 결합."""
    num_match = re.search(r'(\d+)\s*개|top\s*(\d+)|상위\s*(\d+)', q.lower())
    top_n = 5
    if num_match:
        for g in num_match.groups():
            if g:
                top_n = min(int(g), 30)
                break
    results = K['results']
    skus = K['skus']
    smap = K['smap']
    if (('회전' in q or '재배치' in q) and
            ('top' in q.lower() or '상위' in q or '필요' in q or '추천' in q or '큰' in q or '높' in q or '많' in q)):
        sty_rev = {}
        sty_qty = {}
        sty_nm = {}
        for r in results:
            sty = r['code'][:10]
            sty_rev[sty] = sty_rev.get(sty, 0) + r['revenue']
            sty_qty[sty] = sty_qty.get(sty, 0) + sum(v for v in r['moves'].values() if v > 0)
            sty_nm[sty] = smap.get(sty, r['data'].get('name', ''))
        top = sorted([(s, rev) for s, rev in sty_rev.items() if rev > 0],
                     key=lambda x: -x[1])[:top_n]
        if not top:
            return '회전 필요한 스타일이 없습니다 (안정 운영 중).'
        lines = [
            f'{i}. <b>{s}</b> {(sty_nm[s] or "")[:18]} — '
            f'이동 {sty_qty[s]:,}장 · 회수 <b style="color:#ffb84d">{round(sty_rev[s]/10000):,}만원</b>'
            for i, (s, _) in enumerate(top, 1)
        ]
        total_rev_eok = sum(rev for _, rev in top) / 100000000
        return (f'회전 필요 상위 <b>{top_n}개 스타일</b> (회수매출 기준):<br><br>' +
                '<br>'.join(lines) +
                f'<br><br>📊 상위 {top_n}개 합계 회수: <b style="color:#ffb84d">{total_rev_eok:.2f}억</b>')
    if (('top' in q.lower() or '상위' in q or '베스트' in q or 'best' in q.lower()) and
            ('스타일' in q or '판매' in q or '매출' in q)):
        top = K['top_10'][:top_n]
        if not top:
            return '데이터 없음'
        lines = [
            f'{i}. <b>{s}</b> {(nm or "")[:18]} — <b>{daily_q:,}장/일</b>'
            for i, (s, daily_q, nm) in enumerate(top, 1)
        ]
        return f'전일 매출 TOP {top_n} 스타일:<br><br>' + '<br>'.join(lines)
    for c in app_v20.CHANNELS:
        short = app_v20.CH_SHORT.get(c, c)
        if (c in q or short in q) and '결품' in q:
            shorts = []
            for code, d in skus.items():
                o = d['orders'].get(c, 0)
                i = d['inv'].get(c, 0)
                if o > 0 and i / o < 1:
                    sty = code[:10]
                    shorts.append((code, sty, i, o, i / o, smap.get(sty, '')))
            shorts.sort(key=lambda x: x[4])
            top_s = shorts[:top_n]
            if not top_s:
                return f'<b>{short}</b> 채널 결품 단품 없음 (모두 ≥ 1주).'
            lines = [
                f'{i}. <b>{c0}</b> {(nm or "")[:14]} — 재고 {inv:,} · 주판 {o:,} · '
                f'<b style="color:#ff6b6b">{w:.1f}주</b>'
                for i, (c0, s0, inv, o, w, nm) in enumerate(top_s, 1)
            ]
            return f'<b>{short}</b> 채널 결품 상위 {top_n}건:<br><br>' + '<br>'.join(lines)
    if any(k in q for k in ['기대매출', '회수', '효과', '얼마']) and '회전' in q:
        return (f'회전 즉시 실행 시 예상 회수매출: '
                f'<b style="color:#ffb84d">{K["rotation_amt_sum"]/100000000:.2f}억</b><br>'
                f'(총 이동량 {K["rotation_qty"]:,}장, 결품해소 회수매출 기준)')
    if any(k in q for k in ['반응과', '분배', '필업']):
        return (f'반응과에서 채널 결품 보충 추천: '
                f'<b>{K["dist_qty"]:,}장 · {K["dist_amt"]/100000000:.2f}억</b><br>'
                f'(회전으로 못 메우는 결품을 반응과 가용재고로 보충)')
    if '결품' in q:
        return (f'현재 6채널 결품 단품: <b style="color:#ff6b6b">{K["short_cnt"]:,}건</b><br>'
                f'채널명 지정하시면 상위 결품을 보여드릴게요. (예: "무신 결품 5건")')
    if any(k in q for k in ['매출', '주문', '전일', '어제', '오늘']):
        ch_strs = [f'{app_v20.CH_SHORT.get(c, c)} {int(K["ch_daily_amt"][c]/10000):,}만원'
                   for c in app_v20.CHANNELS]
        return (f'전일 주문 기준 매출: <b>{K["daily_amt_total"]/100000000:.2f}억</b><br>'
                f'채널별: {" / ".join(ch_strs)}')
    if '회전' in q or '재배치' in q:
        return (f'회전 추천 총량: <b>{K["rotation_qty"]:,}장 · '
                f'{K["rotation_amt_sum"]/100000000:.2f}억</b><br>'
                f'상위 5개 스타일 보시려면 "회전 TOP 5 스타일"로 물어봐주세요.')
    return (
        '도움말 — 다음 패턴으로 물어봐주세요:<br><br>'
        '• <b>"회전 TOP 5 스타일"</b> · 회전 필요 상위 N개 스타일 + 기대매출<br>'
        '• <b>"전일 TOP 10 스타일"</b> · 전일 매출 베스트 스타일<br>'
        '• <b>"공홈 결품 5건"</b> · 채널별 결품 상위 N건<br>'
        '• <b>"회전 기대매출"</b> · 회전 시 예상 회수매출<br>'
        '• <b>"반응과 분배"</b> · 반응과 분배 추천<br>'
        '• <b>"전일 매출"</b> · 채널별 전일 매출 요약'
    )


def render():
    """AICA Studio (TEST) — 일일 브리핑 + 자연어 채팅."""
    _inject_styles()
    _render_hero()
    try:
        K = _compute_brief()
    except Exception as e:
        st.error(f'데이터 로드 실패: {e}')
        return
    _render_brief(K)
    st.markdown('---')
    _render_chat(K)
