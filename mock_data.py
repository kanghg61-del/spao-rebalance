# -*- coding: utf-8 -*-
"""
실 단품 데이터 로더 v2.0 (듀얼 버전 지원)
- get_combined_data('v2') : v2.0 — 리오더 병합 적용, 외부창고 분리 (기본)
- get_combined_data('v1') : v1.4 참고용 — 원본 그대로 (반응과 포함, 병합 없음)
- 외부창고: 무신사 풀필먼트(AENS)·지그재그 천안(ADU3)·네이버 CMS(ADQS)
  sku_master.csv 에 wh_채널 컬럼이 있으면 사용, 없으면 결정적 mock 분리(실데이터 수신 시 교체)
- 리오더 병합: reorder_mapping.(csv|xlsx) 발견 시 리오더코드의 재고·주문을
  기존코드로 합산, 화면은 기존코드로 노출
"""
import copy
import csv, os, hashlib
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
CSV_PATH = os.path.join(_DIR, 'sku_master.csv')

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


def _load_reorder_mapping():
    """리오더 매핑 로드 → {리오더코드: 기존코드}. 컬럼명은 '기존'/'리오더' 포함 여부로 자동 탐지."""
    path = _find_reorder_file()
    if not path:
        return {}, None
    rows = []
    if path.endswith('.csv'):
        with open(path, encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
    else:  # xlsx
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            it = ws.iter_rows(values_only=True)
            header = [str(c).strip() if c is not None else '' for c in next(it)]
            for r in it:
                rows.append({header[i]: r[i] for i in range(min(len(header), len(r)))})
        except Exception:
            return {}, None
    if not rows:
        return {}, os.path.basename(path)
    cols = list(rows[0].keys())
    org_col = next((c for c in cols if '기존' in c or 'org' in c.lower() or 'style' in c.lower()), cols[0])
    re_col = next((c for c in cols if '리오더' in c or 'reorder' in c.lower()), cols[-1])
    mapping = {}
    for r in rows:
        org = str(r.get(org_col) or '').strip()
        reo = str(r.get(re_col) or '').strip()
        if org and reo and org != reo:
            mapping[reo] = org
    return mapping, os.path.basename(path)


def _load_raw():
    """원본 로드 (v1.4 호환 — 반응과 포함, 병합 없음)"""
    if 'raw' in _cache:
        return _cache['raw']
    skus = {}
    with open(CSV_PATH, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row['단품코드'].strip()
            if not code:
                continue
            inv = {BW_NAME: int(_num(row.get('inv_반응과', 0)))}
            ext_wh = {}
            for ch in CHANNELS:
                q = int(_num(row.get(f'inv_{ch}', 0)))
                inv[ch] = q
                if ch in EXT_WAREHOUSE:
                    wh_col = row.get(f'wh_{ch}')
                    ext_wh[ch] = int(_num(wh_col)) if wh_col not in (None, '') else _mock_ext_wh_qty(code, ch, q)
            orders = {ch: int(_num(row.get(f'ord_{ch}', 0))) for ch in CHANNELS}
            skus[code] = {
                'rank_total': int(_num(row.get('매출랭킹', 9999), 9999)),
                'rank_online': int(_num(row.get('온라인랭킹', 9999), 9999)),
                'name': row.get('단품명', '').strip(),
                'price': int(_num(row.get('정상가', 0))),
                'ship_rate': _num(row.get('출고율', 0)),
                'online_ratio': _num(row.get('온라인비중', 0)),
                'locked': False,
                'critical': False,
                'inv': inv,
                'orders': orders,
                'ext_wh': ext_wh,          # 외부창고 보관분 (채널 재고에 포함된 값)
                'reorder_codes': [],       # 병합된 리오더코드 목록 (v2 병합 시 채움)
            }
    _cache['raw'] = skus
    return skus


def _load_merged():
    """v2.0 — 리오더 병합 적용본"""
    if 'merged' in _cache:
        return _cache['merged']

    reorder_map, reorder_file = _load_reorder_mapping()
    skus = copy.deepcopy(_load_raw())

    merged = 0
    if reorder_map:
        for reo, org in reorder_map.items():
            if reo not in skus:
                continue
            src = skus.pop(reo)
            if org not in skus:
                # 기존코드가 마트에 없으면 리오더 데이터를 기존코드 이름으로 승격
                src['reorder_codes'] = [reo]
                skus[org] = src
                merged += 1
                continue
            dst = skus[org]
            dst['inv'][BW_NAME] = dst['inv'].get(BW_NAME, 0) + src['inv'].get(BW_NAME, 0)
            for ch in CHANNELS:
                dst['inv'][ch] += src['inv'][ch]
                dst['orders'][ch] += src['orders'][ch]
                if ch in dst['ext_wh']:
                    dst['ext_wh'][ch] += src['ext_wh'].get(ch, 0)
            # 출고율·온라인비중은 주문량 가중 평균
            s_ord = sum(src['orders'].values()) or 1
            d_ord = sum(dst['orders'].values()) or 1
            w = s_ord / (s_ord + d_ord)
            dst['ship_rate'] = dst['ship_rate'] * (1 - w) + src['ship_rate'] * w
            dst['online_ratio'] = dst['online_ratio'] * (1 - w) + src['online_ratio'] * w
            dst['rank_online'] = min(dst['rank_online'], src['rank_online'])
            dst['rank_total'] = min(dst['rank_total'], src['rank_total'])
            dst['reorder_codes'].append(reo)
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
    """리오더 병합 현황: {'file': 파일명|None, 'merged': 병합건수, 'mapping_rows': 매핑행수}"""
    _load_merged()
    return _cache.get('reorder_info', {'file': None, 'merged': 0, 'mapping_rows': 0})


def fetch_sap_inventory(seed=None):
    return _load_merged()


def fetch_channel_orders(seed=None):
    return None


def get_last_update_time():
    now = datetime.now()
    today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now < today_6am:
        return today_6am - timedelta(days=1)
    return today_6am
