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
# 컬러(12자리) 커버리지 임계 — 이 컬러 결품 사이즈의 이 비율 이상을 해소 못 하는 채널은
# 수신처에서 제외(아소트 깨짐 방지). 단일 결품 사이즈는 항상 통과.
COLOR_COVERAGE_TH = 0.6
# 소액 채널 수신 제외 — 주간 주문이 이 미만인 채널은 결품이라도 IN(보충) 대상에서 제외
# (잉여일 때 빼주는 것은 허용). 사용자 정의 탭에서 조정.
MIN_RECV_ORDER = 4


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
    # 출고율 게이트 제거(v4.3) — 출고율과 무관하게 결품(재고주수 부족) 발생 시 즉시 보충.
    # (과거: ship_rate < threshold 인 단품은 이동 대상에서 제외했으나, 결품은 출고율과
    #  무관하게 채워야 하므로 게이트를 폐지함.)

    inv = {c: sku_data['inv'].get(c, 0) for c in channels}
    ord_ = {c: sku_data['orders'].get(c, 0) for c in channels}
    ext_wh = sku_data.get('ext_wh', {})

    cap_pct = params.get('move_cap_pct', 0.5)

    def movable(c):
        """OUT 가용 재고 = min(채널 재고 - 외부창고 보관분, 현재고 cap_pct 상한)"""
        base = max(0, inv[c] - ext_wh.get(c, 0))
        cap = int(math.floor(cap_pct * inv[c])) if inv[c] > 0 else 0
        return min(base, cap)

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



def calc_rebalance_group(group, params, channels):
    """
    컬러(단품코드 12자리) 단위 재배치 (v4.7) — 같은 컬러의 사이즈들을 함께 본다.
      · 마이너 채널 제외 — 그룹 내 '수요 사이즈 수'가 최다 채널의 50% 미만인 채널은
        해당 스타일에서 다수 결품(구색 미보유)으로 보고 수신 대상에서 제외한다.
        (예: 이랜드몰이 한 스타일에서 1개 사이즈만 팔리면, 거기에 소량 채우는 대신
         재고가 더 급한 정상 채널로 돌리거나, 갈 곳 없으면 이동하지 않는다.)
      · 수신 우선순위 — 1순위 재고주수(낮을수록 결품 심함), 2순위 저수수료.
      · 이동은 사이즈 내에서만(아소트 보호), 외부창고 OUT 제외, 사이즈별 합계 0.

    Args:
        group: {단품코드: sku_data}  (같은 컬러의 사이즈들)
        params, channels: calc_rebalance와 동일
    Returns:
        {단품코드: moves dict}  — 각 사이즈별 채널 이동(양수 IN/음수 OUT/합계 0)
    """
    out = {code: {c: 0 for c in channels} for code in group}

    short_th = params['shortage_threshold']
    target = params['target_woc']

    # ── 채널별 IN/OUT 제외 (채널 MD 직접 관리) — 코드 부분일치 ──
    ch_excl = params.get('ch_excl', {})

    def _x(code, c, direction):
        # 7/13 사용자 정책: 이랜드몰은 신상(G코드) IN 안 받음 (재배치 회전 대상 제외)
        if c == '이랜드몰' and direction == 'in' and len(code) >= 5 and code[4].upper() == 'G':
            return True
        pats = ch_excl.get(c, {}).get(direction)
        return bool(pats) and any(p and p in code for p in pats)

    # ── 이동(OUT) 상한 — 하루에 각 채널 현재고의 cap_pct까지만 반출 가능 (기본 50%) ──
    cap_pct = params.get('move_cap_pct', 0.5)

    def _cap(i):
        return int(math.floor(cap_pct * i)) if i > 0 else 0

    # ── 사이즈(SKU)별 결품/잉여 산출 ──
    shortage = {}      # code -> {ch: need_full}
    surplus_left = {}  # code -> {ch: avail}  (사이즈 내에서만 이동 가능)
    for code, d in group.items():
        # 출고율 게이트 제거(v4.3) — locked(제외 스타일)만 건너뛰고, 출고율과 무관하게
        # 결품 발생 시 보충 대상에 포함한다.
        if d.get('locked', False):
            shortage[code] = {}; surplus_left[code] = {}
            continue
        inv = d['inv']; ordd = d['orders']; ext = d.get('ext_wh', {})
        sh, su = {}, {}
        for c in channels:
            i = inv.get(c, 0); o = ordd.get(c, 0)
            if o <= 0 and i <= 0:
                continue
            # 사용자 7/8: 이동 가능한 재고는 EHUB(내부재고)만 — 외부창고(EDW 위탁창고)는 제외
            # 총재고 i는 WOC/결품 판정에 사용 (전체 재고 감안), 실제 OUT 상한은 내부재고 기준
            i_internal = max(0, i - ext.get(c, 0))
            if o <= 0:
                # 주문 없음 → 잉여 (EHUB 재고의 cap_pct 상한)
                m = min(i_internal, _cap(i_internal))
                if m > 0 and not _x(code, c, 'out'):   # OUT 제외 채널은 잉여 공급 안 함
                    su[c] = int(m)
                continue
            woc = i / o
            if woc <= short_th:
                # 소액 사이즈 제외(주간주문 min_recv 미만) — 기본 0(제외 안 함)
                if o < params.get('min_recv_order', MIN_RECV_ORDER):
                    continue
                need_full = max(0, int(math.ceil(target * o - i)))
                if need_full > 0 and not _x(code, c, 'in'):   # IN 제외 채널은 수신 안 함
                    sh[c] = need_full
            elif woc > target:
                # 잉여량 판정: 총재고(WOC) 기준, 실제 OUT 가능: 내부재고(EHUB) 기준
                avail = min(int((woc - target) * o), i_internal, _cap(i_internal))
                if avail > 0 and not _x(code, c, 'out'):
                    su[c] = avail
        shortage[code] = sh
        surplus_left[code] = su

    # ── 마이너 채널 제외(구색 보호) — 수요 사이즈 수가 최다 채널의 50% 미만이면 수신 제외 ──
    demand_cnt = {c: sum(1 for code in group if group[code]['orders'].get(c, 0) > 0)
                  for c in channels}
    max_dc = max(demand_cnt.values()) if demand_cnt else 0
    viable = {c for c in channels if max_dc > 0 and demand_cnt[c] >= 0.5 * max_dc}

    # ── 채널별 그룹 재고주수(가중) — 낮을수록 결품 심함 ──
    def group_woc(c):
        ti = sum(group[code]['inv'].get(c, 0) for code in group)
        to = sum(group[code]['orders'].get(c, 0) for code in group)
        return (ti / to) if to > 0 else float('inf')

    # ── 단품당 1채널만 IN (사용자 6/25 요청) ──
    # 1순위: 단독 이동 시 기대효과(해소되는 결품량) 큰 채널
    # 2순위: 동률이면 저수수료 채널 (CHANNEL_PRIORITY 작은 값)
    # 마이너 채널(viable 외)은 수신 후보에서 제외
    for code in group:
        sh = shortage.get(code, {})
        if not sh:
            continue
        d = group[code]
        candidates = []
        total_avail = sum(surplus_left[code].values())
        if total_avail <= 0:
            continue
        for ch, need_full in sh.items():
            if ch not in viable:
                continue
            g = min(need_full, total_avail)
            if g <= 0:
                continue
            i = d['inv'].get(ch, 0)
            o = d['orders'].get(ch, 0)
            old_short = max(0, o - i)
            new_short = max(0, o - i - g)
            rev = old_short - new_short  # 단가 동일 — 해소량으로 비교
            candidates.append((ch, g, rev))
        if not candidates:
            continue
        # 정렬: 1순위 기대효과 ↓, 2순위 저수수료 ↑
        candidates.sort(key=lambda x: (-x[2], _prio(x[0])))
        best_ch, best_g, _ = candidates[0]
        # OUT 회수: 고수수료(역순)부터 best_ch에 충전
        need = best_g
        for src in sorted(list(surplus_left[code].keys()), key=lambda x: -_prio(x)):
            if need <= 0:
                break
            tk = min(surplus_left[code][src], need)
            if tk > 0:
                out[code][src] -= tk
                out[code][best_ch] += tk
                surplus_left[code][src] -= tk
                need -= tk

    # ── 비부가 필터 (사이즈별) ──
    for code, d in group.items():
        pos = sum(v for v in out[code].values() if v > 0)
        if pos < params['min_move_qty'] and not d.get('critical', False):
            out[code] = {c: 0 for c in channels}

    return out


def calc_expected_revenue(sku_data, moves, channels, price, days: int = 5):
    """기대효과 = 해소된 결품량 × 정상가 × (days/7) — 5일 기준 회수매출 (사용자 7/23 요청)
    
    orders는 파일 기준 주간(7일) 판매량 → 5일 예측 판매량으로 스케일링.
    days=7이면 종전과 동일 결과 (호환성).
    """
    revenue = 0
    scale = days / 7.0  # 5/7 스케일링 (5일 기준 회수매출)
    for c in channels:
        inv = sku_data['inv'].get(c, 0)
        o_wk = sku_data['orders'].get(c, 0)
        o = o_wk * scale  # 5일 예측 주문량
        new_inv = inv + moves.get(c, 0)
        old_short = max(0, o - inv)
        new_short = max(0, o - new_inv)
        revenue += (old_short - new_short) * price
    return int(revenue)


def calc_distribution(sku_data, moves, channels, dist_target=2.0, bw_name='반응과'):
    """회전(채널 간 이동) 후에도 남은 결품을 반응과 재고로 보충 = SCM '분배' 요청.
    Returns: (dist dict {channel:int IN}, used int 반응과 차감 총량)."""
    dist = {c: 0 for c in channels}
    bw = int(sku_data['inv'].get(bw_name, 0))
    if bw <= 0 or sku_data.get('locked', False):
        return dist, 0
    need = {}
    for c in channels:
        o = sku_data['orders'].get(c, 0)
        if o <= 0:
            continue
        after_i = sku_data['inv'].get(c, 0) + moves.get(c, 0)
        nd = int(math.ceil(dist_target * o - after_i))
        if nd > 0:
            need[c] = nd
    if not need:
        return dist, 0
    supply = min(bw, sum(need.values()))
    rem = supply

    def _woc_after(c):
        o = sku_data['orders'].get(c, 0)
        return (sku_data['inv'].get(c, 0) + moves.get(c, 0)) / o if o > 0 else 999

    for c in sorted(need, key=lambda x: (_woc_after(x), _prio(x))):
        if rem <= 0:
            break
        tk = min(need[c], rem)
        dist[c] = tk
        rem -= tk
    return dist, supply
