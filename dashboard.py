"""
대시보드 (웹 화면).
실행:  streamlit run dashboard.py

종료임박순 eBay PSA10 매물 + PriceCharting 시세 비교 + 비딩 후보 하이라이트.
"""
import datetime as dt
import re

import pandas as pd
import streamlit as st

import collector
import config
import db
import gixen_api
import links
import valuation


def _upscale_img(url):
    """eBay 썸네일 해상도 ↑ (s-l225 → s-l500). 깨짐 방지."""
    return re.sub(r"s-l\d+", "s-l500", url) if url else url


def _card_img_html(url, cap):
    """실물·공식 이미지를 인라인 스타일로 직접 렌더 → Streamlit DOM 변화와 무관하게
    두 이미지가 항상 동일한 박스 크기로 통일됨. (CSS testid 선택자 의존 제거.)
    카드 비율(5:7) 고정박스 + object-fit:contain → 크기 통일하면서 이미지는
    절대 안 잘림(상품정보/PSA라벨 보존). 비율차이는 어두운 여백으로 채움."""
    return (
        "<div style='text-align:center'>"
        f"<img src='{url}' style='width:100%;aspect-ratio:5/7;object-fit:contain;"
        "object-position:center;display:block;border-radius:12px;"
        "border:1px solid rgba(255,255,255,.10);background:#0c0e13'/>"
        f"<div style='color:#9aa3b2;font-size:.78rem;margin-top:4px'>{cap}</div>"
        "</div>"
    )


def _toggle_gixen(item_id):
    """Gixen 등록 체크 토글 → DB 저장(영구 유지)."""
    db.set_gixen_mark(item_id, bool(st.session_state.get(f"gx_{item_id}", False)))


def _register_gixen(item_id, itemno):
    """🅖 Gixen 자동등록 버튼 콜백 — '내 최대입찰가' 그대로 스나이프 등록(클릭=컨펌)."""
    bid = st.session_state.get(f"bid_{item_id}", 0) or 0
    try:
        gixen_api.add_snipe(itemno, bid, bidoffset=config.GIXEN_BIDOFFSET)
        st.session_state[f"gxres_{item_id}"] = {"ok": True, "bid": float(bid)}
        db.set_gixen_mark(item_id, True)        # 등록 표시 영구 저장
        st.session_state[f"gx_{item_id}"] = True  # 토글도 켜짐 상태로
    except Exception as e:
        st.session_state[f"gxres_{item_id}"] = {"ok": False, "msg": str(e)}


def _exclude_item(item_id, title=""):
    """이 매물 제외 → DB 저장. 다음 수집 때도 다시 안 긁어옴."""
    db.set_excluded(item_id, title, True)


def _restore_item(item_id):
    """제외 해제."""
    db.set_excluded(item_id, on=False)


def _save_manual(card_key, widget_key):
    """수동 시세 입력 저장(카드별). 0이면 삭제."""
    db.set_manual_price(card_key, st.session_state.get(widget_key, 0) or 0)

st.set_page_config(page_title="Pokemon PSA10 비딩 대시보드", layout="wide",
                   page_icon="🎴")

st.markdown("""
<style>
/* ===== 다크 프리미엄 테마 ===== */
.stApp { background:#0a0b0f; }
.block-container { padding-top:1.4rem; padding-bottom:3rem; max-width:1480px; }
html, body, [class*="css"], p, span, label, div { font-family:'Pretendard','Inter','Segoe UI',sans-serif; }
.stApp, .stApp p, .stApp label, .stApp span { color:#e3e7ee; }

/* ===== 헤더 ===== */
h1 { font-weight:600 !important; letter-spacing:-.5px;
     background:linear-gradient(90deg,#fbbf24,#fb7c5c); -webkit-background-clip:text;
     -webkit-text-fill-color:transparent; }
h2,h3 { font-weight:600 !important; color:#f4f5f7 !important; letter-spacing:-.3px; }
h4 { font-weight:600 !important; color:#f4f5f7 !important; }

/* ===== 카드 ===== */
[data-testid="stVerticalBlockBorderWrapper"]{
  background:#111319; border:1px solid rgba(255,255,255,.08) !important; border-radius:16px !important;
  padding:10px 18px 14px; margin-bottom:8px;
  transition:border-color .2s ease, transform .2s ease;
}
[data-testid="stVerticalBlockBorderWrapper"]:hover{
  border-color:rgba(251,191,36,.40) !important; transform:translateY(-2px);
}

/* ===== 메트릭 ===== */
[data-testid="stMetric"]{
  background:#1a1d25; border:1px solid rgba(255,255,255,.05);
  border-radius:12px; padding:12px 15px;
}
[data-testid="stMetricValue"]{ font-weight:600 !important; font-size:1.42rem !important; color:#f4f5f7 !important; }
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] *{ color:#8b91a0 !important; }

/* ===== 버튼 ===== */
.stButton>button, .stLinkButton>a{
  background:#1f2330 !important; color:#e5e7eb !important; border-radius:9px !important;
  font-weight:500 !important; border:1px solid rgba(255,255,255,.1) !important; transition:all .15s ease;
}
.stButton>button:hover, .stLinkButton>a:hover{
  border-color:#fbbf24 !important; color:#fbbf24 !important;
}

/* ===== 이미지/입력/탭/사이드바 ===== */
[data-testid="stImage"] img{ border-radius:12px; border:1px solid rgba(255,255,255,.07); }
/* 실물·공식 카드 이미지는 _card_img_html 인라인 스타일로 크기 통일(아래 CSS 미사용). */
input, textarea, [data-baseweb="input"]{ background:#1a1d25 !important; color:#f4f5f7 !important; }
[data-testid="stTabs"] [data-baseweb="tab"]{ font-weight:600; font-size:.98rem; color:#9ca3af; }
[data-testid="stTabs"] [aria-selected="true"]{ color:#fbbf24 !important; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] *{ color:#9aa3b2 !important; }
section[data-testid="stSidebar"]{ background:#0d0f14; border-right:1px solid rgba(255,255,255,.06); }
[data-testid="stExpander"]{ background:#111319; border:1px solid rgba(255,255,255,.07); border-radius:12px; }
</style>
""", unsafe_allow_html=True)


def time_left(end_iso):
    if not end_iso:
        return None
    s = end_iso.replace("Z", "+00:00")
    try:
        end = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    return (end - now).total_seconds()


def fmt_left(secs):
    if secs is None:
        return "?"
    if secs <= 0:
        return "종료됨"
    h, m = int(secs // 3600), int((secs % 3600) // 60)
    if h >= 24:
        return f"{h // 24}일 {h % 24}시간"
    if h > 0:
        return f"{h}시간 {m}분"
    return f"{m}분"


# ---------------- 사이드바 ----------------
st.sidebar.header("필터 / 설정")
st.sidebar.caption(f"모드: **{config.MODE.upper()}**  |  실낙찰가: **{config.SOLD_PROVIDER}**")

auto_refresh = st.sidebar.checkbox("⏱ 5분마다 자동 새로고침", value=True,
                                   help="화면을 5분마다 최신 DB로 자동 갱신 (수집은 별도)")
if auto_refresh:
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=300_000, key="auto5min")
    except Exception:
        pass

min_roi = st.sidebar.slider("최소 ROI (비딩 후보 기준)", 0.0, 2.0, float(config.MIN_ROI), 0.05)
min_score = st.sidebar.slider("최소 매칭 신뢰도", 0, 100, int(config.MIN_MATCH_SCORE), 5)
max_hours = st.sidebar.slider("남은 시간 최대(시간)", 1, 72, 10, 1)
only_good = st.sidebar.checkbox("비딩 후보만 보기", value=False)

if st.sidebar.button("🔄 데이터 새로고침 (eBay 다시 수집)"):
    with st.spinner("eBay 수집 + 시세 매칭 중..."):
        import collector
        try:
            db.clear_failed_sold_cache()   # 매칭 실패캐시 비워 개선된 매칭 즉시 반영
            n = collector.run()
            st.sidebar.success(f"{n}개 매물 수집 완료")
        except Exception as e:
            st.sidebar.error(f"수집 실패: {e}")

# ---------------- 본문 ----------------
st.markdown(
    "<div style='display:flex;align-items:center;gap:12px;margin:2px 0 4px'>"
    "<div style='width:32px;height:32px;border-radius:9px;flex-shrink:0;"
    "background:linear-gradient(135deg,#fbbf24,#fb7c3c)'></div>"
    "<span style='font-size:26px;font-weight:700;letter-spacing:-.5px;"
    "background:linear-gradient(90deg,#fbbf24,#fb7c5c);-webkit-background-clip:text;"
    "-webkit-text-fill-color:transparent'>Pokemon PSA 10 — 종료임박 비딩 대시보드</span>"
    "</div>", unsafe_allow_html=True)
_loc = config.ITEM_LOCATION_COUNTRY or "전체"
st.caption(f"입찰 {config.MIN_BID_COUNT}건+ · 배송 ${config.MAX_SHIPPING:.0f} 이하 · "
           f"예산 ${config.MAX_BID:.0f} · 영어판 · 종료임박순")

rows = db.get_listings()
if not rows:
    st.warning("데이터가 없습니다. 사이드바의 '데이터 새로고침'을 누르거나 `python collector.py`를 실행하세요.")
    st.stop()

df = pd.DataFrame(rows)
df["secs_left"] = df["end_time"].apply(time_left)
# 이미 종료된 경매 제외(다음 수집 전까지 DB에 남아있어도 입찰 불가). 종료시각 불명(None)은 유지.
df = df[df["secs_left"].isna() | (df["secs_left"] > 0)].reset_index(drop=True)
if df.empty:
    st.warning("진행 중인 경매가 없습니다 (수집된 매물이 모두 종료됨). "
               "다음 자동수집을 기다리거나, 사이드바 **새로고침**을 누르세요.")
    st.stop()
df["남은시간"] = df["secs_left"].apply(fmt_left)
df["ROI%"] = df["roi"].apply(lambda x: round(x * 100, 1) if x is not None else None)

# 실거래가 검증용: eBay 낙찰가 딥링크 + 복붙용 검색어
df["검색어"] = df.apply(
    lambda r: links.build_query(r["pc_console"], r["pc_name"], r["title"], r["match_score"]),
    axis=1,
)
df["sold_url"] = df["검색어"].apply(links.ebay_sold_url)
df["비고"] = df.get("is_steal", 0)
df["비고"] = df["비고"].apply(lambda x: "🔥스틸" if x else "")


def _trend_str(r):
    t = {"up": "📈", "down": "📉", "flat": "➖"}.get(r.get("value_trend"), "")
    flags = []
    at, mv = r.get("all_time_value"), r.get("market_value")
    if at and mv and mv < at * config.DROP_FLAG_RATIO:
        flags.append("⚠️신상/하락")
    if r.get("value_source") == "estimate":
        flags.append("추정")
    return (t + " " + " ".join(flags)).strip()


df["추세"] = df.apply(_trend_str, axis=1)

# 비딩 후보 판정
def _in_window(r):
    return (r["roi"] is not None and r["roi"] >= min_roi
            and r["secs_left"] is not None and 0 < r["secs_left"] <= max_hours * 3600)

def good(r):
    # 신뢰도: sold는 번호확정+표본충분(match_score≥90)이어야 신뢰. 추정가는 매칭 점수로.
    reliable = (r.get("value_source") == "sold" and (r["match_score"] or 0) >= 90) or (
        r.get("value_source") == "estimate" and (r["match_score"] or 0) >= min_score)
    return _in_window(r) and reliable

df["후보"] = df.apply(good, axis=1)

# 신호 컬럼: 🔥스틸 / 🟢후보 / ⚠️저신뢰(시세는 있지만 표본부족·미확정→수동검증)
def _signal(r):
    if r["비고"] == "🔥스틸":
        return "🔥 스틸"
    if r["후보"]:
        return "🟢 후보"
    if r.get("value_source") == "sold" and _in_window(r):
        return "⚠️ 저신뢰"   # 표본 부족/매칭 미확정 → PriceCharting 등으로 직접 확인
    return ""

df["신호"] = df.apply(_signal, axis=1)

# Gixen 스나이프 프리필 링크(eBay번호+권장입찰가 자동입력). 행에서 바로 클릭.
df["Gixen"] = df.apply(
    lambda r: links.gixen_snipe_url(
        links.ebay_item_number(r.get("url"), r.get("item_id")), r.get("max_bid")),
    axis=1,
)

# 셀러(이름·리뷰수). 저평판이면 ⚠️ — 신규셀러의 싼 PSA10 = 사기(가짜슬랩/미발송) 위험.
def _seller_str(r):
    name = r.get("seller_name") or ""
    fb = int(r.get("seller_feedback") or 0)
    if not name:
        return "-"
    return f"{name} ({fb})" + (" ⚠️" if fb < config.SELLER_FLAG_FEEDBACK else "")

df["셀러"] = df.apply(_seller_str, axis=1)


def _fresh(updated):
    if not updated:
        return ""
    try:
        u = dt.datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if u.tzinfo is None:
        u = u.replace(tzinfo=dt.timezone.utc)
    d = (dt.datetime.now(dt.timezone.utc) - u).days
    return f"{d}일 전" + (" ⚠️오래됨" if d > config.STALE_DAYS else "")


# 요약 메트릭
c1, c2, c3, c4 = st.columns(4)
c1.metric("활성 매물", len(df),
          help=f"입찰 {config.MIN_BID_COUNT}건 이상 + 배송/예산/영어 통과. 시세·ROI는 직접 판단")
c2.metric("🟢 신뢰 후보", int(df["후보"].sum()),
          help="시세 신뢰(표본 충분)+ROI 좋은 것 = 도구가 추천(참고용)")
c3.metric("실낙찰가 확보", int((df["value_source"] == "sold").sum()))
c4.metric("종료 임박(1h)",
          int(((df["secs_left"] > 0) & (df["secs_left"] <= 3600)).sum()))

if config.MODE == "demo":
    st.info("지금은 **DEMO 모드** (가짜 eBay 매물 + 샘플 시세). 전체 흐름 확인용입니다.")


def _ago(iso):
    if not iso:
        return "?"
    try:
        t = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return "?"
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    secs = (dt.datetime.now(dt.timezone.utc) - t).total_seconds()
    if secs < 90:
        return "방금"
    if secs < 3600:
        return f"{int(secs // 60)}분 전"
    return f"{int(secs // 3600)}시간 전"


_last = df["collected_at"].max() if "collected_at" in df else None
_stale_collect = ""
try:
    if _last and (dt.datetime.now(dt.timezone.utc) -
                  dt.datetime.fromisoformat(str(_last).replace("Z", "+00:00"))).total_seconds() > 7200:
        _stale_collect = " ⚠️ 2시간+ 미수집 (자동수집 켜졌는지 확인)"
except ValueError:
    pass
st.caption(f"🕒 마지막 수집 {_ago(_last)}{_stale_collect}")

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["🎯 비딩 후보", "🔥 인기·거래량", "📒 거래 기록", "📝 입찰 기록", "💼 포트폴리오"])

# ============== 탭 1: 비딩 후보 ==============
with tab1:
    view = df.copy().sort_values("secs_left", na_position="last")
    if only_good:
        view = view[view["후보"]]
    _gx_marks = db.get_gixen_marks()   # Gixen 등록 체크(영구 저장)
    _excluded = db.get_excluded()      # 제외(블랙리스트) — 화면+다음수집에서 빠짐
    view = view[~view["item_id"].isin(_excluded)]
    # (입찰여지 필터 제거 — 시세/ROI는 사용자가 직접 판단. 입찰 N건 이상 활성 매물 모두 표시)
    if _gx_marks and st.checkbox(f"☑️ Gixen 등록한 {len(_gx_marks)}건 숨기기 (남은 것만 보기)"):
        view = view[~view["item_id"].isin(_gx_marks)]
    if _excluded:
        with st.expander(f"🚫 제외한 매물 {len(_excluded)}건 (복원 가능)"):
            for _eid, _et in db.get_excluded_list():
                _c1, _c2 = st.columns([8, 1])
                _c1.caption(_et or _eid)
                _c2.button("복원", key=f"rs_{_eid}", on_click=_restore_item, args=(_eid,))

    _sortby = st.radio("정렬", ["종료임박순", "ROI순", "예상수익순"],
                       horizontal=True, label_visibility="collapsed")
    if _sortby == "ROI순":
        view = view.sort_values("roi", ascending=False, na_position="last")
    elif _sortby == "예상수익순":
        view = view.sort_values("profit", ascending=False, na_position="last")

    st.caption(f"후보 {len(view)}건 · 권장 최대입찰가까지만 Gixen에 걸어두세요")
    if view.empty:
        st.info("지금 조건에 맞는 후보가 없습니다. (PSA10 차익 기회는 원래 드물어요)")

    def _money(v, dec=0):
        return f"${v:,.{dec}f}" if pd.notna(v) else "-"

    _BADGE = {"🟢 후보": ("🟢", "후보"), "🔥 스틸": ("🔥", "스틸"),
              "⚠️ 저신뢰": ("⚠️", "저신뢰·표본부족")}

    _manual_prices = db.get_all_manual_prices()   # 카드별 수동시세(한 번에 로드)
    for _, r in view.iterrows():
        ic, lbl = _BADGE.get(r["신호"], ("•", "관망"))
        with st.container(border=True):
            top = st.columns([1.3, 1.3, 5])
            _eimg, _cimg = r.get("image"), r.get("card_image")
            if pd.notna(_eimg) and _eimg:
                top[0].markdown(_card_img_html(_upscale_img(_eimg), "실물"),
                                unsafe_allow_html=True)
            if pd.notna(_cimg) and _cimg:
                top[1].markdown(_card_img_html(_cimg, "공식"),
                                unsafe_allow_html=True)
            with top[2]:
                hc = st.columns([8, 2])
                _done = "✅ " if r["item_id"] in _gx_marks else ""
                hc[0].markdown(f"#### {ic} {_done}{r['title']}")
                hc[1].markdown(
                    f"<div style='text-align:right;padding-top:8px;color:#94a3b8;font-weight:700'>⏳ {r['남은시간']}</div>",
                    unsafe_allow_html=True)
                _sfb = int(r["seller_feedback"]) if pd.notna(r.get("seller_feedback")) else 0
                _sname = r["seller_name"] if pd.notna(r.get("seller_name")) else "-"
                _swarn = ("  ·  ⚠️ 신규/저평판 셀러 주의"
                          if _sfb < config.SELLER_FLAG_FEEDBACK else "")
                st.caption(f"👤 {_sname} · 리뷰 {_sfb}{_swarn}")

            # 수동 시세(PriceCharting) 적용 — PPT보다 우선
            _ck = collector._card_key(r.get("title"), r.get("matched_name"))
            _manual = _manual_prices.get(_ck)
            if _manual:
                _mv = valuation.evaluate(r.get("current_bid") or 0, r.get("shipping") or 0, _manual)
                r["market_value"], r["max_bid"] = _manual, _mv["max_bid"]
                r["profit"], r["breakeven_bid"] = _mv["profit"], _mv["breakeven_bid"]
                r["ROI%"] = (_mv["roi"] * 100) if _mv["roi"] is not None else None
                r["value_source"] = "manual"

            _pf = r.get("profit")
            _pos = pd.notna(_pf) and _pf > 0
            _neg = pd.notna(_pf) and _pf < 0
            _pcol = "#4ade80" if _pos else ("#f87171" if _neg else "#f4f5f7")
            _pbg = "rgba(74,222,128,.10)" if _pos else ("rgba(248,113,113,.08)" if _neg else "#1a1d25")

            def _mc(lab, val, col="#f4f5f7", bg="#1a1d25"):
                return (f"<div style='flex:1;min-width:0;background:{bg};border-radius:11px;padding:11px 14px'>"
                        f"<div style='font-size:12px;color:#9aa3b2'>{lab}</div>"
                        f"<div style='font-size:20px;font-weight:700;color:{col};margin-top:3px'>{val}</div></div>")
            st.markdown(
                "<div style='display:flex;gap:11px;margin:14px 0 10px'>"
                + _mc("현재가", _money(r["current_bid"]))
                + _mc("시세", _money(r["market_value"]))
                + _mc("권장 최대입찰", _money(r["max_bid"]), "#fbbf24")
                + _mc("예상수익", _money(r["profit"]), _pcol, _pbg)
                + "</div>", unsafe_allow_html=True)

            _mn = r["matched_name"] if pd.notna(r.get("matched_name")) else "-"
            _sn = int(r["sold_n"]) if pd.notna(r.get("sold_n")) else 0
            _roi_s = f" · ROI {r['ROI%']:.0f}%" if pd.notna(r.get("ROI%")) else ""
            st.caption(f"손익분기 {_money(r['breakeven_bid'])} · 표본 {_sn}건{_roi_s} · 시세기준 {_mn}")
            # 가격-상식 가드: 입찰 많이 붙었는데 현재가가 시세의 40% 미만 →
            # 실물이 PSA8·9(제목만 PSA10)이거나 오매칭일 확률 큼. 시장(입찰)이 정답.
            _cb = (r.get("current_bid") or 0) + (r.get("shipping") or 0)
            _mvv = r.get("market_value")
            if pd.notna(_mvv) and _mvv and _cb and _cb < _mvv * 0.4:
                _bc = int(r["bid_count"]) if pd.notna(r.get("bid_count")) else 0
                _pct = _cb / _mvv * 100
                st.warning(
                    f"⚠️ **실물 등급/매칭 의심** — 입찰 {_bc}명이 붙었는데 현재가(+배송)가 "
                    f"시세의 **{_pct:.0f}%**뿐입니다. 시장이 이걸 PSA10으로 안 본다는 뜻 → "
                    f"**실물이 PSA8·9인데 제목만 PSA10**이거나 **다른 카드와 오매칭**일 가능성이 큽니다. "
                    f"실물 이미지의 PSA 등급라벨·카드번호를 꼭 확인하세요. (위 예상수익 무시)")
            _own = db.get_own_price(_ck)
            if _own:
                st.caption(f"📈 자체 낙찰 중앙 ${_own['median']:.0f} (${_own['min']:.0f}~${_own['max']:.0f} · {_own['n']}건)")

            cc = st.columns([2, 2, 2, 2, 3])
            cc[0].toggle("Gixen", value=(r["item_id"] in _gx_marks), key=f"gx_{r['item_id']}",
                         on_change=_toggle_gixen, args=(r["item_id"],))
            if r.get("url"):
                cc[1].link_button("eBay", r["url"], use_container_width=True)
            cc[2].link_button("시세검증",
                links.pricecharting_url(links.verify_query(r.get("matched_name"), r.get("title"))),
                use_container_width=True)
            cc[3].button("🚫 제외", key=f"ex_{r['item_id']}", use_container_width=True,
                         on_click=_exclude_item, args=(r["item_id"], r["title"]))
            cc[4].number_input(
                "내 최대입찰가($)", min_value=0.0, step=1.0,
                value=float(round(r["max_bid"], 2)) if pd.notna(r.get("max_bid")) else 0.0,
                key=f"bid_{r['item_id']}")
            # 🅖 Gixen 자동등록 — '내 최대입찰가'(위 입력칸, 기본=권장가)로 스나이프 등록. 클릭=컨펌.
            _itemno = links.ebay_item_number(r.get("url"), r.get("item_id"))
            _gxres = st.session_state.get(f"gxres_{r['item_id']}")
            if _itemno and gixen_api.enabled():
                gb = st.columns([2, 6])
                gb[0].button("🅖 Gixen 자동등록", key=f"gxapi_{r['item_id']}",
                             use_container_width=True,
                             on_click=_register_gixen, args=(r["item_id"], _itemno))
                if _gxres and _gxres.get("ok"):
                    gb[1].success(f"✅ Gixen 등록됨 · 아이템 {_itemno} · 최대 ${_gxres['bid']:.2f}")
                elif _gxres:
                    gb[1].error(f"❌ Gixen 실패: {_gxres.get('msg')}")
                else:
                    gb[1].caption(f"아이템 `{_itemno}` · 위 '내 최대입찰가'로 등록 (종료 {config.GIXEN_BIDOFFSET}초 전)")
            elif _itemno:
                _bidv = f"{r['max_bid']:.2f}" if pd.notna(r.get("max_bid")) else "-"
                st.caption(f"🅖 Gixen 등록용 → 아이템번호 `{_itemno}` · 권장입찰가 \\${_bidv} "
                           "(.env에 GIXEN_USERNAME/PASSWORD 넣으면 자동등록 버튼이 생깁니다)")
            _mp_key = f"mp_{r['item_id']}"
            st.number_input("✏️ 수동 시세($) — 이 카드 전체 적용, 0=해제",
                min_value=0.0, value=float(_manual or 0), step=1.0, key=_mp_key,
                on_change=_save_manual, args=(_ck, _mp_key))

    st.markdown(
        f"🔎 추가 검증 도구: [130point]({links.point130_url()}) · "
        f"[PSA APR]({links.psa_apr_url()}) · [alt.xyz]({links.alt_url()})"
    )

# ============== 탭 2: 인기·거래량 ==============
with tab2:
    st.caption("**거래량(표본)이 많은 = 인기·환금성 높은 카드** 순. 사고팔기 쉬운 카드 위주로 보세요.")
    pop = df.sort_values(["sales_week", "sold_n", "bid_count"],
                         ascending=[False, False, False])
    popshow = pop[[
        "title", "market_value", "sales_week", "sold_n", "bid_count", "추세",
        "남은시간", "ROI%", "max_bid", "url", "sold_url",
    ]].rename(columns={
        "title": "eBay 제목", "market_value": "시세($)", "sales_week": "주당판매",
        "sold_n": "거래량(표본)", "bid_count": "입찰수", "max_bid": "권장최대입찰가($)",
        "url": "매물", "sold_url": "낙찰가검증",
    })
    st.dataframe(
        popshow, use_container_width=True, hide_index=True,
        column_config={
            "매물": st.column_config.LinkColumn("매물", display_text="eBay"),
            "낙찰가검증": st.column_config.LinkColumn("낙찰가검증", display_text="실거래"),
            "주당판매": st.column_config.NumberColumn(
                "주당판매", format="%.1f", help="일주일에 몇 장 팔리나 = 환금성(되팔 때 현금화 속도)"),
            "거래량(표본)": st.column_config.NumberColumn(
                "거래량(표본)", help="집계된 PSA10 낙찰 건수 = 인기/유동성"),
            "시세($)": st.column_config.NumberColumn(format="%.0f"),
            "권장최대입찰가($)": st.column_config.NumberColumn(format="%.0f"),
            "ROI%": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )

# ============== 탭 3: 거래 기록 ==============
with tab3:
    st.caption("내가 실제로 사고판 결과를 기록 → 도구가 잘 맞히는지, 내 수익이 얼마인지 추적합니다.")
    with st.form("add_trade", clear_on_submit=True):
        f1, f2, f3, f4 = st.columns([3, 1, 1, 1])
        t_card = f1.text_input("카드명")
        t_buy = f2.number_input("매입가($)", min_value=0.0, step=1.0)
        t_mkt = f3.number_input("현재시세($, 선택)", min_value=0.0, step=1.0,
                                help="보유중 카드의 현재 시세 → 포트폴리오 평가손익 계산")
        t_sell = f4.number_input("판매가($, 미판매=0)", min_value=0.0, step=1.0)
        t_note = st.text_input("메모 (선택)")
        if st.form_submit_button("기록 추가") and t_card:
            db.add_trade(t_card, t_buy, t_sell or None, t_note, t_mkt or None)
            st.success("추가됨")
            st.rerun()

    trades = db.get_trades()
    if trades:
        tdf = pd.DataFrame(trades)
        tdf["실현손익"] = tdf.apply(
            lambda x: (x["sell"] - x["buy"]) if x["sell"] else None, axis=1)
        closed = tdf[tdf["sell"].notna()]
        m1, m2, m3 = st.columns(3)
        m1.metric("총 거래", len(tdf))
        m2.metric("실현 손익", f"${closed['실현손익'].sum():,.0f}" if len(closed) else "$0")
        win = (closed["실현손익"] > 0).mean() * 100 if len(closed) else 0
        m3.metric("승률", f"{win:.0f}%")
        st.dataframe(
            tdf[["created_at", "card", "buy", "sell", "실현손익", "note"]].rename(columns={
                "created_at": "날짜", "card": "카드", "buy": "매입가", "sell": "판매가", "note": "메모"}),
            use_container_width=True, hide_index=True,
        )
        st.caption("삭제하려면 아래에 기록 번호(id)를 입력하세요.")
        did = st.number_input("삭제할 id", min_value=0, step=1, value=0)
        if st.button("삭제") and did:
            db.delete_trade(int(did))
            st.rerun()
    else:
        st.info("아직 기록이 없습니다. 위에서 추가해보세요.")

# ============== 탭 4: 입찰 기록 (Gixen 스나이핑 결과) ==============
with tab4:
    st.caption("Gixen 입찰 결과 추적 → 내 입찰가가 적정했는지, 좋은 걸 아슬아슬하게 놓쳤는지 분석.")
    with st.form("add_bid", clear_on_submit=True):
        b1, b2, b3, b4 = st.columns([3, 1, 1, 1])
        bcard = b1.text_input("카드명")
        bmy = b2.number_input("내 입찰가($)", min_value=0.0, step=1.0)
        bfin = b3.number_input("최종 낙찰가($)", min_value=0.0, step=1.0)
        bval = b4.number_input("시세($)", min_value=0.0, step=1.0)
        bres = st.selectbox("결과", ["패찰", "낙찰", "진행중"])
        if st.form_submit_button("입찰 기록 추가") and bcard:
            db.add_bid(bcard, bmy, bfin or None, bval or None, bres, note="수동입력")
            st.success("추가됨")
            st.rerun()

    bids = db.get_bids()
    if bids:
        bdf = pd.DataFrame(bids)
        bdf["차이"] = bdf.apply(
            lambda r: round((r["final_price"] or 0) - (r["my_bid"] or 0), 2)
            if pd.notna(r["final_price"]) else None, axis=1)
        m1, m2, m3 = st.columns(3)
        m1.metric("총 입찰", len(bdf))
        won = int((bdf["result"] == "낙찰").sum())
        m2.metric("낙찰률", f"{won/len(bdf)*100:.0f}%" if len(bdf) else "0%")
        lost = bdf[bdf["result"] == "패찰"]
        avoided = int((lost["net_if_won"] < 0).sum()) if len(lost) else 0
        m3.metric("잘 진 패찰", f"{avoided}건",
                  help="패찰인데 이겼다면 NET 손해였을 것 = 안 사길 잘함")
        st.dataframe(
            bdf[["id", "created_at", "card", "my_bid", "final_price", "차이",
                 "market_value", "net_if_won", "result"]].rename(columns={
                     "created_at": "날짜", "card": "카드", "my_bid": "내입찰",
                     "final_price": "최종가", "market_value": "시세",
                     "net_if_won": "이겼다면NET수익", "result": "결과"}),
            use_container_width=True, hide_index=True,
        )
        st.caption("**차이** = 최종가 − 내입찰(얼마 차로 졌나) · **이겼다면NET수익** = 그 가격에 "
                   "낙찰했다면 되팔아 남는 실수익(수수료 13%+$3·배송 반영). **음수 = 이겼으면 손해**(잘 진 것)")
        did = st.number_input("삭제할 입찰 id", min_value=0, step=1, value=0, key="del_bid")
        if st.button("입찰 기록 삭제") and did:
            db.delete_bid(int(did))
            st.rerun()
    else:
        st.info("아직 입찰 기록이 없습니다. 위에서 추가하거나, 저한테 말하면 저장해드려요.")

# ============== 탭 5: 투자 포트폴리오 + 비용 ==============
with tab5:
    db.seed_costs_if_empty()
    trades_c = db.get_trades()
    costs = db.get_costs()

    def _annual(amount, kind, period):
        return float(amount) * (12 if period == "monthly" else 1) if kind == "recurring" else 0.0

    setup_total = float(sum(c["amount"] for c in costs if c["kind"] == "setup"))
    annual_total = float(sum(_annual(c["amount"], c["kind"], c["period"]) for c in costs))

    # ----- 포트폴리오 집계 -----
    held = [t for t in trades_c if not t.get("sell")]
    sold = [t for t in trades_c if t.get("sell")]
    invested_total = float(sum(t["buy"] for t in trades_c))            # 누적 매입 총액
    held_cost = float(sum(t["buy"] for t in held))                     # 보유 원가
    held_value = float(sum((t.get("market") or t["buy"]) for t in held))  # 보유 평가액(시세없으면 원가)
    unrealized = held_value - held_cost                               # 미실현 손익
    realized = float(sum((t["sell"] - t["buy"]) for t in sold))        # 실현 손익
    net_pl = realized + unrealized - setup_total                       # 총 순손익(설립비 차감)

    st.markdown("#### 💼 투자 포트폴리오")
    p = st.columns(4)
    p[0].metric("총 투자원금", f"${invested_total:,.0f}", help="지금까지 카드 매입에 쓴 총액(보유+판매 전체)")
    p[1].metric("보유 평가액", f"${held_value:,.0f}", help="보유중 카드의 현재시세 합(시세 미입력시 매입가로 계산)")
    p[2].metric("미실현 손익", f"${unrealized:,.0f}", help="보유 평가액 − 보유 원가")
    p[3].metric("실현 손익", f"${realized:,.0f}", help="판매완료 카드의 매도−매입")

    if held:
        hdf = pd.DataFrame(held)
        if "market" not in hdf:
            hdf["market"] = None
        hdf["평가손익"] = hdf.apply(
            lambda r: round(r["market"] - r["buy"], 2) if pd.notna(r.get("market")) else None, axis=1)
        st.dataframe(
            hdf[["id", "card", "buy", "market", "평가손익", "created_at"]].rename(columns={
                "id": "id", "card": "카드", "buy": "매입가", "market": "현재시세", "created_at": "매입일"}),
            use_container_width=True, hide_index=True)
        st.caption("**현재시세**는 **거래 기록 탭**에서 입력(또는 카드 시세검증으로 확인). 미입력 카드는 평가손익 '-'.")
    else:
        st.info("보유중인 카드가 없습니다. **거래 기록 탭**에서 매입을 기록하세요.")

    st.divider()

    # ----- 운영 비용 + 순손익 -----
    st.markdown("#### 🧾 운영 비용")
    c = st.columns(3)
    c[0].metric("설립비(1회성)", f"${setup_total:,.0f}")
    c[1].metric("연 고정비", f"${annual_total:,.0f}", help=f"월 약 ${annual_total/12:,.0f}")
    c[2].metric("총 순손익", f"${net_pl:,.0f}", help="실현+미실현 − 설립비 (이후 매년 고정비 추가 차감)")
    st.caption(
        f"총 순손익 = 실현 \\${realized:,.0f} + 미실현 \\${unrealized:,.0f} − 설립비 \\${setup_total:,.0f} "
        f"= **\\${net_pl:,.0f}**  ·  이후 매년 고정비 약 \\${annual_total:,.0f}(월 \\${annual_total/12:,.0f}) 발생")

    _PER_KO = {"once": "1회", "monthly": "월", "yearly": "년"}
    with st.expander("비용 내역 보기 / 추가 / 삭제"):
        if costs:
            cdf = pd.DataFrame(costs)
            cdf["금액"] = cdf["amount"].map(lambda v: f"${v:,.2f}")
            cdf["구분"] = cdf["kind"].map(lambda k: "설립비" if k == "setup" else "고정비")
            cdf["주기"] = cdf["period"].map(lambda x: _PER_KO.get(x, x))
            st.dataframe(cdf[["id", "구분", "item", "금액", "주기", "note"]].rename(
                columns={"item": "항목", "note": "메모"}),
                use_container_width=True, hide_index=True)
        with st.form("add_cost", clear_on_submit=True):
            c1, c2 = st.columns([3, 1])
            ci = c1.text_input("항목명")
            ca = c2.number_input("금액($)", min_value=0.0, step=1.0)
            c3, c4 = st.columns(2)
            ck = c3.selectbox("종류", ["recurring", "setup"],
                              format_func=lambda x: "반복(고정비)" if x == "recurring" else "1회성(설립비)")
            cp = c4.selectbox("주기", ["yearly", "monthly", "once"],
                              format_func=lambda x: _PER_KO[x])
            cn = st.text_input("메모(선택)")
            if st.form_submit_button("비용 추가") and ci:
                db.add_cost(ci, ca, ck, "once" if ck == "setup" else cp, cn)
                st.success("추가됨")
                st.rerun()
        dcid = st.number_input("삭제할 비용 id", min_value=0, step=1, value=0, key="del_cost")
        if st.button("비용 삭제") and dcid:
            db.delete_cost(int(dcid))
            st.rerun()

st.divider()
with st.expander("계산 방식 / 시세 로직 보는 법"):
    st.markdown(
        f"""
- **시세($)** = eBay **최근 가중 현재시세**(smartMarketPrice). 출시 거품·과거 고가가 아니라 **지금 팔리는 값**.
  단, 최근 표본이 짧고(<{config.MIN_VALUE_DAYS}일) 신뢰도가 낮으면 **역대 중앙값으로 보수 보정**(들쭉날쭉 방지).
  거래 많은 카드의 단기 시세는 신뢰도 high라 그대로 사용합니다.
- **위험 보정**: 📉하락 추세면 시세 ×{config.TREND_DOWN_FACTOR}. **⚠️신상/하락**(현재<역대×{config.DROP_FLAG_RATIO:.0%})이면서
  하락이면 목록서 제외(단 ROI {config.RISKY_ALERT_ROI:.0%}+면 알림).
- **예상수익** = 시세 − 판매수수료 − (현재가 + 배송비). 판매 방식 **{config.SELL_MODE}**.
  PSA Vault 위탁 요율(공식): <\\$100 = 13%+\\$3 · \\$100~499 = 13% · \\$500~999 = 12% ·
  \\$1k~2.5k = 10% · \\$2.5k~5k = 9% · \\$5k+ = 7% (eBay 수수료 별도 없음, 발송비 구매자 부담).
- **권장최대입찰가** = 목표 수익(${config.MIN_PROFIT:.0f}+)·목표 ROI({config.MIN_ROI:.0%})를 남기는 상한 → eBay 최대입찰가에 입력.
- **시세카드(검증)** 열이 eBay 제목과 다르면 매칭 오류일 수 있으니 확인하세요.
- 알림: 종료 {config.NOTIFY_WINDOW_HOURS:.0f}시간 내 1차 + {config.FINAL_ALERT_MINUTES:.0f}분 전 2차 리마인드.
        """
    )
