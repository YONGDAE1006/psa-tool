"""
가치 판단(밸류에이션).

비딩 관점 핵심 계산:
  cost       = 현재 입찰가 + 배송비          (지금 사는 데 드는 돈)
  net_resale = PSA10 시세 * (1 - 수수료율)   (되팔 때 수수료 떼고 실수령액)
  profit     = net_resale - cost
  roi        = profit / cost

roi 가 config.MIN_ROI 이상이면 '비딩 후보'.
주의: 경매는 막판에 가격이 뛰므로(스나이핑) 현재가 기준 수치는 '기회 신호'이지
      확정 수익이 아닙니다. 대시보드에서도 이 점을 표시합니다.
"""
import config

def sell_fees(price):
    """판매가에 적용되는 (수수료율, 고정비). PSA Vault 공식 eBay 요율표 기준."""
    if config.SELL_MODE == "psa_vault":
        if price < 100:
            return 0.13, 3.0      # <$100: 13% + $3 고정
        if price < 500:
            return 0.13, 0.0
        if price < 1000:
            return 0.12, 0.0
        if price < 2500:
            return 0.10, 0.0
        if price < 5000:
            return 0.09, 0.0
        return 0.07, 0.0          # $5,000+
    return config.RESELL_FEE_RATE, config.FIXED_SELL_FEE


def sell_fee_rate(price):
    return sell_fees(price)[0]


def evaluate(current_bid, shipping, psa10_price):
    if not psa10_price or psa10_price <= 0:
        return {"cost": None, "net_resale": None, "profit": None, "roi": None,
                "breakeven_bid": None, "max_bid": None}
    ship = shipping or 0
    cost = (current_bid or 0) + ship
    # 되팔 때 실수령:
    #  - PSA Offer 모드: 수수료 0. 단 오퍼가 시장가의 ~95%로 들어와서 factor 적용(실측 3건 평균).
    #  - 그 외(eBay/PSA Vault): 계단식 판매수수료 + 고정비 차감.
    if config.SELL_MODE == "psa_offer":
        net_resale = psa10_price * getattr(config, "PSA_OFFER_FACTOR", 0.92) - config.RESALE_SHIP_COST
    else:
        fee_rate, flat_fee = sell_fees(psa10_price)
        net_resale = psa10_price * (1 - fee_rate) - flat_fee - config.RESALE_SHIP_COST
    profit = net_resale - cost
    roi = profit / cost if cost > 0 else None

    # 손익분기 입찰가: 이 입찰가를 넘으면 손해 (수익=0 지점)
    breakeven_bid = max(0, net_resale - ship)
    # 권장 최대 입찰가: 목표 수익($MIN_PROFIT)과 목표 수익률(MIN_ROI)을 둘 다 남기는 상한
    cap_profit = net_resale - config.MIN_PROFIT
    cap_roi = net_resale / (1 + config.MIN_ROI)
    max_bid = max(0, min(cap_profit, cap_roi) - ship)

    return {
        "cost": round(cost, 2),
        "net_resale": round(net_resale, 2),
        "profit": round(profit, 2),
        "roi": round(roi, 4) if roi is not None else None,
        "breakeven_bid": round(breakeven_bid, 2),
        "max_bid": round(max_bid, 2),
    }


def is_good_bid(roi, match_score):
    return (
        roi is not None
        and roi >= config.MIN_ROI
        and match_score >= config.MIN_MATCH_SCORE
    )
