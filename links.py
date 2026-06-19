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


def verify_query(matched_name, title=""):
    """시세 검증(PriceCharting/eBay) 검색어 = '카드명 + 카드번호 첫부분'만.
    세트명/총번호(/SV94)/연도/SHINY 등은 빼야 PriceCharting서 정확히 나옴.
    예: matched_name 'Buzzwole GX SV68/SV94 · Hidden Fates: Shiny Vault' → 'Buzzwole GX SV68'."""
    if matched_name:
        left = matched_name.split("·")[0].replace("-", " ")
        name_toks, num = [], None
        for t in left.split():
            if re.match(r"^[A-Za-z]{0,3}\d", t):     # 카드번호 토큰(SV68/SV94, 183/165, GG55, 024)
                num = t.split("/")[0]                # 첫 부분만(SV68/SV94 → SV68)
                break
            name_toks.append(t)
        if name_toks:
            base = " ".join(name_toks) + (f" {num}" if num else "")
            return re.sub(r"\s+", " ", base).strip()
    return re.sub(r"\s+", " ", (title or "")).strip()


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


def gixen_url():
    return config.GIXEN_URL


def gixen_snipe_url(item_number, max_bid=None):
    """Gixen add-snipe 프리필 URL: itemid(=eBay번호)·maxbid(=권장입찰가) 자동입력.
    번호 없으면 None. (Add 버튼은 사용자가 직접 누름)"""
    if not item_number:
        return None
    params = {"itemid": str(item_number)}
    try:
        if max_bid is not None and float(max_bid) == float(max_bid):  # NaN 아님
            params["maxbid"] = f"{float(max_bid):.2f}"
    except (TypeError, ValueError):
        pass
    base = config.GIXEN_URL
    sep = "&" if "?" in base else "?"
    return base + sep + urllib.parse.urlencode(params)


def ebay_item_number(url, item_id=""):
    """Gixen 등록에 쓰는 eBay 숫자 아이템 번호 추출."""
    m = re.search(r"/itm/(?:[^/]*/)?(\d{9,15})", url or "")
    if m:
        return m.group(1)
    m = re.search(r"\|(\d{9,15})\|", item_id or "") or re.search(r"(\d{9,15})", item_id or "")
    return m.group(1) if m else None


def psa_apr_url():
    return "https://www.psacard.com/auctionprices"


def alt_url():
    return "https://alt.xyz/"
