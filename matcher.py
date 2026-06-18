"""
매칭 = 이 프로그램의 두뇌.
지저분한 eBay 제목을 PriceCharting 상품과 연결해서 PSA10 시세를 찾아냄.

전략:
1) 제목을 정규화.
2) rapidfuzz 로 모든 PriceCharting 상품과 유사도(token_set_ratio) 계산.
3) 제목에서 뽑은 카드번호가 상품명에 들어있으면 점수 보너스.
4) 최고 점수 후보를 반환 (점수도 함께 -> 대시보드에서 신뢰도 확인용).
"""
from rapidfuzz import fuzz

from textutil import normalize, extract_card_number


def build_index(pc_rows):
    """pc_rows(dict 리스트)를 매칭용 구조로 준비."""
    idx = []
    for r in pc_rows:
        idx.append({
            "pc_id": r["pc_id"],
            "console_name": r["console_name"],
            "product_name": r["product_name"],
            "search_text": r["search_text"],
            "number": extract_card_number(r["product_name"]),
            "psa10_price": r["psa10_price"],
        })
    return idx


def match(title, index):
    """가장 잘 맞는 PriceCharting 상품과 점수(0~100) 반환. 못 찾으면 (None, 0)."""
    q = normalize(title)
    q_num = extract_card_number(title)

    best = None
    best_score = -1.0
    for row in index:
        score = fuzz.token_set_ratio(q, row["search_text"])
        # 카드번호 일치 보너스 / 불일치 페널티
        if q_num and row["number"]:
            if q_num == row["number"]:
                score += 12
            else:
                score -= 8
        if score > best_score:
            best_score = score
            best = row

    if best is None:
        return None, 0
    return best, int(max(0, min(100, round(best_score))))
