"""
설정 모듈.
- .env 파일에서 값을 읽어옵니다 (.env.example 참고).
- 가장 중요한 값은 MODE 입니다:
    demo = eBay 키/PriceCharting 결제 없이 가짜 데이터로 전체 흐름 확인
    live = 실제 eBay API + 실제 PriceCharting CSV 사용
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# demo 또는 live
MODE = os.getenv("MODE", "demo").strip().lower()

# ---------- eBay ----------
# 매물 소스: official(eBay 공식 API) / serpapi(승인 전 우회) / (demo는 MODE로)
EBAY_PROVIDER = os.getenv("EBAY_PROVIDER", "official").strip().lower()
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET", "")
EBAY_MARKETPLACE = os.getenv("EBAY_MARKETPLACE", "EBAY_US")
# 수취지 미국 ZIP. eBay 계산식 배송비를 이 목적지 기준으로 정확히 받기 위함.
# (없으면 일부 매물 배송비가 비어 DEFAULT_SHIPPING으로 떨어짐). PSA창고/본인 미국주소 ZIP.
EBAY_SHIP_ZIP = os.getenv("EBAY_SHIP_ZIP", "19720")
# Gixen 스나이핑 사이트. m.gixen.com 폐쇄, /mobile/?프리필도 메인으로 튕김(미지원)
# → 그냥 로그인된 메인(스나이프 추가 폼)으로 열고 번호·입찰가는 대시보드서 복붙.
GIXEN_URL = os.getenv("GIXEN_URL", "https://www.gixen.com")
# Gixen 공식 API 자동등록용 로그인(= Gixen 계정 ID/비번). 비우면 자동등록 비활성(복붙 안내만).
GIXEN_USERNAME = os.getenv("GIXEN_USERNAME", "")
GIXEN_PASSWORD = os.getenv("GIXEN_PASSWORD", "")
# 종료 몇 초 전에 입찰할지(Gixen 기본 6초). 막판 스나이핑일수록 작게.
GIXEN_BIDOFFSET = int(os.getenv("GIXEN_BIDOFFSET", "6"))
# 등록 방식: auto(API 우선, 막히면 웹폼 자동전환) / api(API만) / web(웹폼만).
# Gixen API가 [501] DISABLED면 auto가 웹 로그인+폼제출로 자동 우회.
GIXEN_METHOD = os.getenv("GIXEN_METHOD", "auto").strip().lower()
SEARCH_QUERY = os.getenv("SEARCH_QUERY", "pokemon psa10")  # 붙여써야 PSA10만 정확히 잡힘
SEARCH_LIMIT = int(os.getenv("SEARCH_LIMIT", "250"))  # 한 번에 가져올 매물 수(100≈6h, 250≈15h 커버)
# 상승추세 카드: PPT 90일가중 시세가 최근가를 못 따라갈 때 priceHistory 최근값으로 보정.
# 단 스파이크 방지로 90일가중의 이 배수까지만 올림(예: 1.6 = 최대 1.6배).
MAX_RECENT_MULT = float(os.getenv("MAX_RECENT_MULT", "1.6"))

# ---------- 매물 필터 (거래 조건) ----------
# 상품 소재지 국가. "US" = 미국 내 매물만. 빈값이면 전체 허용.
ITEM_LOCATION_COUNTRY = os.getenv("ITEM_LOCATION_COUNTRY", "US").strip().upper()
# 최대 배송비(USD). 이 값 이상이면 제외. (예: 10 = 10달러 이상 배송비 제외)
MAX_SHIPPING = float(os.getenv("MAX_SHIPPING", "10"))
# 허용 통화. 이 통화가 아니면 제외(안전장치). eBay.com 은 보통 USD.
CURRENCY = os.getenv("CURRENCY", "USD").strip().upper()
# 최소 입찰 수. 이 값 미만이면 제외. (11 = '입찰 10건 초과'만 = 수요 있는 매물)
MIN_BID_COUNT = int(os.getenv("MIN_BID_COUNT", "11"))
# 셀러 리뷰(피드백) 수 하한. 이 미만 셀러 매물은 제외(0=필터 끔, 전부 표시).
# 신규/저평판 셀러의 싼 PSA10 = 사기(가짜슬랩/미발송) 위험. 대시보드엔 ⚠️로도 표시.
MIN_SELLER_FEEDBACK = int(os.getenv("MIN_SELLER_FEEDBACK", "0"))
SELLER_FLAG_FEEDBACK = int(os.getenv("SELLER_FLAG_FEEDBACK", "30"))  # 이 미만이면 ⚠️ 주의 표시
# 입찰이 적어도 ROI가 이 값 이상이면 예외적으로 표시(🔥스틸). 0.5 = 50%.
# 단, 크레딧 절약을 위해 '이미 캐시에 시세가 있는 카드'만 대상.
HIGH_ROI_OVERRIDE = float(os.getenv("HIGH_ROI_OVERRIDE", "0.5"))
# 예산 상한(USD). 현재가가 이 값보다 비싸면 제외. 0이면 무제한.
MAX_BID = float(os.getenv("MAX_BID", "500"))
# 시세 하한(USD). 카드 PSA10 시세가 이 값 미만이면 제외(저가 카드 노이즈 제거). 0이면 무제한.
MIN_MARKET_VALUE = float(os.getenv("MIN_MARKET_VALUE", "50"))
# 영어판만 보기: 제목에 외국어/타지역 표기 있으면 제외 (PPT 매칭률↑, 크레딧 절약)
ENGLISH_ONLY = os.getenv("ENGLISH_ONLY", "true").lower() == "true"
FOREIGN_MARKERS = [
    w.strip().lower() for w in os.getenv(
        "FOREIGN_MARKERS",
        # 언어/지역 단어만 제외. 일본 세트코드는 통과시켜 PPT가 시세 있는지 조회(혹시 모르니).
        "japanese,japan,jpn,jp ,korean,chinese,german,french,spanish,italian,portuguese,taiwan,"
        "indonesia,thailand,thai,vietnam,philippines,carddass"
    ).split(",") if w.strip()
]
# 제목에 이 단어가 있으면 제외 (묶음/커스텀/가짜 등). 쉼표로 구분.
EXCLUDE_KEYWORDS = [
    w.strip().lower() for w in os.getenv(
        "EXCLUDE_KEYWORDS",
        "lot,bulk,proxy,custom,jumbo,oversized,sticker,reprint,fake,read desc"
    ).split(",") if w.strip()
]

# ---------- PriceCharting ----------
# live 모드에서 매일 받는 전체 CSV 파일 경로. demo 모드면 샘플 CSV 사용.
PC_CSV_PATH = os.getenv(
    "PC_CSV_PATH",
    str(BASE_DIR / "data" / "pricecharting_sample.csv"),
)
PC_TOKEN = os.getenv("PC_TOKEN", "")  # 나중에 API로 자동 다운로드할 때 사용
# PriceCharting CSV/API 가격은 '센트(penny)' 정수로 옵니다. 예: 1099 = $10.99
PC_PRICE_IN_PENNIES = os.getenv("PC_PRICE_IN_PENNIES", "true").lower() == "true"

# PriceCharting 카드 등급 -> CSV 컬럼명 매핑 (공식 문서 기준)
# 게임용 필드명을 카드 등급에 재사용하는 구조라 헷갈리니 주석으로 명시.
PC_GRADE_FIELDS = {
    "ungraded": "loose-price",
    "grade7": "cib-price",
    "grade8": "new-price",
    "grade9": "graded-price",
    "grade9.5": "box-only-price",
    "psa10": "manual-only-price",   # <-- 우리가 쓰는 핵심 값
    "bgs10": "bgs-10-price",
}
PC_PSA10_FIELD = PC_GRADE_FIELDS["psa10"]

# ---------- 실낙찰가(eBay sold) 자동 조회 ----------
# demo                 : 가짜 실낙찰가 (키 없이 흐름 확인)
# pokemonpricetracker  : PokemonPriceTracker API (eBay 실낙찰가 PSA10) ~$10/월
# ebay_insights        : eBay Marketplace Insights API (승인 필요, 무료)
SOLD_PROVIDER = os.getenv("SOLD_PROVIDER", "demo").strip().lower()
SOLD_DAYS = int(os.getenv("SOLD_DAYS", "90"))      # 최근 며칠 낙찰 집계
MIN_SOLD_COUNT = int(os.getenv("MIN_SOLD_COUNT", "3"))  # 이 건수 이상이면 실낙찰가 '표시'
# 이 건수 이상 + confidence가 low가 아니어야 시세를 '신뢰'(후보/알림/스틸 대상).
# 미만이면 대시보드엔 보이되 ⚠️저신뢰로 표시하고 자동알림/스틸에서 제외(수동 검증 유도).
CONFIDENT_SOLD_COUNT = int(os.getenv("CONFIDENT_SOLD_COUNT", "12"))
# --- 무료 등급 크레딧 절약 ---
# 같은 카드를 이 시간(시간) 안에는 다시 조회하지 않고 캐시 사용 (시세는 빨리 안 변함)
SOLD_CACHE_HOURS = int(os.getenv("SOLD_CACHE_HOURS", "24"))
# 1회 수집에서 '새로' 조회할 최대 카드 수 (나머지는 캐시만 사용). 무료 등급 보호용.
SOLD_LOOKUP_LIMIT = int(os.getenv("SOLD_LOOKUP_LIMIT", "25"))
# PokemonPriceTracker
# PPT_API_KEY 는 콤마로 여러 무료 키를 넣을 수 있음. 하나가 일일한도(429)에 걸리면
# soldprices 가 자동으로 다음 키로 전환(무료 100/일을 키 수만큼 확보). 유료키면 1개만.
PPT_API_KEYS = [k.strip() for k in os.getenv("PPT_API_KEY", "").split(",") if k.strip()]
PPT_API_KEY = PPT_API_KEYS[0] if PPT_API_KEYS else ""  # 호환용(첫 키)
PPT_BASE_URL = os.getenv("PPT_BASE_URL", "https://www.pokemonpricetracker.com/api/v2")

# ---------- 가치 판단(밸류에이션) 파라미터 ----------
# 판매 방식: psa_vault = PSA Vault에서 eBay 위탁판매(계단식 수수료, eBay 수수료 없음)
#            ebay     = 일반 eBay 판매(고정 비율)
SELL_MODE = os.getenv("SELL_MODE", "psa_vault").strip().lower()
# PSA Offer 모드: 수수료 0, 단 오퍼가 시장가의 약 X%로 들어옴(실측 ~95%, 보수적 기본 0.92).
PSA_OFFER_FACTOR = float(os.getenv("PSA_OFFER_FACTOR", "0.92"))
# 일반 eBay 판매 시 수수료 비율(결제처리 포함). 기본 13.25%.
RESELL_FEE_RATE = float(os.getenv("RESELL_FEE_RATE", "0.1325"))
# 되팔 때 주문당 고정 수수료(USD). PSA Vault ≈ $3, 일반 eBay ≈ $0.40.
FIXED_SELL_FEE = float(os.getenv("FIXED_SELL_FEE", "3.0"))
# 되팔 때 내가 부담하는 발송비(USD). PSA Vault는 구매자 부담이라 0.
RESALE_SHIP_COST = float(os.getenv("RESALE_SHIP_COST", "0"))
# 시세 기준 최소 기간(일). 최근 데이터가 이보다 짧고 불안정하면 장기 중앙값으로 보수 보정.
MIN_VALUE_DAYS = int(os.getenv("MIN_VALUE_DAYS", "30"))
# 시세 데이터가 이 일수보다 오래됐으면 '오래됨' 경고 표시.
STALE_DAYS = int(os.getenv("STALE_DAYS", "14"))
# 배송비 정보가 없을 때 가정할 기본 배송비(USD)
DEFAULT_SHIPPING = float(os.getenv("DEFAULT_SHIPPING", "5.0"))
# 이 ROI 이상이면 '비딩 후보'로 표시 (0.15 = 15%)
MIN_ROI = float(os.getenv("MIN_ROI", "0.15"))
# 예상수익(USD) 하한. 현재가 기준 예상수익이 이 값 미만이면 제외. 0이면 무제한.
MIN_PROFIT = float(os.getenv("MIN_PROFIT", "15"))
# 카드명 매칭 신뢰도(0~100) 최소 점수. 이보다 낮으면 매칭 실패로 간주.
MIN_MATCH_SCORE = int(os.getenv("MIN_MATCH_SCORE", "70"))

# ---------- 시세 추세/위험 보정 ----------
# 시세가 하락 추세면 시세를 이 비율로 깎아서 보수적으로 평가 (계속 떨어질 위험).
TREND_DOWN_FACTOR = float(os.getenv("TREND_DOWN_FACTOR", "0.90"))
# 시세 신뢰도가 낮으면(표본/변동성) 이 비율로 추가로 깎음.
LOW_CONF_FACTOR = float(os.getenv("LOW_CONF_FACTOR", "0.92"))
# 현재 시세가 역대 중앙값의 이 비율 미만이면 '신상 거품/하락' 주의 표시.
DROP_FLAG_RATIO = float(os.getenv("DROP_FLAG_RATIO", "0.7"))
# 하락+급락(위험) 카드는 목록서 제외하되, ROI가 이 값 이상이면 알림만 보냄.
RISKY_ALERT_ROI = float(os.getenv("RISKY_ALERT_ROI", "0.6"))

# ---------- 텔레그램 알림 ----------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
# 종료까지 이 시간 이내인 후보만 알림 (예: 12시간 안에 끝나는 좋은 매물만).
NOTIFY_WINDOW_HOURS = float(os.getenv("NOTIFY_WINDOW_HOURS", "12"))
# 종료 직전 2차(마지막) 알림: 이 분(分) 이내로 임박하면 한 번 더 리마인드.
FINAL_ALERT_MINUTES = float(os.getenv("FINAL_ALERT_MINUTES", "15"))
# 상주 프로그램(agent) 자동 수집 간격(분).
COLLECT_INTERVAL_MINUTES = int(os.getenv("COLLECT_INTERVAL_MINUTES", "60"))
# 생존신호 보낼 시각(시, 24h). 기본 아침9·점심13·저녁19.
HEARTBEAT_HOURS = os.getenv("HEARTBEAT_HOURS", "9,13,19")

# ---------- 저장소 ----------
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "psa.db"))
