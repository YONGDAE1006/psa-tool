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
import datetime as _dt
import hashlib
import re
import statistics
import time
import unicodedata

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
    r"\b(psa|bgs|cgc|sgc|gem|mint|mt|graded|grade|holo|holographic|reverse|rare|"
    r"secret|alt|alternate|art|full|sir|sar|shiny|promo|japanese|english|jpn|en|"
    r"moonbreon|wotc|card|cards|tcg|pokemon|pokémon|lot|nm|near|condition|regular|"
    r"potential|hyper|ultra|pt|swirl|with|new|other|read|desc|foil|"
    r"the|company|official|genuine|authentic|vintage|seller|edition|set)\b",
    re.I,
)


def _ppt_query(text):
    """PPT 검색용 깔끔한 문자열 (긴 제목에서 카드 이름만 추출)."""
    t = text or ""
    # 악센트 정규화 (Pokémon -> Pokemon)
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"\d+\s*/\s*\d+", " ", t)   # 215/203 같은 번호 제거
    t = re.sub(r"#\s*\w+", " ", t)         # #125, #SV49 제거
    t = re.sub(r"[^A-Za-z0-9 ]", " ", t)
    t = re.sub(r"\b\w*\d\w*\b", " ", t)    # 숫자가 든 토큰 전부 제거(133554679, swsh11, 2023 등)
    t = _PPT_NOISE.sub(" ", t)
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

    # 카드 이름(노이즈 제거) + 카드번호(#183 등)로 식별.
    # 검색·캐시 모두 '이름+번호'로 묶어야 동명이카드(번호만 다른 카드) 혼선/캐시충돌 방지.
    name = _ppt_query(title or query) or (query or "").strip()
    if not name:
        return None
    card_number = extract_card_number(title or query or "")
    key = f"{name} #{card_number}" if card_number else name

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
            data = _ppt(name, card_number, tcgplayer_id)
        elif provider == "ebay_insights":
            data = _ebay_insights(name)
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
def _recent_median(price_history, days):
    """priceHistory(psa10, {날짜:{average,count}})에서 최근 days일 거래의 중앙값.
    상승추세 카드가 90일가중에 저평가될 때 보정용. 표본 적어 단순 중앙값."""
    if not isinstance(price_history, dict) or not price_history:
        return None
    cut = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)
    vals = []
    for ds, e in price_history.items():
        try:
            d = _dt.datetime.fromisoformat(ds).replace(tzinfo=_dt.timezone.utc)
        except (ValueError, TypeError):
            continue
        if d >= cut and e.get("average") and e.get("count"):
            vals.append(float(e["average"]))
    return round(statistics.median(vals), 2) if vals else None


def _norm_num(s):
    """카드번호 정규화: 앞자리 0 제거 + 소문자. '027'->'27', '#006'->'6', 'GG55'->'gg55'.
    (eBay 제목은 '#027', PPT는 '27'로 저장 → 정규화 안 하면 같은 카드인데 불일치로 오제외)"""
    s = (s or "").strip().lower()
    m = re.match(r"([a-z]*)0*(\d+)", s)
    return (m.group(1) + m.group(2)) if m else s


# 여러 무료 키 순환: 현재 키가 429(일일한도 초과)면 다음 키로 넘어가 재시도.
_key_idx = 0


def _ppt_get(url, params):
    """PPT GET. 429를 구분 처리:
       - 일일한도(Daily-Remaining=0) → 다음 키로 전환
       - 분당한도 → 잠깐 쉬었다 같은 키 재시도
       그 외 일시적 오류(401/403/5xx/네트워크)도 짧게 재시도. 끝내 실패 시 None."""
    global _key_idx
    keys = config.PPT_API_KEYS
    if not keys:
        return None
    n = len(keys)
    minute_waits = 0
    transient = 0
    for _ in range(n + 6):            # 키 순회 + 재시도 여유
        ki = _key_idx % n
        try:
            r = _session.get(
                url, headers={"Authorization": f"Bearer {keys[ki]}"},
                params=params, timeout=30,
            )
        except requests.RequestException:
            transient += 1
            if transient > 3:
                return None
            time.sleep(1.0)
            continue
        if r.status_code == 429:
            if r.headers.get("X-Ratelimit-Daily-Remaining") == "0":
                _key_idx = (ki + 1) % n        # 오늘치 소진 → 다음 키
                continue
            if minute_waits < 6:               # 분당한도 → 잠깐 쉬고 같은 키
                minute_waits += 1
                time.sleep(2.0)
                continue
            return None
        if r.status_code in (401, 403, 500, 502, 503):
            transient += 1                     # 일시적 → 짧게 재시도
            if transient > 3:
                return None
            time.sleep(1.0)
            continue
        r.raise_for_status()
        return r
    return None


def _ppt(name, card_number, tcgplayer_id):
    if not config.PPT_API_KEYS:
        return None
    base = config.PPT_BASE_URL.rstrip("/")

    num_confirmed = bool(tcgplayer_id)        # 외부에서 명시한 id면 신뢰
    if not tcgplayer_id:
        tcgplayer_id, num_confirmed = _ppt_resolve_id(name, card_number, base)
    if not tcgplayer_id:
        return None

    r = _ppt_get(
        f"{base}/cards",
        {"tcgPlayerId": tcgplayer_id, "includeEbay": "true", "days": config.SOLD_DAYS},
    )
    if r is None:
        return None
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
    current = float(current)
    # 상승추세인데 90일가중(smart)이 최근 거래를 못 따라가면(얇은카드 흔함)
    # priceHistory 최근 30일 중앙값으로 보정. 단 스파이크 방지로 상한 배수까지만.
    if (psa10.get("marketTrend") or "flat") == "up":
        recent = _recent_median((ebay.get("priceHistory") or {}).get("psa10") or {}, 30)
        if recent and recent > current:
            current = min(recent, current * config.MAX_RECENT_MULT)
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
        "num_confirmed": num_confirmed,
        "card_image": d.get("imageCdnUrl400") or d.get("imageCdnUrl"),  # 공식 카드 이미지(TCGplayer)
        "source": "pokemonpricetracker",
        "days": config.SOLD_DAYS,
    }


def _ppt_resolve_id(name, card_number, base):
    """이름(+카드번호) -> (tcgPlayerId, num_confirmed).

    - 번호가 있으면 '이름 번호'로 검색(예: 'Charizard ex 183') → 그 카드 1건을 정확히 집고
      PPT cardNumber 일치로 확정(num_confirmed=True).
    - 제목에 번호가 있는데 어떤 후보와도 번호가 안 맞으면 (None, False)
      = 엉뚱한 카드를 가져오느니 차라리 버린다(오매칭 방지).
    - 번호가 없으면 이름 유사도로만 고르되 미확정(False)으로 표시.
    """
    qn = _norm_num(card_number)                 # 비교/캐시용 정규화 번호('027'->'27')
    cache_key = f"{name} #{qn}" if qn else name
    cached = db.get_id_cache(cache_key)
    if cached:
        return cached, bool(qn)

    def cnum(it):
        return _norm_num((it.get("cardNumber") or "").split("/")[0])

    def pick(items):
        """결과 중 이름 유사도+번호일치로 최선 선택. 반환 (best, matched)."""
        best, best_score, matched = None, -1.0, False
        for it in items or []:
            cand = f"{it.get('setName','')} {it.get('name','')}"
            score = fuzz.token_set_ratio(name, cand)
            c = cnum(it)
            if qn and c:
                if qn == c:
                    score += 50          # 번호 일치 = 강한 우선
                    matched = True
                else:
                    score -= 30          # 번호 불일치 = 강한 페널티
            if score > best_score:
                best_score, best = score, it
        return best, matched

    def fetch(q, limit):
        r = _ppt_get(f"{base}/cards", {"search": q, "limit": limit})
        return ((r.json() or {}).get("data") or []) if r is not None else []

    # 1차: 이름만으로 검색(recall 좋음. 번호를 붙이면 PPT가 0건 주는 카드 多) → 번호로 확정.
    # limit=10(=10크레딧). 흔한 이름이라 정답이 top10 밖이면 아래 2차 폴백이 받쳐줌.
    best, matched = pick(fetch(name, 10))

    # 2차 폴백: 번호가 있는데 1차에서 번호일치 못 찾음(이름이 흔해 limit 밖이거나 1차 0건)
    #          → '이름 번호'로 좁혀 재검색(번호검색은 결과 적어 limit=5로 충분).
    if qn and not matched:
        b2, m2 = pick(fetch(f"{name} {card_number}".strip(), 5))
        if m2:
            best, matched = b2, True

    # 제목에 번호가 있는데 끝내 일치 못 찾으면 = 엉뚱한 카드 위험 → 포기(오매칭 방지)
    if qn and not matched:
        return None, False
    tid = best.get("tcgPlayerId") if best else None
    if tid:
        db.save_id_cache(cache_key, tid)
    return tid, (matched if qn else False)


# ---------------- eBay Marketplace Insights (확장 슬롯) ----------------
def _ebay_insights(query):
    return None
