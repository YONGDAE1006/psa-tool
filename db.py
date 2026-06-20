"""
SQLite 저장소.
- pc_prices : PriceCharting 시세표 (CSV에서 로드)
- listings  : eBay에서 수집 + 매칭 + 마진계산까지 끝난 매물 (수집할 때마다 새로 채움)
"""
import sqlite3
from contextlib import contextmanager
import config


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pc_prices (
                pc_id        TEXT PRIMARY KEY,
                console_name TEXT,
                product_name TEXT,
                search_text  TEXT,   -- 매칭용으로 정규화한 문자열
                psa10_price  REAL    -- 달러 단위
            );

            CREATE TABLE IF NOT EXISTS listings (
                item_id      TEXT PRIMARY KEY,
                title        TEXT,
                url          TEXT,
                image        TEXT,
                end_time     TEXT,   -- ISO8601 (UTC)
                currency     TEXT,
                current_bid  REAL,
                bid_count    INTEGER,
                is_steal     INTEGER,
                shipping     REAL,
                item_country TEXT,
                seller_name  TEXT,
                seller_feedback INTEGER,
                seller_pct   REAL,
                pc_id        TEXT,
                pc_name      TEXT,
                pc_console   TEXT,
                psa10_price  REAL,   -- PriceCharting 추정 시세
                sold_median  REAL,   -- eBay 현재(스마트) 시세
                sold_n       INTEGER,-- 집계된 낙찰 건수
                sold_source  TEXT,   -- 실낙찰가 출처
                value_trend  TEXT,   -- 시세 추세 up/down/flat
                value_confidence TEXT,-- 시세 신뢰도
                matched_name TEXT,   -- 시세를 가져온 카드(검증용)
                card_image   TEXT,   -- 공식 카드 이미지(TCGplayer)
                value_days   INTEGER,-- 시세 기준 기간(일)
                value_updated TEXT,  -- 시세 갱신 시각
                sales_week   REAL,   -- 주당 판매량(환금성)
                all_time_value REAL, -- 역대 중앙값(거품 판단용)
                market_value REAL,   -- 실제 ROI 계산에 쓴 시세(위험 보정 반영)
                value_source TEXT,   -- 'sold'(실낙찰가) / 'estimate'(추정가)
                match_score  INTEGER,
                cost         REAL,   -- 현재가 + 배송비
                net_resale   REAL,   -- 재판매 시 수수료 뗀 실수령액
                profit       REAL,   -- net_resale - cost
                roi          REAL,   -- profit / cost
                breakeven_bid REAL,  -- 이 입찰가 넘으면 손해
                max_bid      REAL,   -- 권장 최대 입찰가(목표 수익 남김)
                collected_at TEXT
            );

            CREATE TABLE IF NOT EXISTS sold_cache (
                query      TEXT PRIMARY KEY,
                median     REAL,     -- 현재 시세(스마트)
                avg        REAL,
                n          INTEGER,
                all_time   REAL,     -- 역대 중앙값
                trend      TEXT,     -- up/down/flat
                confidence TEXT,     -- low/medium/high
                days_used  INTEGER,  -- 시세 산정에 쓴 기간(일)
                updated    TEXT,     -- 시세 데이터 갱신 시각
                sales_week REAL,     -- 주당 판매량(환금성)
                matched_name TEXT,   -- 시세를 가져온 카드(검증용)
                num_confirmed INTEGER,-- 1=제목 카드번호로 매칭 확정, 0/NULL=미확정
                card_image TEXT,     -- 공식 카드 이미지(TCGplayer)
                source     TEXT,
                fetched_at TEXT      -- ISO8601 UTC
            );
            """
        )
        # 마이그레이션: 구버전 sold_cache 에 num_confirmed 컬럼이 없으면 추가
        try:
            conn.execute("ALTER TABLE sold_cache ADD COLUMN num_confirmed INTEGER")
        except sqlite3.OperationalError:
            pass
        # 마이그레이션: 구버전 listings 에 셀러/이미지 컬럼 추가
        for col, typ in (("seller_name", "TEXT"), ("seller_feedback", "INTEGER"),
                         ("seller_pct", "REAL"), ("card_image", "TEXT")):
            try:
                conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute("ALTER TABLE sold_cache ADD COLUMN card_image TEXT")
        except sqlite3.OperationalError:
            pass


def get_sold_cache(query, max_age_hours):
    """캐시가 신선하면 dict 반환, 아니면 None."""
    import datetime as _dt
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sold_cache WHERE query = ?", (query,)
        ).fetchone()
    if not row:
        return None
    try:
        fetched = _dt.datetime.fromisoformat(row["fetched_at"])
    except (ValueError, TypeError):
        return None
    age = (_dt.datetime.now(_dt.timezone.utc) - fetched).total_seconds()
    if age > max_age_hours * 3600:
        return None
    return {"median": row["median"], "avg": row["avg"], "n": row["n"],
            "all_time": row["all_time"], "trend": row["trend"],
            "confidence": row["confidence"], "days_used": row["days_used"],
            "updated": row["updated"], "sales_week": row["sales_week"],
            "matched_name": row["matched_name"],
            "num_confirmed": row["num_confirmed"],
            "card_image": row["card_image"],
            "source": row["source"], "days": None}


def save_sold_cache(query, data):
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO sold_cache
               (query, median, avg, n, all_time, trend, confidence, days_used, updated,
                sales_week, matched_name, num_confirmed, card_image, source, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (query, data["median"], data.get("avg"), data["n"], data.get("all_time"),
             data.get("trend"), data.get("confidence"), data.get("days_used"),
             data.get("updated"), data.get("sales_week"), data.get("matched_name"),
             1 if data.get("num_confirmed") else 0, data.get("card_image"),
             data["source"], now),
        )


def get_id_cache(key):
    """카드 식별자(tcgPlayerId) 영구 캐시 조회. 한 번 찾으면 검색 크레딧 절약."""
    with get_conn() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS id_cache (
                   key TEXT PRIMARY KEY, tcgplayer_id TEXT, resolved_at TEXT)"""
        )
        row = conn.execute("SELECT tcgplayer_id FROM id_cache WHERE key = ?", (key,)).fetchone()
    return row["tcgplayer_id"] if row else None


def save_id_cache(key, tcgplayer_id):
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS id_cache (
                   key TEXT PRIMARY KEY, tcgplayer_id TEXT, resolved_at TEXT)"""
        )
        conn.execute(
            "INSERT OR REPLACE INTO id_cache (key, tcgplayer_id, resolved_at) VALUES (?, ?, ?)",
            (key, tcgplayer_id, now),
        )


def replace_pc_prices(rows):
    """rows: dict 리스트. 전체를 갈아끼움."""
    with get_conn() as conn:
        conn.execute("DELETE FROM pc_prices")
        conn.executemany(
            """INSERT OR REPLACE INTO pc_prices
               (pc_id, console_name, product_name, search_text, psa10_price)
               VALUES (:pc_id, :console_name, :product_name, :search_text, :psa10_price)""",
            rows,
        )


def get_all_pc_prices():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM pc_prices")]


def replace_listings(rows):
    with get_conn() as conn:
        conn.execute("DELETE FROM listings")
        if rows:
            cols = list(rows[0].keys())
            placeholders = ", ".join(f":{c}" for c in cols)
            conn.executemany(
                f"INSERT OR REPLACE INTO listings ({', '.join(cols)}) VALUES ({placeholders})",
                rows,
            )


def is_notified(item_id):
    with get_conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS notified (item_id TEXT PRIMARY KEY, at TEXT)")
        return conn.execute(
            "SELECT 1 FROM notified WHERE item_id = ?", (item_id,)).fetchone() is not None


def mark_notified(item_id):
    import datetime as _dt
    with get_conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS notified (item_id TEXT PRIMARY KEY, at TEXT)")
        conn.execute("INSERT OR REPLACE INTO notified (item_id, at) VALUES (?, ?)",
                     (item_id, _dt.datetime.now(_dt.timezone.utc).isoformat()))


def get_listings():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM listings ORDER BY end_time ASC"
        )]


# ---------- 거래 기록 (투자 복기용 데이터) ----------
def _ensure_trades(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS trades (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               created_at TEXT, card TEXT, buy REAL, sell REAL, note TEXT)"""
    )


def add_trade(card, buy, sell, note):
    import datetime as _dt
    with get_conn() as conn:
        _ensure_trades(conn)
        conn.execute(
            "INSERT INTO trades (created_at, card, buy, sell, note) VALUES (?, ?, ?, ?, ?)",
            (_dt.datetime.now().strftime("%Y-%m-%d"), card, buy, sell, note),
        )


def get_trades():
    with get_conn() as conn:
        _ensure_trades(conn)
        return [dict(r) for r in conn.execute("SELECT * FROM trades ORDER BY id DESC")]


def delete_trade(trade_id):
    with get_conn() as conn:
        _ensure_trades(conn)
        conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))


# ---------- 입찰 기록(Gixen 스나이핑 결과 추적) ----------
def _ensure_bidlog(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS bid_log (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               created_at TEXT, item_id TEXT, card TEXT,
               my_bid REAL, final_price REAL, market_value REAL, shipping REAL,
               net_if_won REAL, result TEXT, note TEXT)"""
    )
    for col, typ in (("shipping", "REAL"), ("net_if_won", "REAL")):
        try:
            conn.execute(f"ALTER TABLE bid_log ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass


def _net_if_won(market_value, final_price, shipping):
    """이 가격에 낙찰했다면 되팔아 남는 실제 수익(수수료+배송 반영). 음수=손해."""
    if market_value is None or final_price is None:
        return None
    fee, flat = (0.13, 3.0) if market_value < 100 else \
        (0.13, 0.0) if market_value < 500 else \
        (0.12, 0.0) if market_value < 1000 else \
        (0.10, 0.0) if market_value < 2500 else \
        (0.09, 0.0) if market_value < 5000 else (0.07, 0.0)
    net_resale = market_value * (1 - fee) - flat
    return round(net_resale - (final_price + (shipping or 0)), 2)


def add_bid(card, my_bid, final_price, market_value, result,
            item_id="", note="", shipping=0.0, when=None):
    import datetime as _dt
    net = _net_if_won(market_value, final_price, shipping)
    with get_conn() as conn:
        _ensure_bidlog(conn)
        conn.execute(
            """INSERT INTO bid_log
               (created_at, item_id, card, my_bid, final_price, market_value,
                shipping, net_if_won, result, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (when or _dt.datetime.now().strftime("%Y-%m-%d"), item_id, card,
             my_bid, final_price, market_value, shipping, net, result, note),
        )


def get_bids():
    with get_conn() as conn:
        _ensure_bidlog(conn)
        return [dict(r) for r in conn.execute("SELECT * FROM bid_log ORDER BY id DESC")]


def delete_bid(bid_id):
    with get_conn() as conn:
        _ensure_bidlog(conn)
        conn.execute("DELETE FROM bid_log WHERE id = ?", (bid_id,))


# ---------- Gixen 등록 체크(새로고침/재시작에도 유지) ----------
def _ensure_gixen(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS gixen_marks (item_id TEXT PRIMARY KEY, at TEXT)")


def get_gixen_marks():
    with get_conn() as conn:
        _ensure_gixen(conn)
        return {row["item_id"] for row in conn.execute("SELECT item_id FROM gixen_marks")}


def set_gixen_mark(item_id, on=True):
    import datetime as _dt
    with get_conn() as conn:
        _ensure_gixen(conn)
        if on:
            conn.execute("INSERT OR REPLACE INTO gixen_marks (item_id, at) VALUES (?, ?)",
                         (item_id, _dt.datetime.now(_dt.timezone.utc).isoformat()))
        else:
            conn.execute("DELETE FROM gixen_marks WHERE item_id = ?", (item_id,))
