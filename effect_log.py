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
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    _KST = ZoneInfo("Asia/Seoul")
except Exception:  # 방어적 fallback
    _KST = None


def _now_kst_str(fmt: str = '%Y-%m-%d %H:%M') -> str:
    """KST 기준 현재 시각 문자열. (사용자 7/9 fix — UTC → KST)"""
    if _KST is not None:
        return datetime.now(_KST).strftime(fmt)
    return datetime.now().strftime(fmt)


_DIR = os.path.dirname(__file__)
LOG_PATH = os.path.join(_DIR, 'execution_log.csv')
DETAILS_PATH = os.path.join(_DIR, 'execution_details.csv')

# ── GitHub 영구 저장 설정 (사용자 7/9) ─────────────────────────────────
# execution_log.csv / execution_details.csv를 GitHub 저장소에 자동 commit → 재부팅에도 유지
_GH_OWNER = "kanghg61-del"
_GH_REPO = "spao-rebalance"
_GH_BRANCH = "main"
_GH_LOG_PATH = "execution_log.csv"
_GH_DETAILS_PATH = "execution_details.csv"


def _gh_token():
    try:
        import streamlit as st  # noqa
        t = st.secrets.get('GITHUB_TOKEN')
        if t: return t
    except Exception:
        pass
    return os.environ.get('GITHUB_TOKEN')


def _gh_push_file(remote_path: str, content_bytes: bytes, commit_msg: str) -> tuple[bool, str]:
    """GitHub contents API로 파일 create/update (sha 있으면 update, 없으면 create)."""
    tok = _gh_token()
    if not tok:
        return False, 'no-token'
    try:
        import base64, json, urllib.request
        api = f"https://api.github.com/repos/{_GH_OWNER}/{_GH_REPO}/contents/{remote_path}"
        # 기존 sha 조회
        sha = None
        try:
            req_g = urllib.request.Request(
                f"{api}?ref={_GH_BRANCH}",
                headers={'Authorization': f'token {tok}', 'Accept': 'application/vnd.github+json'},
            )
            with urllib.request.urlopen(req_g, timeout=8) as resp:
                sha = json.loads(resp.read().decode('utf-8')).get('sha')
        except Exception:
            pass
        body = {
            'message': commit_msg,
            'content': base64.b64encode(content_bytes).decode('ascii'),
            'branch': _GH_BRANCH,
        }
        if sha:
            body['sha'] = sha
        req_p = urllib.request.Request(
            api, method='PUT',
            data=json.dumps(body).encode('utf-8'),
            headers={'Authorization': f'token {tok}', 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(req_p, timeout=12) as resp:
            resp.read()
        return True, 'ok'
    except Exception as e:
        return False, str(e)[:120]


def _gh_pull_file(remote_path: str) -> bytes | None:
    """GitHub raw에서 파일 fetch (재부팅 후 최초 load 시 사용)."""
    try:
        import urllib.request
        url = f"https://raw.githubusercontent.com/{_GH_OWNER}/{_GH_REPO}/{_GH_BRANCH}/{remote_path}"
        with urllib.request.urlopen(url, timeout=8) as resp:
            return resp.read()
    except Exception:
        return None


def _ensure_local_from_gh():
    """로컬 파일 없으면 GitHub에서 pull해서 채움 (재부팅 후 최초 load)."""
    for local, remote in ((LOG_PATH, _GH_LOG_PATH), (DETAILS_PATH, _GH_DETAILS_PATH)):
        if not os.path.exists(local):
            data = _gh_pull_file(remote)
            if data:
                try:
                    with open(local, 'wb') as f:
                        f.write(data)
                except Exception:
                    pass
FIELDS = ['id', '실행일시', '시나리오', '단품수', '이동량_장', '기대효과_만원',
          '실제효과_만원', '추가판매_장', '실측일', '상태', '메모']
DETAIL_FIELDS = ['exec_id', '단품코드', '채널', '전일재고_장', '이동IN_장', '정상가',
                 '실제판매_장', '추가판매_장']


def load_log():
    # 사용자 7/9 — GH 영구저장: 로컬 파일 없으면 GitHub에서 pull (재부팅 대응)
    _ensure_local_from_gh()
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def load_details(exec_id=None):
    _ensure_local_from_gh()
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
    # 사용자 7/9 — GitHub 영구 저장 (ch_excl.json과 동일 방식, 실패해도 로컬 저장은 유지)
    try:
        with open(LOG_PATH, 'rb') as f:
            _gh_push_file(_GH_LOG_PATH, f.read(),
                          f'실행 이력 자동 저장 (n={len(rows)}) [{_now_kst_str()}]')
    except Exception:
        pass


def _save_details(rows):
    with open(DETAILS_PATH, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in DETAIL_FIELDS})
    try:
        with open(DETAILS_PATH, 'rb') as f:
            _gh_push_file(_GH_DETAILS_PATH, f.read(),
                          f'실행 상세 자동 저장 (n={len(rows)}) [{_now_kst_str()}]')
    except Exception:
        pass


def log_execution(scenario, sku_count, qty, expected_rev_won, details=None, memo=''):
    """승인 실행 기록. details: [(단품코드, 채널, 전일재고, 이동IN, 정상가)] — IN 발생분만"""
    rows = load_log()
    rid = max([int(r['id']) for r in rows], default=0) + 1
    rows.append({
        'id': rid,
        '실행일시': _now_kst_str('%Y-%m-%d %H:%M'),
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
    today = _now_kst_str('%Y-%m-%d')
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
    today = _now_kst_str('%Y-%m-%d')
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
    """일일 매출 자료(csv/xlsx) → 실측 대기 실행의 실제효과 자동 산출 (당일 매출 기준)"""
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
    today = _now_kst_str('%Y-%m-%d')
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
            sold = by_code_ch.get((code, ch), 0)
            if sold == 0 and by_code.get(code, 0) > 0:
                total_in = in_sum_by_code.get(code, 1) or 1
                sold = int(by_code[code] * (inq / total_in))
            extra = min(inq, max(0, sold - prev))
            d['실제판매_장'] = sold
            d['추가판매_장'] = extra
            extra_total += extra
            won += extra * price
            if sold > 0:
                hit += 1
        if hit > 0:
            lr['실제효과_만원'] = round(won / 10000)
            lr['추가판매_장'] = extra_total
            lr['실측일'] = today
            lr['상태'] = '실측 완료 (매출)'
            n_exec += 1
            matched += hit
    _save(log_rows)
    _save_details(drows)
    return n_exec, matched


def reset_all():
    """전체 이력 초기화 (테스트 용도)."""
    for p in (LOG_PATH, DETAILS_PATH):
        if os.path.exists(p):
            os.remove(p)
    # 빈 헤더 파일 재생성 + GH push
    _save([])
    _save_details([])


# ─────────────────────────────────────────────
# 사용자 7/9 fix — 누락 함수 복원 (파일 재구성 시 누락)
# ─────────────────────────────────────────────
def export_csv_bytes() -> bytes:
    """실행 이력 CSV bytes (백업 다운로드용)."""
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, 'rb') as f:
            return f.read()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    w.writeheader()
    return buf.getvalue().encode('utf-8-sig')


def export_details_bytes() -> bytes:
    """실행 상세 CSV bytes (백업 다운로드용)."""
    if os.path.exists(DETAILS_PATH):
        with open(DETAILS_PATH, 'rb') as f:
            return f.read()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=DETAIL_FIELDS)
    w.writeheader()
    return buf.getvalue().encode('utf-8-sig')


def restore_from_bytes(data: bytes) -> int:
    """CSV bytes에서 이력 복원."""
    text = data.decode('utf-8-sig', errors='replace')
    rows = list(csv.DictReader(io.StringIO(text)))
    if rows:
        _save(rows)
    return len(rows)


def clear_log() -> None:
    """이력 초기화 (로컬 + GH push)."""
    _save([])
    _save_details([])
