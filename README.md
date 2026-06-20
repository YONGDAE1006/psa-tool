# psa-tool — PSA-graded trading card auction price analyzer

A personal, single-user tool that helps evaluate **PSA-graded trading card auctions** on eBay before bidding.

**eBay APIs used:**
- **Browse API** (`buy.browse`) — fetches live graded-card auctions, sorted by ending-soonest, filtered to US location and auction format (in production).
- **Marketplace Insights API** (`buy.marketplace.insights`) — *access requested* — recent sold prices (last 90 days) per graded card, used to compute an accurate market value (median + price range) and a short-term price trend. A single current price is not enough to judge whether an auction is priced below or above the going rate.

Data is used only internally within this application for price analysis. It is never redistributed, resold, or shown publicly. API keys live in a local `.env` file that is **not** committed to this repository.

---

*(아래는 한국어 상세 문서 / Korean detailed documentation below)*

# Pokemon PSA 10 비딩 대시보드

eBay에서 "pokemon psa 10" 경매를 **종료 임박순**으로 수집하고,
**PriceCharting PSA 10 시세**와 비교해 **비딩할 만한 매물**을 골라주는 개인 투자용 도구.

---

## 빠른 시작 (DEMO 모드 — 키/결제 불필요)

가짜 eBay 매물 + 샘플 시세로 전체 흐름을 먼저 확인합니다.

```powershell
cd C:\psa-tool
.\.venv\Scripts\python.exe pricecharting.py     # 샘플 시세 로드
.\.venv\Scripts\python.exe collector.py         # 수집 + 매칭 + 마진계산
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

브라우저에서 http://localhost:8501 접속.

---

## 구조

```
ebay_client.py   eBay 매물 수집 (공식 Browse API / demo)
pricecharting.py CSV 시세 로드
textutil.py      제목 정규화 + 카드번호 추출
matcher.py       제목 ↔ 시세 매칭 (이 프로그램의 두뇌)
valuation.py     마진/ROI 계산
collector.py     위를 묶는 파이프라인
dashboard.py     웹 화면 (streamlit)
run_loop.py      자동 반복 수집 (선택)
config.py / .env 설정
data/            샘플 CSV + SQLite DB
```

---

## 실제 데이터(LIVE)로 전환하기

DEMO로 만족했으면 아래 2가지를 연결합니다.

### 1) eBay 공식 API 키 (무료)
1. https://developer.ebay.com 가입 → **Application Keys** 메뉴.
2. **Production** 의 **App ID(Client ID)** 와 **Cert ID(Client Secret)** 복사.
3. `.env.example` 을 복사해 `.env` 로 저장 후 값 입력:
   ```
   MODE=live
   EBAY_CLIENT_ID=여기에
   EBAY_CLIENT_SECRET=여기에
   ```

### 2) PriceCharting 시세 (Legendary $59/년)
1. https://www.pricecharting.com 구독(Legendary) 후 **Subscription → API/Download**.
2. **Price Guide CSV(포켓몬)** 를 다운로드해 `C:\psa-tool\data\` 에 저장.
3. `.env` 에 경로 지정:
   ```
   PC_CSV_PATH=C:\psa-tool\data\pokemon-cards.csv
   ```
   - 실제 CSV는 이미 같은 컬럼명(`manual-only-price` = PSA 10)이라 그대로 동작.
   - 가격이 센트가 아니라 달러로 보이면 `PC_PRICE_IN_PENNIES=false` 로 변경.

### 3) eBay 실낙찰가 자동 조회 (선택, 추정가보다 정확)
130point/PSA APR 의 "실거래가 확인"을 자동화하는 부분. `.env`:
```
SOLD_PROVIDER=pokemonpricetracker
PPT_API_KEY=발급받은키
```
- **PokemonPriceTracker** ($10/월): eBay 실낙찰가 PSA10(중앙값·건수)을 API로 제공. 가장 깨끗한 자동화.
- 또는 `SOLD_PROVIDER=ebay_insights` : eBay 공식 Marketplace Insights API(무료, **사전 승인 필요**).
- 실낙찰 건수가 `MIN_SOLD_COUNT` 이상이면 **실낙찰가**로 ROI 계산, 아니면 PriceCharting 추정가로 폴백.
- 130point/PSA APR 직접 스크래핑은 공식 API가 없고 Cloudflare 차단·약관 문제로 **비권장**.

### 전환 후 실행
```powershell
.\.venv\Scripts\python.exe pricecharting.py   # 진짜 CSV 로드 (하루 1회)
.\.venv\Scripts\python.exe collector.py       # 실제 eBay 수집
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

---

## 자동 반복

```powershell
.\.venv\Scripts\python.exe run_loop.py 600   # 10분마다 수집
```
대시보드 사이드바의 **🔄 데이터 새로고침** 버튼으로도 수동 갱신 가능.

---

## 조정 가능한 값 (.env 또는 사이드바)

- `MIN_ROI` 비딩 후보 기준 수익률 (기본 0.15 = 15%)
- `RESELL_FEE_RATE` 재판매 수수료 추정 (기본 0.13)
- `MIN_MATCH_SCORE` 매칭 신뢰도 하한 (기본 70)
- `DEFAULT_SHIPPING` 배송비 없을 때 가정값

---

## ⚠️ 주의

- 경매는 **막판에 가격이 뛸 수 있습니다(스나이핑)**. ROI는 "현재가 기준 기회 신호"이지 확정 수익이 아닙니다.
- 매칭 신뢰도가 낮은 행은 **'매칭된 카드' 열을 꼭 눈으로 확인**하세요.
- 시세/통화는 USD(eBay.com US) 기준으로 가정합니다.
```
