# -*- coding: utf-8 -*-
"""
대화형 AICA — 규칙기반 Q&A 엔진 (AI 1.0 테스트)

정직성 라벨: 인텐트 패턴 매칭 + v5.6 엔진 데이터 기반 답변 생성 (LLM 미사용).
LLM(자연어 자유 질의) 전환은 자동화 단계에서 보안 검토 후 도입.

ctx (render 쪽에서 준비):
  skus       — {code: {name, price, rank_online, inv{}, orders{}, ext_wh{}}}
  risk_rows  — ai_insight.sku_channel_risks 결과 (확률 내림차순)
  moved      — 이동 권고 결과 [{code, data, moves, revenue}] (회수 내림차순)
  channels   — 채널 리스트
  asof       — 기준 시각 문자열
  total_in / total_rev — 권고 합계
"""
import re

import ai_insight

CH_ALIAS = {
    '공홈': '공홈', '공식몰': '공홈', '자사몰': '공홈',
    '무신사': '무신사', '무신': '무신사',
    '지그재그': '지그재그', '지그': '지그재그', '지재': '지그재그',
    '네이버': '네이버', '네이': '네이버',
    '이랜드몰': '이랜드몰', '이몰': '이랜드몰',
    '카카오': '카카오선물하기', '카카오선물하기': '카카오선물하기',
}

HELP = (
    '이런 걸 물어보실 수 있어요:\n\n'
    '- **"오늘 요약"** / "브리핑" — 오늘의 위험·권고 요약\n'
    '- **"가장 급한 거 5개"** — 결품 임박 단품 Top N\n'
    '- **"윈드브레이커 왜 결품이야?"** — 단품명/단품코드로 진단 + 이동 권고 사유\n'
    '- **"지그재그 상황 어때?"** — 채널별 위험·이동 요약\n'
    '- **"효과 얼마야?"** — 권고 실행 시 기대 회수 매출\n\n'
    'ⓘ AI 1.0 채팅은 규칙기반(패턴 매칭)입니다. 자유 문장 이해(LLM)는 자동화 단계 도입 예정.'
)


def _fmt_uk(won):
    if won >= 100000000:
        return f'{won / 100000000:.2f}억 원'
    return f'{won / 10000:,.0f}만 원'


def _find_sku(query, skus):
    """단품코드 직접 매칭 → 단품명 키워드 매칭 (매출순 상위 우선)."""
    m = re.search(r'[A-Z]{2,5}[A-Z0-9]{8,}', query.upper())
    if m:
        key = m.group(0)
        hits = [c for c in skus if c.startswith(key)]
        if hits:
            return sorted(hits, key=lambda c: skus[c].get('rank_online', 9999))[:1]
    # 단품명 키워드 — 실제 단품명에 존재하는 토큰만 추려, 전체 토큰 일치 우선
    raw = re.findall(r'[가-힣A-Za-z]+', query)
    tokens = [t for t in raw
              if t not in ('결품', '재고', '이유', '상황', '권고', '이동', '단품', '채널')
              and any(t in d.get('name', '') for d in skus.values())]
    if not tokens:
        return []
    hits = [c for c, d in skus.items() if all(t in d.get('name', '') for t in tokens)]
    if not hits:  # 전체 일치 없으면 최다 토큰 일치
        scored = [(sum(t in d.get('name', '') for t in tokens), c) for c, d in skus.items()]
        mx = max(s for s, _ in scored)
        hits = [c for s, c in scored if s == mx and s > 0]
    return sorted(hits, key=lambda c: skus[c].get('rank_online', 9999))[:1]


def _sku_answer(code, ctx):
    skus, channels = ctx['skus'], ctx['channels']
    d = skus[code]
    lines = [f"**{d.get('name', code)}** (`{code}` · 정상가 {d.get('price', 0):,}원 · 온라인 {d.get('rank_online', '?')}위) 진단입니다.\n"]
    for c in channels:
        i, o = max(0, d['inv'].get(c, 0)), d['orders'].get(c, 0)
        if i == 0 and o == 0:
            continue
        p7 = ai_insight.poisson_sf(i, float(o)) if o > 0 else 0.0
        woc = f'{i / o:.1f}주' if o > 0 else '수요 없음'
        flag = ' 🔴' if p7 >= 0.8 else (' 🟠' if p7 >= 0.5 else '')
        lines.append(f'- {c}: 재고 {i:,}장 / 주간수요 {o:,}장 ({woc}) — 7일 결품확률 {p7 * 100:.0f}%{flag}')
    mv = next((r for r in ctx['moved'] if r['code'] == code), None)
    if mv:
        lines.append('')
        lines.append(ai_insight.explain_move(code, mv['data'], mv['moves'], mv['revenue'], channels))
    else:
        lines.append('\n현재 이 단품에 대한 이동 권고는 없습니다 (결품 위험 채널 없음 또는 가용 공급 부족).')
    return '\n'.join(lines)


def _top_risk(ctx, n):
    rows = ctx['risk_rows'][:n]
    out = [f'지금 가장 급한 단품×채널 **Top {len(rows)}** (7일 내 결품 확률 순):\n']
    for i, r in enumerate(rows, 1):
        eta = f"D+{r['d_day']:.0f}일" if r['d_day'] is not None and r['d_day'] <= 14 else '2주 이후'
        out.append(f"{i}. {r['grade']} **{r['name'][:18]}** ({r['channel']}) — 확률 {r['p7'] * 100:.0f}% · "
                   f"재고 {r['inv']:,}/수요 {r['ord']:,} · 예상 결품 {eta} · 노출 {r['loss_week'] / 10000:,.0f}만/주")
    out.append('\n해당 단품을 채팅에 입력하면 이동 권고 사유까지 설명해 드립니다.')
    return '\n'.join(out)


def _channel_answer(ch, ctx):
    rows = [r for r in ctx['risk_rows'] if r['channel'] == ch]
    n_crit = sum(1 for r in rows if r['p7'] >= 0.8)
    n_warn = sum(1 for r in rows if 0.5 <= r['p7'] < 0.8)
    expo = sum(r['loss_week'] for r in rows if r['p7'] >= 0.5)
    t_in = sum(r['moves'].get(ch, 0) for r in ctx['moved'] if r['moves'].get(ch, 0) > 0)
    t_out = -sum(r['moves'].get(ch, 0) for r in ctx['moved'] if r['moves'].get(ch, 0) < 0)
    fee = ai_insight.FEE_RATE.get(ch)
    top = rows[:3]
    out = [f'**{ch}** 현황 ({ctx["asof"]} 기준 · 수수료 {fee}%):\n',
           f'- 결품 위험: 🔴 긴급 {n_crit:,}건 · 🟠 경계 {n_warn:,}건 · 위험 노출 {_fmt_uk(expo)}/주',
           f'- AI 권고 이동: IN +{t_in:,}장 / OUT −{t_out:,}장']
    if top:
        out.append('- 최상위 위험: ' + ' · '.join(f"{t['name'][:12]}({t['p7'] * 100:.0f}%)" for t in top))
    return '\n'.join(out)


def _kpi_answer(ctx):
    return (f"현재 권고를 전량 실행하면 **주 {_fmt_uk(ctx['total_rev'])}** 회수가 기대됩니다 "
            f"(연 환산 약 {ctx['total_rev'] * 52 / 100000000:.0f}억 원).\n\n"
            f"- 이동 권고: {len(ctx['moved']):,}개 단품 · {ctx['total_in']:,}장\n"
            f"- 위험 노출(미조치 시): 주 {_fmt_uk(sum(r['loss_week'] for r in ctx['risk_rows'] if r['p7'] >= 0.5))}\n"
            f"- 안전장치: 외부창고 반출 제외 · 1일 반출 상한 50% · 구색 보호 적용 후 수치입니다.")


def answer(query, ctx):
    q = query.strip()
    if not q:
        return HELP
    # ① 채널 질의
    for alias, ch in CH_ALIAS.items():
        if alias in q and not _find_sku(q, ctx['skus']):
            return _channel_answer(ch, ctx)
    # ② 단품 질의 (코드/단품명)
    hits = _find_sku(q, ctx['skus'])
    if hits:
        return _sku_answer(hits[0], ctx)
    # ③ 긴급 Top N
    if any(k in q for k in ('급한', '긴급', '위험', '임박', '결품')):
        m = re.search(r'(\d+)\s*개', q)
        return _top_risk(ctx, int(m.group(1)) if m else 5)
    # ④ 요약/브리핑
    if any(k in q for k in ('요약', '브리핑', '오늘', '현황', '상황')):
        return ai_insight.daily_briefing(ctx['risk_rows'], ctx['total_in'],
                                         ctx['total_rev'], len(ctx['moved']), ctx['asof'])
    # ⑤ 효과/회수
    if any(k in q for k in ('효과', '회수', '얼마', '매출', '기대')):
        return _kpi_answer(ctx)
    return '질문을 이해하지 못했어요. 🙏\n\n' + HELP
