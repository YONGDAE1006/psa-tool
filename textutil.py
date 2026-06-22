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
    # 프로모 코드 (# 없이 적힌 SWSH291, SM248, SVP083, GG12 등)
    m = re.search(r"\b(swsh|svp|swhp|sm|sv|xy|bw|hgss|gg|tg)\s*(\d{2,4})\b", t)
    if m:
        return m.group(1) + m.group(2)
    # 맨숫자 카드번호 — 앞0 붙은 건 거의 카드번호(023/050/009). 연도·총수량 오인 방지로 앞0만.
    m = re.search(r"\b(0\d{1,3})\b", t)
    if m:
        return m.group(1)
    # 맨숫자 단독 폴백 — 등급(psa/cgc/bgs N)·연도(19xx/20xx) 제거 후 1~3자리 숫자가
    # '딱 하나'면 그게 카드번호(159·177·203 등). 여럿이면 모호하므로 포기(오추출 방지).
    t2 = re.sub(r"\b(psa|cgc|bgs|sgc|gem\s*mt?|mint|nm)\s*\d+", " ", t)
    t2 = re.sub(r"\bpop(ulation)?\s*\d+", " ", t2)   # PSA 인구수 'POP 1' 오추출 방지
    t2 = re.sub(r"\b(19|20)\d{2}\b", " ", t2)
    uniq = set(re.findall(r"\b\d{1,3}\b", t2))
    if len(uniq) == 1:
        return uniq.pop()
    return None


def has_psa10(text: str) -> bool:
    return bool(re.search(r"psa\s*10", (text or "").lower()))
