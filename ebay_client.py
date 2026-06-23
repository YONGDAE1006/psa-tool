"""
eBay 매물 수집기.

- live 모드: 공식 Browse API 로 "pokemon psa 10" 경매를 종료임박순으로 가져옴.
    * sort=endingSoonest, filter=buyingOptions:{AUCTION}
- demo 모드: 가짜 매물 생성 (키 없이 전체 흐름 확인용).

반환 형식(공통): 아래 키를 가진 dict 리스트
    item_id, title, url, image, end_time(ISO8601 UTC),
    currency, current_bid, bid_count, shipping
"""
import base64
import datetime as dt
import random
import re
import time

import requests

import config

_token_cache = {"token": None, "exp": 0}


def _get_oauth_token():
    """client_credentials 방식으로 application 토큰 발급 (2시간 유효)."""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["exp"] - 60:
        return _token_cache["token"]

    creds = f"{config.EBAY_CLIENT_ID}:{config.EBAY_CLIENT_SECRET}".encode()
    headers = {
        "Authorization": "Basic " + base64.b64encode(creds).decode(),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    }
    r = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers=headers, data=data, timeout=30,
    )
    r.raise_for_status()
    j = r.json()
    _token_cache["token"] = j["access_token"]
    _token_cache["exp"] = now + int(j.get("expires_in", 7200))
    return _token_cache["token"]


# eBay 정형필드(localizedAspects) → 내부 키 매핑. 매칭 정확도용(제목 추측 대체).
_ASPECT_MAP = {
    "card name": "name", "card": "name", "character": "character",
    "set": "set", "card number": "number",
    "grade": "grade", "card condition": "grade", "card grade": "grade",
    "certification number": "cert", "professional grader": "grader",
    "language": "language",
}


def fetch_item_aspects(item_id):
    """getItem 으로 카드 정형정보(Card Name/Set/Card Number/Grade/Cert/Language) 조회.
    셀러가 입력한 구조화 필드라 제목 파싱보다 정확. 실패/미지원 시 {} 반환."""
    if config.MODE != "live" or config.EBAY_PROVIDER != "official" or not item_id:
        return {}
    try:
        token = _get_oauth_token()
        r = requests.get(
            f"https://api.ebay.com/buy/browse/v1/item/{item_id}",
            headers={"Authorization": f"Bearer {token}",
                     "X-EBAY-C-MARKETPLACE-ID": config.EBAY_MARKETPLACE},
            timeout=30,
        )
        if r.status_code != 200:
            return {}
        out = {}
        for a in (r.json().get("localizedAspects") or []):
            key = _ASPECT_MAP.get((a.get("name") or "").strip().lower())
            val = (a.get("value") or "").strip()
            if key and val and key not in out:
                out[key] = val
        return out
    except requests.RequestException:
        return {}


def _fetch_live():
    token = _get_oauth_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": config.EBAY_MARKETPLACE,
    }
    # 수취지 ZIP을 알려주면 '계산식 배송비'가 그 목적지 기준으로 채워짐(없으면 일부 매물 배송비 빔).
    if config.EBAY_SHIP_ZIP:
        headers["X-EBAY-C-ENDUSERCTX"] = (
            f"contextualLocation=country%3DUS%2Czip%3D{config.EBAY_SHIP_ZIP}"
        )
    # 경매만 + (설정 시) 미국 내 매물만
    filt = "buyingOptions:{AUCTION}"
    if config.ITEM_LOCATION_COUNTRY:
        filt += f",itemLocationCountry:{config.ITEM_LOCATION_COUNTRY}"

    results = []
    offset = 0
    while len(results) < config.SEARCH_LIMIT:
        params = {
            "q": config.SEARCH_QUERY,
            "filter": filt,
            "sort": "endingSoonest",
            "limit": min(200, config.SEARCH_LIMIT - len(results)),
            "offset": offset,
        }
        r = requests.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers=headers, params=params, timeout=30,
        )
        r.raise_for_status()
        j = r.json()
        items = j.get("itemSummaries", []) or []
        if not items:
            break
        for it in items:
            results.append(_normalize_live_item(it))
        offset += len(items)
        if offset >= j.get("total", 0):
            break
    return results


def _normalize_live_item(it):
    # 경매 현재가: currentBidPrice 우선, 없으면 price
    bid = it.get("currentBidPrice") or it.get("price") or {}
    cur = bid.get("currency", "USD")
    # 배송비
    shipping = config.DEFAULT_SHIPPING
    for opt in it.get("shippingOptions", []) or []:
        cost = opt.get("shippingCost")
        if cost and cost.get("value") is not None:
            shipping = float(cost["value"])
            break
    seller = it.get("seller") or {}
    return {
        "item_id": it.get("itemId", ""),
        "title": it.get("title", ""),
        "url": it.get("itemWebUrl", ""),
        "image": (it.get("image") or {}).get("imageUrl", ""),
        "end_time": it.get("itemEndDate", ""),
        "currency": cur,
        "current_bid": float(bid.get("value", 0) or 0),
        "bid_count": int(it.get("bidCount", 0) or 0),
        "shipping": shipping,
        "item_country": (it.get("itemLocation") or {}).get("country", ""),
        "seller_name": seller.get("username", ""),
        "seller_feedback": int(seller.get("feedbackScore") or 0),
        "seller_pct": float(seller.get("feedbackPercentage") or 0),
    }


# ----------------- DEMO 데이터 -----------------
# (제목, 현재가, 입찰수, 배송비, 소재국). 일부는 일부러 이득/손해/필터대상으로 구성.
_DEMO = [
    ("2016 Pokemon XY Evolutions Charizard 11/108 PSA 10 GEM MINT", 95.0, 22, 4.5, "US"),
    ("Pokemon Evolving Skies Umbreon VMAX 215/203 Alt Art PSA 10 Moonbreon", 410.0, 41, 0, "US"),
    ("Pokemon Hidden Fates Charizard GX SV49/SV94 Shiny PSA 10", 88.0, 14, 5.0, "US"),
    ("Champions Path Charizard VMAX 074/073 Secret Rare PSA 10", 240.0, 9, 4.0, "US"),
    ("Pokemon 151 Charizard ex 199/165 SAR PSA 10 Japanese", 70.0, 19, 18.0, "JP"),   # 일본+고배송 → 제외
    ("Pokemon Crown Zenith Giratina VSTAR 212/159 PSA 10", 95.0, 7, 6.0, "US"),
    ("Brilliant Stars Charizard V 154/172 Alternate Art PSA 10", 45.0, 31, 0, "US"),
    ("Pokemon Lost Origin Giratina V 186/196 Alt Art PSA 10", 52.0, 12, 5.0, "US"),
    ("Silver Tempest Lugia V 186/195 Alt Art Full Art PSA 10", 60.0, 16, 4.5, "US"),
    ("Celebrations Charizard 4/25 Classic Collection PSA 10", 70.0, 5, 15.0, "US"),    # 배송비 $15 → 제외
    ("Pokemon Base Set Charizard 4/102 Unlimited PSA 10 WOTC", 5200.0, 28, 8.0, "US"),
    ("Surging Sparks Pikachu ex 238/191 SIR PSA 10", 80.0, 11, 7.99, "US"),
    ("Random Energy Card Common Bulk PSA 10 lot", 3.0, 1, 3.0, "US"),
    ("Pokemon Evolving Skies Rayquaza VMAX 218/203 Alt Art PSA 10", 130.0, 24, 5.0, "US"),
    # 입찰 3건(필터 미달)이지만 시세 대비 매우 싸서 🔥스틸로 예외 표시되어야 함
    ("Pokemon Lost Origin Giratina V 186/196 Alt Art PSA 10", 20.0, 3, 5.0, "US"),
]


def _fetch_demo():
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for i, (title, bid, bids, shipping, country) in enumerate(_DEMO):
        end = now + dt.timedelta(minutes=random.randint(5, 60 * 12))
        out.append({
            "item_id": f"demo-{i}",
            "title": title,
            "url": "https://www.ebay.com/",
            "image": "",
            "end_time": end.isoformat().replace("+00:00", "Z"),
            "currency": "USD",
            "current_bid": float(bid),
            "bid_count": bids,
            "shipping": float(shipping),
            "item_country": country,
            "seller_name": "demo_seller", "seller_feedback": 250, "seller_pct": 99.5,
        })
    out.sort(key=lambda x: x["end_time"])
    return out


# ----------------- SerpApi (eBay 승인 전 우회) -----------------
def _parse_time_left(s):
    """'2m', '1h 30m', '2d 3h', '45s' -> 초. 못 읽으면 None."""
    if not s:
        return None
    secs = 0
    for num, unit in re.findall(r"(\d+)\s*([dhms])", str(s).lower()):
        secs += int(num) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
    return secs or None


def _fetch_serpapi():
    params = {
        "engine": "ebay", "_nkw": config.SEARCH_QUERY, "ebay_domain": "ebay.com",
        "_sop": "1", "LH_Auction": "1", "api_key": config.SERPAPI_KEY,
    }
    r = requests.get("https://serpapi.com/search.json", params=params, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("error"):
        raise RuntimeError("SerpApi: " + str(j["error"]))
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for c in j.get("organic_results", []) or []:
        bids = c.get("bids") or {}
        secs = _parse_time_left(bids.get("time_left"))
        end = ((now + dt.timedelta(seconds=secs)).isoformat().replace("+00:00", "Z")
               if secs else "")
        loc = (c.get("location") or "").lower()
        country = "US" if "united states" in loc else ("XX" if loc else "")
        sh = c.get("shipping")
        if isinstance(sh, dict):
            ship, raw = sh.get("extracted"), (sh.get("raw") or "")
        else:
            ship, raw = None, (sh or "")
        if ship is None:
            ship = 0.0 if "free" in str(raw).lower() else config.DEFAULT_SHIPPING
        pr = c.get("price")
        price = pr.get("extracted") if isinstance(pr, dict) else (pr if isinstance(pr, (int, float)) else 0)
        out.append({
            "item_id": str(c.get("product_id") or ""),
            "title": c.get("title", ""),
            "url": c.get("link", ""),
            "image": c.get("thumbnail", ""),
            "end_time": end,
            "currency": "USD",
            "current_bid": float(price or 0),
            "bid_count": int(bids.get("count") or 0),
            "shipping": float(ship),
            "item_country": country,
            "seller_name": "", "seller_feedback": 0, "seller_pct": 0.0,
        })
    return out


def fetch_listings():
    if config.MODE != "live":
        return _fetch_demo()
    if config.EBAY_PROVIDER == "serpapi":
        return _fetch_serpapi()
    return _fetch_live()
