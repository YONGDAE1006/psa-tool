"""
eBay 실낙찰가(sold) 자동 조회 — 130point/PSA APR 수동 확인을 자동화하는 부분.

공급자(provider)를 갈아끼울 수 있는 구조:
  - demo                : 가짜 실낙찰가 (키 없이 전체 흐름 확인)
  - pokemonpricetracker : PokemonPriceTracker API (eBay 실낙찰가 PSA10)
  - ebay_insights       : (확장 슬롯) eBay Marketplace Insights API

반환: dict {median, avg, n, source, days}  또는  None(데이터 없음)

무료 등급 크레딧 절약:
  - 카드ID(tcgPlayerId)는 영구 캐시(id_cache) → 한 번 찾으면 검색 크레딧 안 씀.
  - 시세 결과는 sold_cache 에 SOLD_CACHE_HOURS 동안 캐시.
  - 1회 수집당 새 조회는 SOLD_LOOKUP_LIMIT 건으로 제한.
"""
import hashlib
import re

import requests
from rapidfuzz import fuzz

import config
import db
from textutil import extract_card_number

_session = requests.Session()

# 이번 수집에서 '새로' 조회할 수 있는 남은 횟수 (무료 등급 보호). None = 무제한.
_budget = None


def set_budget(n):
    global _budget
    _budget = n


# PPT 검색을 방해하는 단어/표기 제거 (등급·마케팅·별명 등)
_PPT_NOISE = re.compile(
    r"\b(psa|bgs|cgc|sgc|gem|mint|graded|grade|holo|holographic|reverse|rare|"
    r"secret|alt|alternate|art|full|sir|sar|shiny|promo|japanese|english|jpn|"
    r"moonbreon|wotc|card|cards|tcg|pokemon|pokémon|lot|nm|near)\b",
    re.I,
)


def _ppt_query(text):
    """PPT 검색용 깔끔한 문자열 (예: 'Evolving Skies Umbreon VMAX')."""
    t = text or ""
    t = re.sub(r"\d+\s*/\s*\d+", " ", t)   # 215/203 같은 표기 제거(검색 방해)
    t = re.sub(r"#\s*\w+", " ", t)
    t = _PPT_NOISE.sub(" ", t)
    t = re.sub(r"\b\d{1,4}\b", " ", t)     # 남은 숫자 제거
    t = re.sub(r"[^A-Za-z0-9 ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def get_sold(query, demo_hint=None, tcgplayer_id=None, title=None, cache_only=False):
    """cache_only=True 면 새 API 호출 없이 캐시에 있을 때만 반환(크레딧 0)."""
    global _budget
    provider = config.SOLD_PROVIDER

    # demo는 무료·즉시 (cache_only 무관)
    if provider == "demo":
        try:
            return _demo(query, demo_hint)
        except Exception:
            return None

    # 캐시 키: 카드 식별이 안정적인 PPT 검색문자열 (같은 카드의 다른 매물끼리 캐시 공유)
    key = _ppt_query(title or query) or (query or "").strip()
    if not key:
        return None

    cached = db.get_sold_cache(key, config.SOLD_CACHE_HOURS)
    if cached is not None:
        return cached if cached["n"] else None

    # 입찰 적은 매물 등은 캐시에 없으면 크레딧을 쓰지 않고 포기
    if cache_only:
        return None

    if _budget is not None and _budget <= 0:
        return None

    try:
        if provider == "pokemonpricetracker":
            data = _ppt(key, tcgplayer_id)
        elif provider == "ebay_insights":
            data = _ebay_insights(key)
        else:
            data = None
    except Exception:
        data = None

    if _budget is not None:
        _budget -= 1

    if data:
        db.save_sold_cache(key, data)
        return data
    db.save_sold_cache(key, {"median": None, "avg": None, "n": 0, "source": provider})
    return None


# ---------------- DEMO ----------------
def _demo(query, demo_hint):
    seed = int(hashlib.md5((query or "").encode("utf-8")).hexdigest(), 16)
    r = seed % 1000 / 1000.0
    n = seed % 17
    if demo_hint:
        median = round(demo_hint * (0.82 + 0.30 * r), 2)
    else:
        median = round(20 + 480 * r, 2)
    if n == 0:
        return None
    # 데모용 추세/신뢰도/역대시세 (일부는 '하락+역대보다 낮음'=위험으로 시연)
    confidence = "high" if n >= 6 else ("medium" if n >= 3 else "low")
    if r < 0.35:
        trend, all_time = "down", round(median * 1.7, 2)   # 고점 대비 급락(위험)
    elif r > 0.6:
        trend, all_time = "up", round(median * 1.05, 2)
    else:
        trend, all_time = "flat", round(median * 1.1, 2)
    import datetime as _dt
    days_used = 7 if confidence == "high" else (30 if confidence == "medium" else 90)
    updated = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=seed % 20)).isoformat()
    return {"median": median, "avg": round(median * (0.98 + 0.06 * r), 2),
            "n": n, "all_time": all_time, "trend": trend, "confidence": confidence,
            "days_used": days_used, "updated": updated,
            "sales_week": round(0.5 + 6 * r, 1),
            "matched_name": None, "source": "demo", "days": config.SOLD_DAYS}


# ---------------- PokemonPriceTracker ----------------
def _headers():
    return {"Authorization": f"Bearer {config.PPT_API_KEY}"}


def _ppt(clean_query, tcgplayer_id):
    if not config.PPT_API_KEY:
        return None
    base = config.PPT_BASE_URL.rstrip("/")

    if not tcgplayer_id:
        tcgplayer_id = _ppt_resolve_id(clean_query, base)
    if not tcgplayer_id:
        return None

    r = _session.get(
        f"{base}/cards", headers=_headers(),
        params={"tcgPlayerId": tcgplayer_id, "includeEbay": "true", "days": config.SOLD_DAYS},
        timeout=30,
    )
    r.raise_for_status()
    data = (r.json() or {}).get("data")
    d = (data[0] if isinstance(data, list) else data) or {}
    ebay = d.get("ebay") or {}
    grades = ebay.get("salesByGrade") or {}
    psa10 = grades.get("psa10") or {}
    n = psa10.get("count")
    smart = psa10.get("smartMarketPrice") or {}
    # 현재 시세 = 스마트시세(최근 가중) 우선, 없으면 최근7일 중앙값, 그것도 없으면 역대 중앙값
    current = smart.get("price") or psa10.get("marketPriceMedian7Day") or psa10.get("medianPrice")
    if not n or current is None:
        return None
    # 어떤 카드의 시세를 가져왔는지(검증용)
    nm = " ".join(str(x) for x in [d.get("name"), d.get("cardNumber")] if x).strip()
    if d.get("setName"):
        nm = f"{nm} · {d.get('setName')}"
    return {
        "median": float(current),                       # 현재 시세
        "avg": float(psa10.get("averagePrice", current)),
        "n": int(n),
        "all_time": float(psa10["medianPrice"]) if psa10.get("medianPrice") is not None else None,
        "trend": psa10.get("marketTrend") or "flat",
        "confidence": smart.get("confidence") or "n/a",
        "days_used": smart.get("daysUsed"),
        "updated": ebay.get("updatedAt") or ebay.get("lastEbayCheck"),
        "sales_week": round((psa10.get("dailyVolume7Day") or 0) * 7, 1),
        "matched_name": nm or None,
        "source": "pokemonpricetracker",
        "days": config.SOLD_DAYS,
    }


def _ppt_resolve_id(clean_query, base):
    """clean_query -> tcgPlayerId. id_cache 우선(영구), 없으면 검색 후 저장."""
    cached = db.get_id_cache(clean_query)
    if cached:
        return cached
    r = _session.get(
        f"{base}/cards", headers=_headers(),
        params={"search": clean_query, "limit": 3}, timeout=30,
    )
    r.raise_for_status()
    items = (r.json() or {}).get("data") or []
    if not isinstance(items, list) or not items:
        return None
    # 후보 중 검색문자열과 가장 잘 맞는 것 선택
    q_num = extract_card_number(clean_query)
    best, best_score = None, -1
    for it in items:
        cand = f"{it.get('setName','')} {it.get('name','')}"
        score = fuzz.token_set_ratio(clean_query, cand)
        cnum = (it.get("cardNumber") or "").split("/")[0].lower()
        if q_num and cnum and q_num.lower() == cnum:
            score += 15
        if score > best_score:
            best_score, best = score, it
    tid = best.get("tcgPlayerId") if best else None
    if tid:
        db.save_id_cache(clean_query, tid)
    return tid


# ---------------- eBay Marketplace Insights (확장 슬롯) ----------------
def _ebay_insights(query):
    return None
