"""
PriceCharting 시세 CSV 로더.
- config.PC_CSV_PATH 의 CSV를 읽어 pc_prices 테이블에 저장.
- PSA 10 가격 = manual-only-price 컬럼 (config.PC_PSA10_FIELD).
- 실제 PriceCharting CSV 와 동일한 컬럼명을 기대하므로, 결제 후 받은 진짜 CSV를
  그 경로에 두기만 하면 바로 동작합니다.
"""
import csv

import config
import db
from textutil import normalize


def _to_dollars(raw):
    if raw is None or str(raw).strip() == "":
        return None
    try:
        val = float(str(raw).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None
    if config.PC_PRICE_IN_PENNIES:
        val = val / 100.0
    return round(val, 2)


def load_csv(path=None):
    path = path or config.PC_CSV_PATH
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # 컬럼명에 'id' 또는 'product-id' 등 변형이 있을 수 있어 유연하게 처리
        for r in reader:
            pc_id = r.get("id") or r.get("product-id") or r.get("pc_id")
            console = (r.get("console-name") or r.get("console") or "").strip()
            product = (r.get("product-name") or r.get("product") or "").strip()
            psa10 = _to_dollars(r.get(config.PC_PSA10_FIELD))
            if not pc_id or not product:
                continue
            rows.append({
                "pc_id": str(pc_id),
                "console_name": console,
                "product_name": product,
                "search_text": normalize(f"{console} {product}"),
                "psa10_price": psa10,
            })
    db.init_db()
    db.replace_pc_prices(rows)
    return len(rows)


if __name__ == "__main__":
    n = load_csv()
    print(f"loaded {n} PriceCharting rows from {config.PC_CSV_PATH}")
