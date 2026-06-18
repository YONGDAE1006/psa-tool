"""
실거래가 검증용 링크/검색어 생성.

- build_query: 후보 카드의 깔끔한 검색어 (매칭 신뢰도 높으면 정규화된 카드명, 아니면 원제목).
- ebay_sold_url: eBay 낙찰가(Sold/Completed) 딥링크 — 카드별로 바로 열림(가장 안정적).
- point130_url / psa_apr_url / alt_url: 폼 검색이라 프리필이 불안정 → 도구 페이지를 열고,
  화면의 '검색어'를 복붙해서 쓰는 용도.
"""
import re
import urllib.parse

import config


def build_query(pc_console, pc_name, title, match_score):
    """검증용 검색어 생성."""
    if pc_name and match_score is not None and match_score >= config.MIN_MATCH_SCORE:
        base = f"{pc_console or ''} {pc_name}"
    else:
        base = title or ""
    base = re.sub(r"\(.*?\)", " ", base)      # 괄호 설명 제거
    base = base.replace("#", " ")
    base = re.sub(r"\s+", " ", base).strip()
    if "psa 10" not in base.lower():
        base += " PSA 10"
    return base


def ebay_sold_url(query):
    q = urllib.parse.quote_plus(query)
    # LH_Sold=1, LH_Complete=1 = 낙찰/완료된 매물, _sop=13 = 최근 종료순
    return f"https://www.ebay.com/sch/i.html?_nkw={q}&LH_Sold=1&LH_Complete=1&_sop=13"


def point130_url():
    # GET 프리필 미지원 → 검색 도구 페이지
    return "https://130point.com/sales/"


def pricecharting_url(query):
    # 그 카드의 PriceCharting 검색(그래프·등급별 시세·개별 낙찰내역 무료 조회)
    q = urllib.parse.quote_plus(query)
    return f"https://www.pricecharting.com/search-products?q={q}&type=prices"


def psa_apr_url():
    return "https://www.psacard.com/auctionprices"


def alt_url():
    return "https://alt.xyz/"
