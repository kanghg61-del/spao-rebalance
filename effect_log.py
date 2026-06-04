# -*- coding: utf-8 -*-
"""
실행 효과 누적 로그 — 재배치 승인 실행 이력 + 기대효과 대비 실제효과(실측) 관리
- 저장: execution_log.csv (앱 폴더) — 앱 재시작 시 패키지 기준 초기화 → CSV 백업/복원 지원
- 실 배포 시: 실측 = 이동 후 D+7 해소결품 SKU의 실제 판매 실적(EDW) 자동 집계로 교체
"""
import csv, io, os, hashlib
from datetime import datetime

_DIR = os.path.dirname(__file__)
LOG_PATH = os.path.join(_DIR, 'execution_log.csv')
FIELDS = ['id', '실행일시', '시나리오', '단품수', '이동량_장', '기대효과_만원',
          '실제효과_만원', '실측일', '상태', '메모']


def load_log():
    """실행 이력 로드 → list[dict]"""
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def _save(rows):
    with open(LOG_PATH, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in FIELDS})


def log_execution(scenario, sku_count, qty, expected_rev_won, memo=''):
    """승인 실행 1건 기록. expected_rev_won: 원 단위"""
    rows = load_log()
    rid = max([int(r['id']) for r in rows], default=0) + 1
    rows.append({
        'id': rid,
        '실행일시': datetime.now().strftime('%Y-%m-%d %H:%M'),
        '시나리오': scenario,
        '단품수': sku_count,
        '이동량_장': qty,
        '기대효과_만원': round(expected_rev_won / 10000),
        '실제효과_만원': '',
        '실측일': '',
        '상태': '실측 대기',
        '메모': memo,
    })
    _save(rows)
    return rid


def save_rows(rows):
    """data_editor 수정분 저장 — 실제효과 입력 시 상태 자동 갱신"""
    today = datetime.now().strftime('%Y-%m-%d')
    for r in rows:
        actual = str(r.get('실제효과_만원') or '').strip()
        if actual and r.get('상태') in ('', '실측 대기'):
            r['상태'] = '실측 완료(수동)'
            r['실측일'] = r.get('실측일') or today
    _save(rows)


def mock_fill_actuals():
    """D+7 실측 자동 산출 (mock) — 실데이터 연동 전 데모용. 기대효과의 85~97% 결정적 산출"""
    rows = load_log()
    n = 0
    today = datetime.now().strftime('%Y-%m-%d')
    for r in rows:
        if not str(r.get('실제효과_만원') or '').strip():
            h = int(hashlib.md5(str(r['id']).encode()).hexdigest()[:6], 16)
            ratio = 0.85 + (h % 13) / 100.0
            r['실제효과_만원'] = round(float(r.get('기대효과_만원') or 0) * ratio)
            r['실측일'] = today
            r['상태'] = '실측 완료(mock)'
            n += 1
    _save(rows)
    return n


def restore_from_bytes(data):
    """백업 CSV 복원 (전체 교체) → 행수"""
    text = data.decode('utf-8-sig', errors='replace')
    rows = list(csv.DictReader(io.StringIO(text)))
    _save(rows)
    return len(rows)


def export_csv_bytes():
    rows = load_log()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, '') for k in FIELDS})
    return buf.getvalue().encode('utf-8-sig')


def clear_log():
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)
