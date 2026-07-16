# -*- coding: utf-8 -*-
"""
매일 누적 실측 자동 갱신 (Stage 9 대체 · 독립 스크립트)
=========================================================
build_test_csv.py로 오늘자 CSV를 만든 뒤 이 스크립트를 실행하면
execution_log.csv의 각 이력을 오늘 재고 기준으로 자동 재측정.

로직:
  · execution_details.csv (승인 시 자동 저장된 SKU×채널 스냅샷) 사용
  · 추가판매(장) = max(0, min(이동IN, 이동IN - 오늘재고))  [1차 채널별 산출]
  · [STRICT CAP] 스타일 단위 총 추가판매(장) > 총 이동후재고 시 → 총 이동후재고로 상한
    (초과분은 매장 옴니출고/분배 효과로 판단, 재배치 순수 효과에서 제외)
  · 실제효과(원) = 캡 적용 후 추가판매(장) × 정상가
  · 상태 = '실측 완료(7일)' (D+7 이후) / '실측 중' (D+1~D+6)
  · '완료'가 이미 포함된 상태(수동/7일)는 건드리지 않음

실행:
  python3 update_execution_actuals.py
"""
from __future__ import annotations
import csv
import gzip
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("update_actuals")

CHANNELS = ["공홈", "이랜드몰", "무신사", "지그재그", "네이버", "카카오선물하기"]
REPO_DIR = Path("/sessions/quirky-dazzling-wozniak/mnt/rebal_web")
DATA_DIR = REPO_DIR / "data" / "test"


def _int(v, d: int = 0) -> int:
    try:
        return 0 if v in (None, "") else int(float(v))
    except Exception:
        return d


def _read_csv_rows(path: Path) -> list:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return list(csv.DictReader(path.read_text(encoding=enc).splitlines()))
        except UnicodeDecodeError:
            continue
    return []


def _find_latest_csv() -> Path | None:
    if not DATA_DIR.exists():
        return None
    files = sorted(DATA_DIR.glob("data_spao_*.csv.gz"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _load_today_stock(csv_path: Path) -> dict:
    stock: dict = {}
    with gzip.open(csv_path, "rt", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = row.get("단품코드", "")
            if not code:
                continue
            stock[code] = {ch: _int(row.get(f"inv_{ch}", 0)) for ch in CHANNELS}
    return stock


def update() -> int:
    log_path = REPO_DIR / "execution_log.csv"
    det_path = REPO_DIR / "execution_details.csv"
    csv_path = _find_latest_csv()

    if not log_path.exists():
        log.warning(f"execution_log.csv 없음: {log_path}")
        return 0
    if not csv_path:
        log.warning(f"data_spao_*.csv.gz 없음: {DATA_DIR}")
        return 0

    log.info(f"실행 이력 자동 누적 실측 시작 (오늘재고: {csv_path.name})")

    rows = _read_csv_rows(log_path)
    dets = _read_csv_rows(det_path)
    if not rows:
        log.info("이력 없음 → skip")
        return 0

    stock_today = _load_today_stock(csv_path)
    log.info(f"오늘재고 SKU: {len(stock_today):,}")

    # details 그룹화
    det_by_id: dict = defaultdict(list)
    for d in dets:
        eid = str(d.get("exec_id", "")).strip()
        if not eid:
            continue
        det_by_id[eid].append({
            "sku": d.get("단품코드", ""),
            "ch": d.get("채널", ""),
            "in_qty": _int(d.get("이동IN_장", 0)),
            "price": _int(d.get("정상가", 0)),
        })

    # ---- STRICT CAP 로직 helper ----
    def _apply_strict_cap(plan: list, stock: dict) -> tuple:
        """스타일 단위 총 추가판매(장) > 총 이동후재고 시 이동후재고로 상한.

        Returns (tot_move, tot_sold, tot_amt, capped_style_count).
        """
        # 1차: SKU x 채널별 raw 추가판매 산출 + 스타일 aggregation
        raw_by_style: dict = defaultdict(lambda: {"add_q": 0, "after": 0, "amt": 0,
                                                   "price": 0, "move": 0, "skus": []})
        for p in plan:
            in_q = p["in_qty"]
            if in_q <= 0:
                continue
            today_q = stock.get(p["sku"], {}).get(p["ch"], 0)
            sold_raw = max(0, min(in_q, in_q - today_q))
            style = str(p["sku"])[:10]
            entry = raw_by_style[style]
            entry["add_q"] += sold_raw
            entry["after"] += today_q
            entry["amt"] += sold_raw * p["price"]
            entry["move"] += in_q
            if entry["price"] == 0 and p["price"] > 0:
                entry["price"] = p["price"]

        tot_move = tot_sold = tot_amt = 0
        capped = 0
        for style, e in raw_by_style.items():
            tot_move += e["move"]
            if e["add_q"] > e["after"]:
                capped += 1
                # 캡: 총 이동후재고로 상한, 매출도 재계산
                tot_sold += e["after"]
                tot_amt += e["after"] * e["price"]
            else:
                tot_sold += e["add_q"]
                tot_amt += e["amt"]
        return tot_move, tot_sold, tot_amt, capped

    today_dt = datetime.now()
    today_str = today_dt.strftime("%Y-%m-%d")
    updated = 0

    for r in rows:
        status = str(r.get("상태") or "").strip()
        if "완료" in status:
            log.info(f"  id={r.get('id')}: 상태 '{status}' → 보존 (skip)")
            continue
        rid = str(r.get("id", "")).strip()
        plan = det_by_id.get(rid, [])
        if not plan:
            log.info(f"  id={rid}: details 없음 → skip")
            continue

        try:
            exec_dt = datetime.strptime(str(r.get("실행일시", ""))[:10], "%Y-%m-%d")
            days = (today_dt.date() - exec_dt.date()).days
        except Exception:
            days = 0

        tot_move, tot_sold, tot_amt, capped = _apply_strict_cap(plan, stock_today)

        r["이동량_장"] = tot_move
        r["추가판매_장"] = tot_sold
        r["실제효과_만원"] = round(tot_amt / 10000)
        r["실측일"] = today_str
        r["상태"] = "실측 완료(7일)" if days >= 7 else "실측 중"
        updated += 1
        log.info(
            f"  id={rid} D+{days}일: 이동 {tot_move:,}장 · "
            f"추가판매 {tot_sold:,}장 · 실제효과 {round(tot_amt/10000):,}만원 · "
            f"CAP {capped}개 스타일 · 상태 '{r['상태']}'"
        )

    if updated == 0:
        log.info("갱신 대상 없음")
        return 0

    fieldnames = ["id", "실행일시", "시나리오", "단품수", "이동량_장",
                  "기대효과_만원", "실제효과_만원", "추가판매_장",
                  "실측일", "상태", "메모"]
    with open(log_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    log.info(f"✓ {updated}건 갱신 완료 → {log_path.name}")
    return updated


if __name__ == "__main__":
    update()
