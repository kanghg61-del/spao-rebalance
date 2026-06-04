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
CSV_PATH = os.path.join(_DIR, 'sku_master.csv')
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
                'reorder_codes': [],       # 병합된 리오더 단품코드 목록 (v2 병합 시 채움)
            }
    _cache['raw'] = skus
    return skus


def _merge_into(dst, src, reo_code):
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
                    target = m[code[:L]] + code[L:]   # suffix(사이즈 등) 유지
                    break
            if not target or target == code or code not in skus:
                continue
            src = skus.pop(code)
            if target in skus:
                _merge_into(skus[target], src, code)
            else:
                # 기존코드 단품이 마트에 없으면 리오더 데이터를 기존코드로 승격
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
    now = datetime.now()
    today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now < today_6am:
        return today_6am - timedelta(days=1)
    return today_6am
