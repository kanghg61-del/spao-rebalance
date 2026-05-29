# -*- coding: utf-8 -*-
"""
재배치 엔진 — 단품 1건에 대한 이동 수량 산출
보수 시나리오 기본값: 부족 임계 1주 / 목표 2주 / 출고율 90% / 온라인 10% / 10장 필터
"""
import math


def calc_rebalance(sku_data, params, channels, bw_name='반응과'):
    """
    Args:
        sku_data: dict
            'inv': {bw_name: int, 공홈: int, ...}
            'orders': {공홈: int, ...} (주간 주문량)
            'ship_rate': float (출고율, 0~1)
            'online_ratio': float (온라인 비중, 0~1)
            'locked' (optional): bool — 잠금 SKU
            'critical' (optional): bool — Critical SKU (10장 필터 면제)
        params: dict (config.yaml의 parameters)
        channels: list[str]
        bw_name: str (반응과 채널명)
    
    Returns:
        moves: dict {bw_name: int, 공홈: int, ...}
            양수 = 들어옴, 음수 = 나감, 합계 = 0
    """
    moves = {bw_name: 0}
    for c in channels:
        moves[c] = 0

    # 잠금 SKU는 이동 안 함
    if sku_data.get('locked', False):
        return moves

    ship = sku_data.get('ship_rate', 0)
    online = sku_data.get('online_ratio', 0)

    mode_A = ship >= params['ship_rate_threshold']
    mode_B = (not mode_A) and (online >= params['online_ratio_threshold'])
    if not (mode_A or mode_B):
        return moves

    inv_bw = sku_data['inv'].get(bw_name, 0)
    inv = {c: sku_data['inv'].get(c, 0) for c in channels}
    ord_ = {c: sku_data['orders'].get(c, 0) for c in channels}

    # 부족·잉여 채널 식별
    shortage, surplus = {}, {}
    for c in channels:
        i = max(0, inv[c])
        o = ord_[c]
        if o <= 0 and i <= 0:
            continue
        if o <= 0:
            if i > 0:
                surplus[c] = int(i)
            continue
        woc = i / o
        if woc <= params['shortage_threshold']:
            need = max(0, int(math.ceil((params['target_woc'] - woc) * o)))
            if need > 0:
                shortage[c] = need
        elif woc > params['target_woc']:
            avail = int((woc - params['target_woc']) * o)
            if avail > 0:
                surplus[c] = avail

    if not shortage:
        return moves

    total_short = sum(shortage.values())

    # 공급원 결정
    sources = {}
    if mode_A:
        sources = dict(surplus)
    else:  # mode_B
        if inv_bw > 0:
            sources[bw_name] = int(inv_bw)
        if sum(sources.values()) < total_short:
            for c, v in surplus.items():
                sources[c] = v

    total_src = sum(sources.values())
    if total_src == 0:
        return moves
    actual = min(total_short, total_src)

    # 공급원 차감 — 반응과 우선
    rem = actual
    if bw_name in sources:
        tk = min(sources[bw_name], rem)
        moves[bw_name] = -tk
        rem -= tk
        del sources[bw_name]
    if rem > 0 and sources:
        sa = sum(sources.values())
        items = list(sources.items())
        acc = 0
        for i, (c, av) in enumerate(items):
            if i == len(items) - 1:
                tk = rem - acc
            else:
                tk = min(av, int(round(av / sa * rem)))
            tk = max(0, min(tk, av))
            moves[c] = -tk
            acc += tk
            if acc >= rem:
                break

    # 부족 채널 분배
    out_total = -sum(moves.values())
    if out_total > 0:
        items = list(shortage.items())
        acc = 0
        for i, (c, nd) in enumerate(items):
            if i == len(items) - 1:
                gv = out_total - acc
            else:
                gv = int(round(nd / total_short * out_total))
                gv = max(0, min(gv, nd))
            moves[c] = gv
            acc += gv

    # 합계 0 보정
    diff = sum(moves.values())
    if diff != 0:
        for c in shortage:
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
        # 결품량 = max(0, 주문 - 재고)
        old_short = max(0, o - inv)
        new_short = max(0, o - new_inv)
        resolved = old_short - new_short
        revenue += resolved * price
    return int(revenue)
