# -*- coding: utf-8 -*-
"""
실 단품 데이터 로더 (보수운영.xlsx에서 추출한 sku_master.csv 사용)
- 8,308 단품
- 6채널: 공홈, 이랜드몰, 무신사, 지그재그, 네이버, 카카오선물하기
- 매출 순위·온라인 매출 순위 포함
"""
import csv, os
from datetime import datetime, timedelta

CHANNELS = ['공홈', '이랜드몰', '무신사', '지그재그', '네이버', '카카오선물하기']
BW_NAME = '반응과'
CSV_PATH = os.path.join(os.path.dirname(__file__), 'sku_master.csv')

_cache = {}

def _load_master():
    if 'data' in _cache:
        return _cache['data']
    skus = {}
    with open(CSV_PATH, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row['단품코드'].strip()
            if not code: continue
            def num(v, d=0):
                try: return float(v) if v not in (None, '', 'None') else d
                except: return d
            inv = {BW_NAME: int(num(row['inv_반응과']))}
            for ch in CHANNELS:
                inv[ch] = int(num(row.get(f'inv_{ch}', 0)))
            orders = {ch: int(num(row.get(f'ord_{ch}', 0))) for ch in CHANNELS}
            skus[code] = {
                'rank_total': int(num(row.get('매출랭킹', 9999), 9999)),
                'rank_online': int(num(row.get('온라인랭킹', 9999), 9999)),
                'name': row.get('단품명', '').strip(),
                'price': int(num(row.get('정상가', 0))),
                'ship_rate': num(row.get('출고율', 0)),
                'online_ratio': num(row.get('온라인비중', 0)),
                'locked': False,
                'critical': False,
                'inv': inv,
                'orders': orders,
            }
    _cache['data'] = skus
    return skus


def get_combined_data(seed=None, n_skus=None):
    """SAP 재고 + 6채널 주문 통합 (실 데이터)"""
    return _load_master()


def fetch_sap_inventory(seed=None):
    return _load_master()


def fetch_channel_orders(seed=None):
    return None


def get_last_update_time():
    now = datetime.now()
    today_3am = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if now < today_3am:
        return today_3am - timedelta(days=1)
    return today_3am
