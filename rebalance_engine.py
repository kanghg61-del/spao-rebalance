# -*- coding: utf-8 -*-
"""
재배치 엔진 v2.9 — 단품 1건에 대한 채널 간 이동 수량 산출

v2.9 변경 (분배 로직 개선):
  [개선1] 무의미 소량 이동 제거 — 한정 공급량을 비례 배분하지 않고, 결품을
          '실제로 해소(≥결품해소선)'할 수 있는 채널에 우선순위대로 몰아준다.
          이동해도 여전히 결품인 채널(예: 이랜드몰·카카오에 몇 장만)은 제외.
          → 같은 컬러(단품코드 12자리) 내 사이즈들이 찔끔 흩어지는 아소트 깨짐 방지.
  [개선2] 수신 채널 우선순위(동률 tie-break) — 저수수료 채널 우선:
          공홈 > 네이버 > 이랜드몰 > 무신사 > 카카오선물하기 > 지그재그
          IN(받는 채널)은 이 순서로 채우고, OUT(빼는 채널)은 역순(고수수료)부터 회수.

기존 유지:
  · 출고율 임계 미만 단품 제외 / 외부창고(AENS·ADU3·ADQS) OUT 제외 / 합계 0 / 비부가 필터
"""
import math

# 수신(IN) 우선순위 — 숫자 낮을수록 우선(저수수료). OUT은 역순(고수수료부터 회수).
CHANNEL_PRIORITY = {
    '공홈': 0, '네이버': 1, '이랜드몰': 2, '무신사': 3, '카카오선물하기': 4, '지그재그': 5,
}
# 결품 해소선(주) — 이 미만이면 '여전히 결품'으로 보고 소량 이동을 만들지 않음
RESOLVE_WOC = 1.0


def _prio(c):
    return CHANNEL_PRIORITY.get(c, 99)


def style_color(code):
    """컬러 단위 키 = 단품코드 앞 12자리 (예: SPPPG25U0525). 아소트(사이즈 구색) 그룹."""
    return (code or '')[:12]


def calc_rebalance(sku_data, params, channels):
    """
    Returns: moves dict {채널: int} — 양수 IN / 음수 OUT / 합계 0
    """
    moves = {c: 0 for c in channels}

    if sku_data.get('locked', False):
        return moves
    if sku_data.get('ship_rate', 0) < params['ship_rate_threshold']:
        return moves

    inv = {c: sku_data['inv'].get(c, 0) for c in channels}
    ord_ = {c: sku_data['orders'].get(c, 0) for c in channels}
    ext_wh = sku_data.get('ext_wh', {})

    def movable(c):
        """OUT 가용 재고 = 채널 재고 - 외부창고 보관분"""
        return max(0, inv[c] - ext_wh.get(c, 0))

    target = params['target_woc']
    short_th = params['shortage_threshold']
    resolve_line = min(RESOLVE_WOC, target)  # 결품 해소선

    # ── 부족·잉여 채널 식별 ──
    # shortage[c] = (need_resolve, need_full): 결품 해소까지 / 목표까지 필요량
    shortage, surplus = {}, {}
    for c in channels:
        i = inv[c]                      # 실재고(음수 가능) — 음수재고도 메워야 실제 결품 해소
        o = ord_[c]
        if o <= 0 and i <= 0:
            continue
        if o <= 0:
            m = movable(c)
            if m > 0:
                surplus[c] = int(m)
            continue
        woc = i / o
        if woc <= short_th:
            # 목표/해소까지 필요량 = 목표재고수량 - 현재 실재고 (음수재고분 포함)
            need_full = max(0, int(math.ceil(target * o - i)))
            need_resolve = max(0, int(math.ceil(resolve_line * o - i)))
            if need_full > 0:
                shortage[c] = (need_resolve, need_full)
        elif woc > target:
            avail = int((woc - target) * o)
            avail = min(avail, movable(c))
            if avail > 0:
                surplus[c] = avail

    if not shortage or not surplus:
        return moves

    total_src = sum(surplus.values())
    supply = min(total_src, sum(nf for _, nf in shortage.values()))
    if supply <= 0:
        return moves

    # ── IN 배분: 우선순위 그리디 (결품 해소 집중 + 무의미 이동 제외) ──
    give = {c: 0 for c in shortage}
    order = sorted(shortage.keys(), key=_prio)  # 저수수료 우선

    # Pass 1: 결품 해소선까지 — '해소 가능한' 채널만 채운다(불가하면 0으로 건너뜀)
    rem = supply
    for c in order:
        need_resolve, _ = shortage[c]
        nr = max(need_resolve, 1)  # 최소 1장은 있어야 의미
        if rem >= nr:
            give[c] = nr
            rem -= nr
        # rem < 필요량이면 이 채널은 건너뜀 → 다음(차순위) 채널 해소에 집중

    # Pass 2: 남은 물량으로 이미 해소된 채널을 목표까지 보충 (우선순위 순)
    for c in order:
        if rem <= 0:
            break
        if give[c] <= 0:
            continue  # Pass1에서 해소 못 한 채널은 보충 안 함(소량 이동 방지)
        _, need_full = shortage[c]
        topup = min(need_full - give[c], rem)
        if topup > 0:
            give[c] += topup
            rem -= topup

    in_total = sum(give.values())
    if in_total <= 0:
        return moves
    for c, g in give.items():
        moves[c] = g

    # ── OUT 회수: 고수수료(역순)부터 잉여 차감, 합계 = in_total ──
    need_out = in_total
    for c in sorted(surplus.keys(), key=lambda x: -_prio(x)):  # 지그재그→…→공홈
        if need_out <= 0:
            break
        tk = min(surplus[c], need_out)
        moves[c] = -tk
        need_out -= tk

    # 합계 0 보정 (정수 반올림 잔차)
    diff = sum(moves.values())
    if diff != 0:
        for c in order:  # 최우선 수신 채널에서 잔차 흡수
            if moves[c] - diff >= 0:
                moves[c] -= diff
                break

    # 비부가 필터 — Critical SKU는 면제
    pos = sum(v for v in moves.values() if v > 0)
    if pos < params['min_move_qty'] and not sku_data.get('critical', False):
        for k in moves:
            moves[k] = 0

    return moves


def calc_after_woc(sku_data, moves, channels):
    """이동 후 채널별 재고주수"""
    result = {}
    for c in channels:
        new_inv = sku_data['inv'].get(c, 0) + moves.get(c, 0)
        o = sku_data['orders'].get(c, 0)
        result[c] = round(new_inv / o, 1) if o > 0 else None
    return result


def calc_expected_revenue(sku_data, moves, channels, price):
    """기대효과 = 해소된 결품량 × 정상가 (보수 추정)"""
    revenue = 0
    for c in channels:
        inv = sku_data['inv'].get(c, 0)
        o = sku_data['orders'].get(c, 0)
        new_inv = inv + moves.get(c, 0)
        old_short = max(0, o - inv)
        new_short = max(0, o - new_inv)
        revenue += (old_short - new_short) * price
    return int(revenue)
