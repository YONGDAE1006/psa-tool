"""제목/상품명 정규화 + 카드번호 추출 (매칭용)."""
import re

_GRADE_NOISE = [
    "psa", "gem", "mint", "gem mint", "bgs", "cgc", "graded",
    "secret rare", "alt art", "alternate art", "full art", "sar", "sir",
    "shiny", "holo", "rare", "card", "pokemon", "tcg", "wotc",
]


def normalize(text: str) -> str:
    """소문자화 + 특수문자 제거 + 흔한 노이즈 단어 제거."""
    t = (text or "").lower()
    t = re.sub(r"[#/().,:\-]", " ", t)
    t = re.sub(r"\bpsa\s*10\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def extract_card_number(text: str):
    """
    제목에서 카드 번호 추출.
    '11/108' -> '11', '#074' -> '074', 'SV49/SV94' -> 'sv49'
    """
    t = (text or "").lower()
    # 11/108 형태
    m = re.search(r"(\b[a-z]{0,3}\d{1,3})\s*/\s*[a-z]{0,3}\d{1,4}", t)
    if m:
        return m.group(1).replace(" ", "")
    # #074 형태
    m = re.search(r"#\s*([a-z]{0,3}\d{1,4})", t)
    if m:
        return m.group(1)
    return None


def has_psa10(text: str) -> bool:
    return bool(re.search(r"psa\s*10", (text or "").lower()))
