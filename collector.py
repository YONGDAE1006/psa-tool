"""
수집 파이프라인.
eBay 매물 가져오기 -> PriceCharting 시세 매칭 -> 마진 계산 -> DB 저장.

직접 실행:  python collector.py
대시보드의 '새로고침' 버튼도 이 함수를 호출합니다.
"""
import datetime as dt
import re

import config
import db
import ebay_client
import links
import matcher
import notify
import soldprices
import valuation
from textutil import has_psa10


def run():
    db.init_db()
    # 무료 등급 보호: 이번 수집에서 '새로' 조회할 카드 수 제한 (나머지는 캐시 사용)
    soldprices.set_budget(config.SOLD_LOOKUP_LIMIT)

    # PriceCharting은 선택. 있으면 카탈로그 매칭+추정가 폴백에 사용,
    # 없으면(무료 구성) eBay 제목으로 검색어를 만들어 실낙찰가만 사용.
    pc_rows = db.get_all_pc_prices()
    index = matcher.build_index(pc_rows) if pc_rows else []

    listings = ebay_client.fetch_listings()
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    out = []
    alert_rows = []   # 목록엔 안 넣지만 너무 좋아서 알림만 보낼 위험(하락) 매물
    skipped = {"country": 0, "shipping": 0, "currency": 0, "foreign": 0, "budget": 0,
               "keyword": 0, "lowvalue": 0, "lowprofit": 0, "bids": 0, "risky": 0,
               "seller": 0, "excluded": 0}
    _excluded = db.get_excluded()        # 사용자가 '제외'한 매물 — 다시 안 긁어옴
    for it in listings:
        title = it["title"]
        # PSA 10 매물만 (제목에 PSA 10 표기가 있는 것)
        if not has_psa10(title):
            continue
        if it.get("item_id") in _excluded:
            skipped["excluded"] += 1
            continue

        # --- 싼 필터 (시세 조회 전에 적용 → 크레딧 절약) ---
        country = (it.get("item_country") or "").upper()
        if config.ITEM_LOCATION_COUNTRY and country and country != config.ITEM_LOCATION_COUNTRY:
            skipped["country"] += 1
            continue
        if (it.get("shipping") or 0) > config.MAX_SHIPPING:
            skipped["shipping"] += 1
            continue
        if config.CURRENCY and (it.get("currency") or "USD").upper() != config.CURRENCY:
            skipped["currency"] += 1
            continue
        if config.MAX_BID > 0 and (it.get("current_bid") or 0) > config.MAX_BID:
            skipped["budget"] += 1
            continue
        low = title.lower()
        # 일본카드 감지: 마커 단어 + JP 고유 신호(JP명칭/아트레어/JP세트코드 sv2a·m2a·s12a)
        _jp = (any(m in low for m in config.FOREIGN_MARKERS)
               or "pokemon card game" in low
               or re.search(r"\bar\b|\b[a-z]{1,3}\d{1,2}[a-z]\b", low))
        if config.ENGLISH_ONLY and _jp:
            skipped["foreign"] += 1
            continue
        if any(kw in low for kw in config.EXCLUDE_KEYWORDS):
            skipped["keyword"] += 1
            continue
        if config.MIN_SELLER_FEEDBACK > 0 and (it.get("seller_feedback") or 0) < config.MIN_SELLER_FEEDBACK:
            skipped["seller"] += 1
            continue

        meets_bids = (it.get("bid_count") or 0) >= config.MIN_BID_COUNT

        pc, score = matcher.match(title, index)
        psa10 = pc["psa10_price"] if pc else None

        # eBay 실낙찰가 자동 조회. 입찰 적은 매물은 캐시에 있을 때만(크레딧 0).
        query = links.build_query(
            pc["console_name"] if pc else None,
            pc["product_name"] if pc else None,
            title, score,
        )
        sold = soldprices.get_sold(query, demo_hint=psa10, title=title,
                                   cache_only=not meets_bids)

        # 시세 기준 결정: 신뢰할 만한 실낙찰가가 있으면 그걸, 없으면 추정가
        value_trend = value_conf = None
        all_time_value = value_days = value_updated = None
        if sold and sold["n"] >= config.MIN_SOLD_COUNT:
            current_value = sold["median"]          # 현재(스마트) 시세
            value_trend = sold.get("trend")
            value_conf = sold.get("confidence")
            all_time_value = sold.get("all_time")
            value_days = sold.get("days_used")
            value_updated = sold.get("updated")
            # 시세 = smartMarketPrice 그대로. PPT가 적응형으로 산출(거래 많으면 14일·적으면 90일
            # 창 자동 선택 + 이상치 필터 + 최근 가중) → '상승해서 굳은 가격'을 제대로 반영.
            # (역대 medianPrice로 끌어내리면 옛 싼거래에 저평가됨 = 상승카드를 못 사게 됨)
            # 표본 부족/저신뢰는 아래 sold_reliable 에서 따로 걸러냄(min 강제할인 폐기).
            if value_trend == "down":
                current_value *= config.TREND_DOWN_FACTOR
            market_value = round(current_value, 2)
            value_source = "sold"
        elif psa10:
            market_value = psa10
            value_source = "estimate"
        else:
            market_value = None
            value_source = None

        val = valuation.evaluate(it["current_bid"], it["shipping"], market_value)

        # 시세 하한: 카드 시세가 너무 낮거나(저가 노이즈) 시세를 못 구하면 제외
        if config.MIN_MARKET_VALUE > 0 and (
                market_value is None or market_value < config.MIN_MARKET_VALUE):
            skipped["lowvalue"] += 1
            continue

        # 예상수익 하한: 현재가 기준 예상수익이 너무 작으면 제외(실속 없는 거래 차단)
        if config.MIN_PROFIT > 0 and (
                val["profit"] is None or val["profit"] < config.MIN_PROFIT):
            skipped["lowprofit"] += 1
            continue

        # 신뢰도: 실낙찰가는 '제목의 카드번호로 매칭이 확정된 경우'에만 신뢰.
        # (번호 확정 안 된 sold는 엉뚱한 카드일 수 있어 후보/알림/스틸에서 제외 → 대시보드엔 저신뢰로 노출)
        # 추정가는 PriceCharting 매칭 점수로 판단.
        num_confirmed = bool(sold and sold.get("num_confirmed"))
        # 표본 충분 + confidence low 아님 → 시세 신뢰. (얇은 카드 시세는 못 믿음)
        enough_sample = bool(sold and (sold.get("n") or 0) >= config.CONFIDENT_SOLD_COUNT
                             and (sold.get("confidence") or "") != "low")
        sold_reliable = num_confirmed and enough_sample
        match_score = (100 if (value_source == "sold" and sold_reliable)
                       else 40 if (value_source == "sold" and num_confirmed)  # 맞는 카드지만 표본부족=저신뢰
                       else 30 if value_source == "sold"
                       else score)
        reliable = (value_source == "sold" and sold_reliable) or (
            value_source == "estimate" and score >= config.MIN_MATCH_SCORE)

        # 입찰 필터: 충족하면 표시. 부족해도 ROI가 아주 높고 신뢰되면(스틸) 예외 표시.
        is_steal = (not meets_bids and reliable and val["roi"] is not None
                    and val["roi"] >= config.HIGH_ROI_OVERRIDE)
        if not meets_bids and not is_steal:
            skipped["bids"] += 1
            continue

        row = {
            "item_id": it["item_id"],
            "title": it["title"],
            "url": it["url"],
            "image": it["image"],
            "end_time": it["end_time"],
            "currency": it["currency"],
            "current_bid": it["current_bid"],
            "bid_count": it["bid_count"],
            "is_steal": 1 if is_steal else 0,
            "shipping": it["shipping"],
            "item_country": it.get("item_country", ""),
            "seller_name": it.get("seller_name", ""),
            "seller_feedback": it.get("seller_feedback", 0),
            "seller_pct": it.get("seller_pct", 0.0),
            "pc_id": pc["pc_id"] if pc else None,
            "pc_name": pc["product_name"] if pc else None,
            "pc_console": pc["console_name"] if pc else None,
            "psa10_price": psa10,
            "sold_median": sold["median"] if sold else None,
            "sold_n": sold["n"] if sold else 0,
            "sold_source": sold["source"] if sold else None,
            "value_trend": value_trend,
            "value_confidence": value_conf,
            "matched_name": (sold.get("matched_name") if sold else None)
                            or (pc["product_name"] if pc else None),
            "card_image": sold.get("card_image") if sold else None,
            "value_days": value_days,
            "value_updated": value_updated,
            "sales_week": sold.get("sales_week") if sold else None,
            "all_time_value": all_time_value,
            "market_value": market_value,
            "value_source": value_source,
            "match_score": match_score,
            "cost": val["cost"],
            "net_resale": val["net_resale"],
            "profit": val["profit"],
            "roi": val["roi"],
            "breakeven_bid": val["breakeven_bid"],
            "max_bid": val["max_bid"],
            "collected_at": now_iso,
        }

        # 옵션 A: 하락 추세 + 역대 고점 대비 급락(신상 거품 의심)이면 목록에서 제외.
        #          단, ROI가 예외적으로 높으면(RISKY_ALERT_ROI) 알림으로만 보냄.
        risky = (value_source == "sold" and value_trend == "down" and all_time_value
                 and market_value is not None
                 and market_value < all_time_value * config.DROP_FLAG_RATIO)
        if risky:
            if reliable and val["roi"] is not None and val["roi"] >= config.RISKY_ALERT_ROI:
                alert_rows.append(row)
            skipped["risky"] += 1
            continue

        out.append(row)

    # Gixen 등록한 매물은 이번 종료임박 순위에서 밀려났어도(또는 일시적으로 빠져도)
    # 아직 안 끝났으면 유지 — 등록한 걸 추적할 수 있게.
    marked = db.get_gixen_marks()
    if marked:
        new_ids = {r["item_id"] for r in out}
        nowts = dt.datetime.now(dt.timezone.utc)
        for old in db.get_listings():
            iid = old.get("item_id")
            if iid in marked and iid not in new_ids:
                try:
                    ends = dt.datetime.fromisoformat((old.get("end_time") or "").replace("Z", "+00:00"))
                except ValueError:
                    ends = None
                if ends and ends > nowts:          # 아직 안 끝난 것만
                    out.append(dict(old))
    if out:                                        # 모든 행 동일 컬럼으로 정렬
        keyset = list(out[0].keys())
        out = [{k: r.get(k) for k in keyset} for r in out]

    db.replace_listings(out)
    _notify_candidates(out)
    _notify_risky(alert_rows)
    print(f"filter skipped - non-{config.ITEM_LOCATION_COUNTRY or 'ALL'}: {skipped['country']}, "
          f"shipping>{config.MAX_SHIPPING:.0f}: {skipped['shipping']}, "
          f"non-{config.CURRENCY}: {skipped['currency']}, "
          f"bid>{config.MAX_BID:.0f}: {skipped['budget']}, "
          f"value<{config.MIN_MARKET_VALUE:.0f}: {skipped['lowvalue']}, "
          f"profit<{config.MIN_PROFIT:.0f}: {skipped['lowprofit']}, "
          f"foreign(영어판아님): {skipped['foreign']}, "
          f"bids<{config.MIN_BID_COUNT}: {skipped['bids']}, keyword: {skipped['keyword']}, "
          f"seller<{config.MIN_SELLER_FEEDBACK}: {skipped['seller']}, "
          f"risky(hidden): {skipped['risky']}, risky-alerts: {len(alert_rows)}")
    return len(out)


def _notify_candidates(rows):
    """강력한 후보(또는 스틸)가 종료 임박이면 텔레그램 알림 (중복 방지)."""
    if not notify.enabled():
        return
    sent = 0
    for r in rows:
        reliable = (r["value_source"] == "sold" and (r["match_score"] or 0) >= 90) or (
            r["value_source"] == "estimate" and (r["match_score"] or 0) >= config.MIN_MATCH_SCORE)
        is_cand = r["is_steal"] or (
            r["roi"] is not None and r["roi"] >= config.MIN_ROI and reliable)
        if not is_cand:
            continue
        secs = notify._secs_left(r["end_time"])
        if secs is None or secs <= 0:
            continue
        # 1차 알림: 알림 윈도우 내 첫 발견 시
        if secs <= config.NOTIFY_WINDOW_HOURS * 3600 and not db.is_notified(r["item_id"]):
            if notify.send(notify.format_candidate(r), notify.build_buttons(r)):
                db.mark_notified(r["item_id"])
                sent += 1
        # 2차 알림: 종료 임박(기본 15분) 리마인드 (한 번 더)
        if secs <= config.FINAL_ALERT_MINUTES * 60 and not db.is_notified(r["item_id"] + "|final"):
            txt = "⏰ <b>곧 종료!</b>\n" + notify.format_candidate(r)
            if notify.send(txt, notify.build_buttons(r)):
                db.mark_notified(r["item_id"] + "|final")
                sent += 1
    if sent:
        print(f"telegram alerts sent: {sent}")


def _notify_risky(rows):
    """목록엔 없지만 예외적으로 좋은 위험(하락) 매물을 ⚠️ 표시로 알림."""
    if not notify.enabled():
        return
    for r in rows:
        secs = notify._secs_left(r["end_time"])
        if secs is None or secs <= 0 or secs > config.NOTIFY_WINDOW_HOURS * 3600:
            continue
        if db.is_notified(r["item_id"]):
            continue
        if notify.send(notify.format_candidate(r, risky=True), notify.build_buttons(r)):
            db.mark_notified(r["item_id"])


if __name__ == "__main__":
    mode = config.MODE
    n = run()
    print(f"[{mode}] collected & valued {n} PSA10 listings -> {config.DB_PATH}")
