# -*- coding: utf-8 -*-
"""
AI 1.0 분석 엔진 (테스트) — 결품 위험 확률 + 추천 사유 자연어 생성

구성 (정직성 라벨: 통계 확률모형 + 규칙기반 설명 생성. ML 학습 모델은 AI 1.5에서 도입):
  · 결품 위험 스코어 — 주간 주문량을 포아송 수요로 보고
    P(7일 수요 > 현재고) = 결품 확률을 단품×채널 단위로 산출.
  · 예상 결품 시점 — 현재고 ÷ 일평균 수요 (영업일 기준 D+n).
  · 위험 노출 매출 — 7일 기대 수요 중 현재고로 못 받는 분량 × 정상가.
  · XAI 설명문 — 각 권고 행에 대해 '왜 이 이동인지'를 사람이 읽는 문장으로 생성.

v5.6 엔진(rebalance_engine)은 건드리지 않고 그 산출(moves)을 입력으로만 사용한다.
"""
import math

# 채널별 수수료율 (2026-06-05 실장 확정치) — 설명문 근거용
FEE_RATE = {
    '공홈': 2.0, '네이버': 5.6, '이랜드몰': 10.0,
    '카카오선물하기': 13.2, '지그재그': 16.0, '무신사': 18.0,
}

# 위험 등급 컷 (7일 내 결품 확률)
GRADE_CUTS = [
    (0.80, '🔴 긴급'),
    (0.50, '🟠 경계'),
    (0.20, '🟡 관찰'),
    (0.00, '🟢 안정'),
]


def poisson_sf(k: int, lam: float) -> float:
    """P(X > k), X ~ Poisson(lam). lam>30은 정규근사(연속성 보정)."""
    if lam <= 0:
        return 0.0
    if k < 0:
        return 1.0
    if lam > 30:
        z = (k + 0.5 - lam) / math.sqrt(lam)
        return 0.5 * math.erfc(z / math.sqrt(2.0))
    term = math.exp(-lam)
    cdf = term
    for i in range(1, k + 1):
        term *= lam / i
        cdf += term
        if term < 1e-15 and i > lam:
            break
    return max(0.0, min(1.0, 1.0 - cdf))


def grade_of(p: float) -> str:
    for cut, g in GRADE_CUTS:
        if p >= cut:
            return g
    return GRADE_CUTS[-1][1]


def confidence_of(weekly_orders: float) -> str:
    """예측 신뢰도 — 수요 표본 크기 기반 (정직한 단순 기준)."""
    if weekly_orders >= 30:
        return '높음'
    if weekly_orders >= 10:
        return '중간'
    return '낮음'


def risk_bar(p: float, width: int = 10) -> str:
    """확률 시각 막대 (유니코드) — 기존 대시보드 데이터바 스타일과 통일."""
    fill = int(round(p * width))
    return '█' * fill + '░' * (width - fill)


def sku_channel_risks(skus: dict, channels: list) -> list:
    """단품×채널 결품 위험 행 산출. 주문>0 채널만.

    Returns: list[dict] — code/name/price/rank/channel/inv/ord/woc/p7/grade/
                          d_day/loss_week/conf
    """
    rows = []
    for code, d in skus.items():
        inv = d['inv']
        for c in channels:
            o = d['orders'].get(c, 0)
            if o <= 0:
                continue
            i = max(0, inv.get(c, 0))
            p7 = poisson_sf(i, float(o))          # 7일(=1주) 수요 > 현재고
            lam_d = o / 7.0
            d_day = (i / lam_d) if lam_d > 0 else None
            loss_units = max(0, o - i)            # 7일 기대 수요 중 미충족분
            rows.append({
                'code': code,
                'name': d.get('name', ''),
                'price': d.get('price', 0),
                'rank': d.get('rank_online', 9999),
                'channel': c,
                'inv': i,
                'ord': o,
                'woc': round(i / o, 1),
                'p7': p7,
                'grade': grade_of(p7),
                'd_day': round(d_day, 1) if d_day is not None else None,
                'loss_week': loss_units * d.get('price', 0),
                'conf': confidence_of(o),
            })
    rows.sort(key=lambda r: (-r['p7'], -r['loss_week']))
    return rows


def _woc_str(i: int, o: int) -> str:
    return f'{i / o:.1f}주' if o > 0 else '수요 없음'


def explain_move(code: str, d: dict, moves: dict, revenue: int,
                 channels: list) -> str:
    """권고 1건(단품)의 이동 사유를 자연어로 생성 — XAI 설명문."""
    inv, ordd = d['inv'], d['orders']
    ext = d.get('ext_wh', {})
    ins = [(c, v) for c, v in moves.items() if v > 0]
    outs = [(c, -v) for c, v in moves.items() if v < 0]
    if not ins:
        return ('현재 기준 이동 권고가 없습니다. 결품 위험 채널이 없거나, '
                '잉여 재고가 외부창고 보관분·이동 상한(50%)에 묶여 가용 공급이 없는 경우입니다.')

    parts = []
    # ① 결품 측 진단
    for c, v in ins:
        i, o = max(0, inv.get(c, 0)), ordd.get(c, 0)
        p7 = poisson_sf(i, float(o)) if o > 0 else 0.0
        d_day = (i / (o / 7.0)) if o > 0 else None
        eta = f'약 D+{d_day:.0f}일' if d_day is not None and d_day <= 14 else '2주 이후'
        parts.append(
            f'**{c}**은(는) 현재고 {i:,}장 · 주간 수요 {o:,}장(재고 {_woc_str(i, o)})으로 '
            f'7일 내 결품 확률 **{p7 * 100:.0f}%**, 예상 결품 시점 {eta}입니다.'
        )
    # ② 공급 측 진단
    if outs:
        srcs = []
        for c, v in outs:
            i, o = inv.get(c, 0), ordd.get(c, 0)
            w = _woc_str(i, o)
            x = ext.get(c, 0)
            srcs.append(f'{c}(재고 {i:,}장·{w}' + (f', 외부창고 {x:,}장 이동 불가 제외' if x else '') + ')')
        parts.append('잉여는 ' + ' · '.join(srcs) + ' 에서 회수합니다.')
    # ③ 권고 + 근거
    mv_txt = ' / '.join(f'{c} **+{v:,}장**' for c, v in ins)
    parts.append(f'AI 권고: {mv_txt} — 기대 회수 매출 **주 {revenue / 10000:,.0f}만원** (정상가 {d.get("price", 0):,}원 기준).')
    # ④ 수수료 관점
    top_in = min(ins, key=lambda x: FEE_RATE.get(x[0], 99))[0]
    if outs:
        top_out = max(outs, key=lambda x: FEE_RATE.get(x[0], 0))[0]
        gap = FEE_RATE.get(top_out, 0) - FEE_RATE.get(top_in, 0)
        if gap > 0:
            parts.append(
                f'수수료 관점에서도 {top_out}({FEE_RATE.get(top_out)}%) → '
                f'{top_in}({FEE_RATE.get(top_in)}%) 이동은 마진 {gap:.1f}%p 개선 방향입니다.'
            )
    # ⑤ 안전장치 고지
    parts.append('적용 안전장치: 외부창고(AENS·ADU3·ADQS) 반출 제외 · 채널별 1일 반출 상한 50% · 사이즈 내 이동(구색 보호).')
    return '\n\n'.join(parts)


def daily_briefing(risk_rows: list, total_in: int, total_rev: int,
                   moved_cnt: int, asof: str) -> str:
    """🤖 오늘의 AI 브리핑 — 위험 현황 + 권고 요약 문단 생성."""
    n_crit = sum(1 for r in risk_rows if r['p7'] >= 0.8)
    n_warn = sum(1 for r in risk_rows if 0.5 <= r['p7'] < 0.8)
    exposure = sum(r['loss_week'] for r in risk_rows if r['p7'] >= 0.5)
    top = risk_rows[:3]
    top_txt = ' · '.join(
        f'{t["name"][:14]}({t["channel"]}, {t["p7"] * 100:.0f}%)' for t in top
    ) if top else '없음'
    return (
        f'{asof} 기준 6채널 전수 스캔 결과, 7일 내 결품 확률 80% 이상 **긴급 {n_crit:,}건**, '
        f'50~80% **경계 {n_warn:,}건**을 탐지했습니다. 위험 노출 매출(미조치 시 주간 손실 추정)은 '
        f'**{exposure / 100000000:.2f}억 원**입니다. 최상위 위험은 {top_txt} 입니다.\n\n'
        f'재배치 엔진은 **{moved_cnt:,}개 단품 · {total_in:,}장** 이동을 권고하며, 실행 시 '
        f'**주 {total_rev / 100000000:.2f}억 원** 회수가 기대됩니다. 외부창고·이동상한·구색 보호 '
        f'안전장치가 적용된 권고이며, 승인 전 아래 위험 레이더와 단품별 AI 사유를 확인하세요.'
    )
