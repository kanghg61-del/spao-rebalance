# -*- coding: utf-8 -*-
"""
실행 효과 누적 로그 v2 — 재배치 승인 실행 이력 + 실제효과(실측) 관리

실제효과 정의 (보수 집계):
  이동(IN) 받은 단품×채널에서 **전일(이동 전) 재고로는 판매할 수 없었던 추가 판매분만** 인정
    추가판매(장) = min( 이동IN수량, max(0, 실제판매수량 − 전일재고) )
    실제효과(원) = Σ 추가판매 × 정상가
  → 이동 없이도 팔 수 있었던 물량(전일재고 內 판매)은 효과에서 제외

저장:
  execution_log.csv     — 실행 단위 요약 (1행/실행)
  execution_details.csv — 단품×채널 IN 스냅샷 (전일재고·이동IN·정상가) + 실측 채움
  실측 = 실측일 당일 매출 기준 (매일 06:00 매출 갱신 후 집계). 일일 매출 자료 업로드로 자동 반영.
  앱 재시작 시 초기화 → CSV 백업/복원 지원. 실 배포 시 DB + EDW 일일 판매 실적 자동 집계로 교체
"""
import csv, io, os, hashlib
from datetime import datetime

_DIR = os.path.dirname(__file__)
LOG_PATH = os.path.join(_DIR, 'execution_log.csv')
DETAILS_PATH = os.path.join(_DIR, 'execution_details.csv')
FIELDS = ['id', '실행일시', '시나리오', '단품수', '이동량_장', '기대효과_만원',
          '실제효과_만원', '추가판매_장', '실측일', '상태', '메모']
DETAIL_FIELDS = ['exec_id', '단품코드', '채널', '전일재고_장', '이동IN_장', '정상가',
                 '실제판매_장', '추가판매_장']


def load_log():
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def load_details(exec_id=None):
    if not os.path.exists(DETAILS_PATH):
        return []
    with open(DETAILS_PATH, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if exec_id is not None:
        rows = [r for r in rows if str(r.get('exec_id')) == str(exec_id)]
    return rows


def _save(rows):
    with open(LOG_PATH, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in FIELDS})


def _save_details(rows):
    with open(DETAILS_PATH, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in DETAIL_FIELDS})


def log_execution(scenario, sku_count, qty, expected_rev_won, details=None, memo=''):
    """승인 실행 기록. details: [(단품코드, 채널, 전일재고, 이동IN, 정상가)] — IN 발생분만"""
    rows = load_log()
    rid = max([int(r['id']) for r in rows], default=0) + 1
    rows.append({
        'id': rid,
        '실행일시': datetime.now().strftime('%Y-%m-%d %H:%M'),
        '시나리오': scenario,
        '단품수': sku_count,
        '이동량_장': qty,
        '기대효과_만원': round(expected_rev_won / 10000),
        '실제효과_만원': '', '추가판매_장': '',
        '실측일': '', '상태': '실측 대기', '메모': memo,
    })
    _save(rows)
    if details:
        drows = load_details()
        for code, ch, prev_inv, in_qty, price in details:
            drows.append({'exec_id': rid, '단품코드': code, '채널': ch,
                          '전일재고_장': int(prev_inv), '이동IN_장': int(in_qty),
                          '정상가': int(price), '실제판매_장': '', '추가판매_장': ''})
        _save_details(drows)
    return rid


def save_rows(rows):
    """data_editor 수정분 저장 — 실제효과 수동 입력 시 상태 자동 갱신"""
    today = datetime.now().strftime('%Y-%m-%d')
    for r in rows:
        actual = str(r.get('실제효과_만원') or '').strip()
        if actual and r.get('상태') in ('', '실측 대기'):
            r['상태'] = '실측 완료(수동)'
            r['실측일'] = r.get('실측일') or today
    _save(rows)


def mock_fill_actuals():
    """D+7 실측 자동 산출 (mock) — 전일재고 대비 추가판매분만 집계 (실데이터 연동 전 데모)
    실제판매(mock) = 전일재고 소진 + 이동IN의 60~95%(결정적) 판매 가정
    → 추가판매 = min(이동IN, max(0, 실제판매 − 전일재고)) = IN × ratio"""
    rows = load_log()
    drows = load_details()
    today = datetime.now().strftime('%Y-%m-%d')
    n = 0
    for r in rows:
        if str(r.get('실제효과_만원') or '').strip():
            continue
        rid = str(r['id'])
        won = 0
        extra_total = 0
        has_detail = False
        for d in drows:
            if str(d['exec_id']) != rid:
                continue
            has_detail = True
            prev = int(float(d['전일재고_장'] or 0))
            inq = int(float(d['이동IN_장'] or 0))
            price = int(float(d['정상가'] or 0))
            h = int(hashlib.md5(f"{rid}|{d['단품코드']}|{d['채널']}".encode()).hexdigest()[:6], 16)
            ratio = 0.60 + (h % 36) / 100.0  # 0.60 ~ 0.95
            sold = prev + int(round(inq * ratio))          # 전일재고 소진 후 IN분 일부 판매
            extra = min(inq, max(0, sold - prev))          # 추가판매 = 이동 덕분에 팔린 수량
            d['실제판매_장'] = sold
            d['추가판매_장'] = extra
            extra_total += extra
            won += extra * price
        if has_detail:
            r['실제효과_만원'] = round(won / 10000)
            r['추가판매_장'] = extra_total
        else:
            # 상세 스냅샷 없는 구버전 이력 — 기대효과의 85~97% 보수 추정
            h = int(hashlib.md5(rid.encode()).hexdigest()[:6], 16)
            r['실제효과_만원'] = round(float(r.get('기대효과_만원') or 0) * (0.85 + (h % 13) / 100.0))
        r['실측일'] = today
        r['상태'] = '실측 완료(mock)'
        n += 1
    _save(rows)
    _save_details(drows)
    return n


def _detect_sales_cols(cols):
    code_col = next((c for c in cols if '단품' in c or 'code' in c.lower() or '코드' in c), cols[0])
    ch_col = next((c for c in cols if '채널' in c or 'channel' in c.lower()), None)
    qty_col = next((c for c in cols if '판매' in c or '수량' in c or 'qty' in c.lower() or 'sales' in c.lower()), cols[-1])
    return code_col, ch_col, qty_col


def apply_sales_bytes(data, filename):
    """일일 매출 자료(csv/xlsx) → 실측 대기 실행의 실제효과 자동 산출 (당일 매출 기준)
    컬럼 자동 인식: 단품코드 / 채널(선택) / 판매수량
    채널 없으면 해당 단품의 이동IN 비중으로 채널 배분. 반환: (실측 완료 실행수, 매칭 단품수)"""
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
    if not rows:
        return 0, 0
    code_col, ch_col, qty_col = _detect_sales_cols(list(rows[0].keys()))
    by_code_ch, by_code = {}, {}
    for r in rows:
        code = str(r.get(code_col) or '').strip().upper()
        if not code:
            continue
        try:
            qty = int(float(r.get(qty_col) or 0))
        except Exception:
            qty = 0
        ch = str(r.get(ch_col) or '').strip() if ch_col else ''
        if ch:
            by_code_ch[(code, ch)] = by_code_ch.get((code, ch), 0) + qty
        by_code[code] = by_code.get(code, 0) + qty

    log_rows = load_log()
    drows = load_details()
    today = datetime.now().strftime('%Y-%m-%d')
    n_exec, matched = 0, 0
    for lr in log_rows:
        if str(lr.get('실제효과_만원') or '').strip():
            continue
        rid = str(lr['id'])
        dets = [d for d in drows if str(d['exec_id']) == rid]
        if not dets:
            continue
        in_sum_by_code = {}
        for d in dets:
            in_sum_by_code[d['단품코드']] = in_sum_by_code.get(d['단품코드'], 0) + int(float(d['이동IN_장'] or 0))
        won, extra_total, hit = 0, 0, 0
        for d in dets:
            code, ch = d['단품코드'], d['채널']
            prev = int(float(d['전일재고_장'] or 0))
            inq = int(float(d['이동IN_장'] or 0))
            price = int(float(d['정상가'] or 0))
            sold = None
            if (code, ch) in by_code_ch:
                sold = by_code_ch[(code, ch)]
            elif code in by_code and in_sum_by_code.get(code, 0) > 0:
                sold = int(round(by_code[code] * inq / in_sum_by_code[code]))
            if sold is None:
                continue
            extra = min(inq, max(0, sold - prev))
            d['실제판매_장'] = sold
            d['추가판매_장'] = extra
            won += extra * price
            extra_total += extra
            hit += 1
        if hit:
            lr['실제효과_만원'] = round(won / 10000)
            lr['추가판매_장'] = extra_total
            lr['실측일'] = today
            lr['상태'] = '실측 완료(매출연동)'
            n_exec += 1
            matched += hit
    _save(log_rows)
    _save_details(drows)
    return n_exec, matched


def restore_from_bytes(data):
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


def export_details_bytes():
    rows = load_details()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=DETAIL_FIELDS)
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, '') for k in DETAIL_FIELDS})
    return buf.getvalue().encode('utf-8-sig')


def clear_log():
    for p in (LOG_PATH, DETAILS_PATH):
        if os.path.exists(p):
            os.remove(p)
