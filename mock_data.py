# -*- coding: utf-8 -*-
"""
실 단품 데이터 로더 v2.2 (듀얼 버전 지원)
- get_combined_data('v2') : 최신 — 리오더 병합 적용, 외부창고 분리
- get_combined_data('v1') : v1.4 참고용 — 원본 그대로 (반응과 포함, 병합 없음)
- 외부창고: 무신사 풀필먼트(AENS)·지그재그 천안(ADU3)·네이버 CMS(ADQS)
  sku_master.csv 에 wh_채널 컬럼이 있으면 사용, 없으면 결정적 mock 분리(실데이터 수신 시 교체)
- 리오더 병합 v2.2:
  · reorder_mapping.(csv|xlsx) 자동 감지 (컬럼: 기존코드 / 리오더(추가)코드)
  · 스타일코드(10자리) 매핑도 지원 — 단품코드 prefix 매칭 후 사이즈 suffix 유지 병합
  · 웹에서 갱신 가능: save_reorder_mapping() / parse_reorder_bytes() (앱 '🔁 리오더 매핑' 탭)
"""
import copy
import csv, io, os, hashlib
from datetime import datetime, timedelta

CHANNELS = ['공홈', '이랜드몰', '무신사', '지그재그', '네이버', '카카오선물하기']
BW_NAME = '반응과'  # v1.4 참고 모드 전용

# 외부창고 정의: 채널 → (창고명, 창고코드)
EXT_WAREHOUSE = {
    '무신사': ('무신사 풀필먼트', 'AENS'),
    '지그재그': ('지그재그 천안', 'ADU3'),
    '네이버': ('네이버 CMS', 'ADQS'),
}

_DIR = os.path.dirname(__file__)
# 실데이터 자동 감지 — data_spao_YYMMDD.csv 중 가장 최신 (날짜 큰 것) 자동 선택
# 매일 새 CSV만 push하면 자동 반영 (mock_data.py 수정 불필요)
import glob as _glob
_REALS = sorted(_glob.glob(os.path.join(_DIR, 'data_spao_*.csv')), reverse=True)
_MOCK = os.path.join(_DIR, 'sku_master.csv')
CSV_PATH = _REALS[0] if _REALS else _MOCK
REORDER_SAVE_PATH = os.path.join(_DIR, 'reorder_mapping.csv')

# 리오더 매핑 파일 후보 (기존코드/리오더코드 — rsc.reorder_style_mapping_spao 추출본)
REORDER_CANDIDATES = [
    'reorder_mapping.csv', 'reorder_mapping.xlsx',
    '리오더매핑.csv', '리오더매핑.xlsx',
]

_cache = {}


def _num(v, d=0):
    try:
        return float(v) if v not in (None, '', 'None') else d
    except Exception:
        return d


def _mock_ext_wh_qty(code, ch, inv_qty):
    """외부창고 mock 분리 — 코드+채널 해시 기반 결정적 비율 35~65% (실데이터 수신 시 교체)"""
    if inv_qty <= 0:
        return 0
    h = int(hashlib.md5(f'{code}|{ch}'.encode()).hexdigest()[:8], 16)
    ratio = 0.35 + (h % 31) / 100.0  # 0.35 ~ 0.65
    return int(inv_qty * ratio)


def _find_reorder_file():
    for name in REORDER_CANDIDATES:
        p = os.path.join(_DIR, name)
        if os.path.exists(p):
            return p
    return None


def _detect_cols(cols):
    """기존/리오더(추가) 컬럼 자동 탐지"""
    org_col = next((c for c in cols if '기존' in c or '원오더' in c or 'org' in c.lower() or 'style' in c.lower()), cols[0])
    re_col = next((c for c in cols if '리오더' in c or '추가' in c or 'reorder' in c.lower()), None)
    if re_col is None:
        re_col = next((c for c in cols if c != org_col), cols[-1])
    return org_col, re_col


def _rows_to_pairs(rows):
    """dict rows → [(기존코드, 리오더코드)] (동일·빈 코드 제외, 중복 제거)"""
    if not rows:
        return []
    org_col, re_col = _detect_cols(list(rows[0].keys()))
    pairs, seen = [], set()
    for r in rows:
        org = str(r.get(org_col) or '').strip().upper()
        reo = str(r.get(re_col) or '').strip().upper()
        if org and reo and org != reo and reo not in seen:
            pairs.append((org, reo))
            seen.add(reo)
    return pairs


def parse_reorder_bytes(data, filename):
    """업로드 파일(bytes) → [(기존코드, 리오더코드)]. csv/xlsx 지원."""
    rows = []
    if filename.lower().endswith('.csv'):
        text = data.decode('utf-8-sig', errors='replace')
        rows = list(csv.DictReader(io.StringIO(text)))
    else:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        header = [str(c).strip() if c is not None else '' for c in next(it)]
        for r in it:
            rows.append({header[i]: r[i] for i in range(min(len(header), len(r)))})
    return _rows_to_pairs(rows)


def save_reorder_mapping(pairs):
    """매핑 저장(전체 교체) + 캐시 무효화. pairs: [(기존코드, 리오더코드)]"""
    with open(REORDER_SAVE_PATH, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['기존코드', '리오더코드'])
        w.writerows(pairs)
    for k in ('merged', 'reorder_info', 'mapping'):
        _cache.pop(k, None)


def _load_reorder_mapping():
    """현재 매핑 로드 → ({리오더코드: 기존코드}, 파일명)"""
    if 'mapping' in _cache:
        return _cache['mapping']
    path = _find_reorder_file()
    if not path:
        _cache['mapping'] = ({}, None)
        return _cache['mapping']
    try:
        with open(path, 'rb') as f:
            pairs = parse_reorder_bytes(f.read(), path)
    except Exception:
        pairs = []
    mapping = {reo: org for org, reo in pairs}
    _cache['mapping'] = (mapping, os.path.basename(path))
    return _cache['mapping']


def get_reorder_mapping():
    """[(기존코드, 리오더코드)] 정렬 리스트 (표시·다운로드용)"""
    mapping, _ = _load_reorder_mapping()
    return sorted([(org, reo) for reo, org in mapping.items()])


def _load_raw():
    """원본 로드 (v1.4 호환 — 반응과 포함, 병합 없음)"""
    if 'raw' in _cache:
        return _cache['raw']
    skus = {}
    with open(CSV_PATH, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row['단품코드'].strip()
            if not code:
                continue
            inv = {BW_NAME: int(_num(row.get('inv_반응과', 0)))}
            ext_wh = {}
            ext_wh_amt = {}
            for ch in CHANNELS:
                q = int(_num(row.get(f'inv_{ch}', 0)))
                inv[ch] = q
                if ch in EXT_WAREHOUSE:
                    # 외부창고 실수치 (CSV 직접) — 사용자 6/25 매장코드 재분류: AENS·ADU3·ADQS
                    ext_wh[ch] = int(_num(row.get(f'wh_{ch}', 0)))
                    ext_wh_amt[ch] = int(_num(row.get(f'wh_amt_{ch}', 0)))
            orders = {ch: int(_num(row.get(f'ord_{ch}', 0))) for ch in CHANNELS}
            daily = {ch: int(_num(row.get(f'daily_{ch}', 0))) for ch in CHANNELS}
            # 외형매출·재고액 실수치 (CSV 직접) — 사용자 6/25 요청: 가격 추정 X
            daily_amt = {ch: int(_num(row.get(f'daily_amt_{ch}', 0))) for ch in CHANNELS}
            inv_amt = {ch: int(_num(row.get(f'inv_amt_{ch}', 0))) for ch in CHANNELS}
            skus[code] = {
                'rank_total': int(_num(row.get('매출랭킹', 9999), 9999)),
                'rank_online': int(_num(row.get('온라인랭킹', 9999), 9999)),
                'name': row.get('단품명', '').strip(),
                'price': int(_num(row.get('정상가', 0))),
                'ship_rate': _num(row.get('출고율', 0)),
                'online_ratio': _num(row.get('온라인비중', 0)),
                'cum_rate': _num(row.get('누판율', 0)),
                'wk_rate': _num(row.get('주판율', 0)),
                'wk_sales': _num(row.get('주간외형매출', 0)),
                'locked': False,
                'critical': False,
                'inv': inv,
                'orders': orders,
                'daily': daily,
                'daily_amt': daily_amt,     # 전일 외형매출 실수치 (만원·억 직접 표시용)
                'inv_amt': inv_amt,         # 매장재고 정상가 실수치
                'in_qty': int(_num(row.get('in_qty', 0))),     # 누적입고량 (스타일 합산용)
                'cum_qty': int(_num(row.get('cum_qty', 0))),   # 누적판매량
                'wk_qty': int(_num(row.get('wk_qty', 0))),     # 기간판매량
                'last_date': row.get('_last_date', '') or '',
                'ext_wh': ext_wh,
                'ext_wh_amt': ext_wh_amt,
                'reorder_codes': [],
            }
    _cache['raw'] = skus
    return skus


def _merge_into(dst, src, reo_code):
    dst['inv'][BW_NAME] = dst['inv'].get(BW_NAME, 0) + src['inv'].get(BW_NAME, 0)
    for ch in CHANNELS:
        dst['inv'][ch] += src['inv'][ch]
        dst['orders'][ch] += src['orders'][ch]
        # daily / daily_amt / inv_amt 도 병합 (사용자 6/25 — 실수치 누락 방지)
        if 'daily' in dst and 'daily' in src:
            dst['daily'][ch] = dst['daily'].get(ch, 0) + src['daily'].get(ch, 0)
        if 'daily_amt' in dst and 'daily_amt' in src:
            dst['daily_amt'][ch] = dst['daily_amt'].get(ch, 0) + src['daily_amt'].get(ch, 0)
        if 'inv_amt' in dst and 'inv_amt' in src:
            dst['inv_amt'][ch] = dst['inv_amt'].get(ch, 0) + src['inv_amt'].get(ch, 0)
        if ch in dst['ext_wh']:
            dst['ext_wh'][ch] += src['ext_wh'].get(ch, 0)
    # 출고율·온라인비중은 주문량 가중 평균
    s_ord = sum(src['orders'].values())
    d_ord = sum(dst['orders'].values())
    denom = s_ord + d_ord
    w = (s_ord / denom) if denom else 0.5
    dst['ship_rate'] = dst['ship_rate'] * (1 - w) + src['ship_rate'] * w
    dst['online_ratio'] = dst['online_ratio'] * (1 - w) + src['online_ratio'] * w
    dst['rank_online'] = min(dst['rank_online'], src['rank_online'])
    dst['rank_total'] = min(dst['rank_total'], src['rank_total'])
    dst['wk_sales'] = dst.get('wk_sales', 0) + src.get('wk_sales', 0)
    dst['reorder_codes'].append(reo_code)


def _load_merged():
    """최신 — 리오더 병합 적용본 (스타일코드 prefix 매칭 지원)"""
    if 'merged' in _cache:
        return _cache['merged']

    reorder_map, reorder_file = _load_reorder_mapping()
    skus = copy.deepcopy(_load_raw())

    merged = 0
    if reorder_map:
        # 매핑 코드 길이별 그룹 (스타일 10자리 / 단품 15자리 혼용 지원)
        by_len = {}
        for reo, org in reorder_map.items():
            by_len.setdefault(len(reo), {})[reo] = org

        for code in list(skus.keys()):
            target = None
            for L, m in by_len.items():
                if len(code) >= L and code[:L] in m:
                    cand = m[code[:L]] + code[L:]   # 기존스타일 + (컬러+사이즈) suffix 유지
                    # ── 컬러코드(단품코드 11~12자리) 동일 기준(v4.3) ──
                    # 스타일코드 매핑 후, 리오더 단품과 병합 대상의 컬러코드(11~12자리)가
                    # 동일할 때만 병합한다. 매핑이 스타일(10자리) 단위라 컬러 suffix가
                    # 보존되지만, 코드 길이 불일치·데이터 이상으로 컬러가 달라지면 병합하지 않는다.
                    if code[10:12] and code[10:12] == cand[10:12]:
                        target = cand
                    break
            if not target or target == code or code not in skus:
                continue
            src = skus.pop(code)
            if target in skus:
                # 컬러코드(11~12자리)가 동일한 기존 단품과 재고 합산 병합
                _merge_into(skus[target], src, code)
            else:
                # 기존코드 단품이 마트에 없으면 리오더 데이터를 기존코드로 승격(컬러 보존)
                src['reorder_codes'] = [code]
                skus[target] = src
            merged += 1

    _cache['merged'] = skus
    _cache['reorder_info'] = {'file': reorder_file, 'merged': merged,
                              'mapping_rows': len(reorder_map)}
    return skus


def get_combined_data(version='v2', seed=None, n_skus=None):
    """SAP 재고 + 6채널 주문 통합. version: 'v2'(병합 적용) | 'v1'(원본)"""
    if version == 'v1':
        return _load_raw()
    return _load_merged()


def get_reorder_info():
    """리오더 병합 현황: {'file': 파일명|None, 'merged': 병합 단품수, 'mapping_rows': 매핑 행수}"""
    _load_merged()
    return _cache.get('reorder_info', {'file': None, 'merged': 0, 'mapping_rows': 0})


def fetch_sap_inventory(seed=None):
    return _load_merged()



def fetch_channel_orders(seed=None):
    return None


def get_last_update_time():
    """대시보드 표시용 마지막 데이터 갱신 시각 (mock — 매일 06:00)."""
    now = datetime.now()
    return now.replace(hour=6, minute=0, second=0, microsecond=0)
