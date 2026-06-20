"""
대시보드 (웹 화면).
실행:  streamlit run dashboard.py

종료임박순 eBay PSA10 매물 + PriceCharting 시세 비교 + 비딩 후보 하이라이트.
"""
import datetime as dt
import re

import pandas as pd
import streamlit as st

import config
import db
import links


def _upscale_img(url):
    """eBay 썸네일 해상도 ↑ (s-l225 → s-l500). 깨짐 방지."""
    return re.sub(r"s-l\d+", "s-l500", url) if url else url


def _toggle_gixen(item_id):
    """Gixen 등록 체크 토글 → DB 저장(영구 유지)."""
    db.set_gixen_mark(item_id, bool(st.session_state.get(f"gx_{item_id}", False)))

st.set_page_config(page_title="Pokemon PSA10 비딩 대시보드", layout="wide")


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
            n = collector.run()
            st.sidebar.success(f"{n}개 매물 수집 완료")
        except Exception as e:
            st.sidebar.error(f"수집 실패: {e}")

# ---------------- 본문 ----------------
st.title("🃏 Pokemon PSA 10 — 종료임박 비딩 대시보드")
_loc = config.ITEM_LOCATION_COUNTRY or "전체"
st.caption(f"적용 조건: 소재지 **{_loc}** · 배송비 **${config.MAX_SHIPPING:.0f} 미만** · "
           f"현재가 **${config.MAX_BID:.0f} 이하** · 시세 **${config.MIN_MARKET_VALUE:.0f}+** · 예상수익 **${config.MIN_PROFIT:.0f}+** · "
           f"입찰 **{config.MIN_BID_COUNT}건 이상**(ROI {config.HIGH_ROI_OVERRIDE:.0%}+ 는 🔥스틸 예외) · 경매(종료임박순) "
           f"— 조건은 `.env`에서 조정")

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


# 요약 메트릭 — 아래 카드에 실제 표시되는 것(입찰 여지 있는 것 + Gixen 등록)과 일치.
_marks_m = db.get_gixen_marks()
_shown_mask = (
    (df["max_bid"].notna() & (df["current_bid"] < df["max_bid"]))
    | df["item_id"].isin(_marks_m)
)
c1, c2, c3, c4 = st.columns(4)
c1.metric("표시 후보", int(_shown_mask.sum()),
          help="아래 카드에 보이는 입찰 가능 후보. 현재가≥권장입찰('이미 비싼')은 제외돼 수집매물보다 적을 수 있음")
c2.metric("비딩 후보(신뢰)", int(df["후보"].sum()))
c3.metric("실낙찰가 확보", int((df["value_source"] == "sold").sum()))
c4.metric("종료 임박(1h)",
          int((_shown_mask & (df["secs_left"] > 0) & (df["secs_left"] <= 3600)).sum()))

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
st.caption(f"🕒 마지막 수집: **{_ago(_last)}**{_stale_collect}  ·  최신화는 사이드바 **새로고침** 또는 F5")
st.caption("⚠️ 경매는 막판에 가격이 뛸 수 있습니다(스나이핑). ROI는 '기회 신호'이지 확정 수익이 아닙니다.")

tab1, tab2, tab3, tab4 = st.tabs(["🎯 비딩 후보", "🔥 인기·거래량", "📒 거래 기록", "📝 입찰 기록"])

# ============== 탭 1: 비딩 후보 ==============
with tab1:
    view = df.copy().sort_values("secs_left", na_position="last")
    if only_good:
        view = view[view["후보"]]
    _gx_marks = db.get_gixen_marks()   # Gixen 등록 체크(영구 저장)
    # 입찰 여지 있는 것(현재가<권장) + Gixen 등록한 것(추적용)은 항상 표시.
    view = view[
        (view["max_bid"].notna() & (view["current_bid"] < view["max_bid"]))
        | view["item_id"].isin(_gx_marks)
    ]
    if _gx_marks and st.checkbox(f"☑️ Gixen 등록한 {len(_gx_marks)}건 숨기기 (남은 것만 보기)"):
        view = view[~view["item_id"].isin(_gx_marks)]

    _sortby = st.radio("정렬", ["종료임박순", "ROI순", "예상수익순"],
                       horizontal=True, label_visibility="collapsed")
    if _sortby == "ROI순":
        view = view.sort_values("roi", ascending=False, na_position="last")
    elif _sortby == "예상수익순":
        view = view.sort_values("profit", ascending=False, na_position="last")

    st.caption(
        f"📡 종료임박 경매(약 10~15시간 내 종료분)에서 추린 후보 **{len(view)}건**. "
        "조기경매는 종료 직전 가격이 오르니 **권장 최대입찰가**까지만 Gixen에 걸어두세요."
    )
    if view.empty:
        st.info("지금 조건에 맞는 후보가 없습니다. (PSA10 차익 기회는 원래 드물어요)")

    def _money(v, dec=0):
        return f"${v:,.{dec}f}" if pd.notna(v) else "-"

    _BADGE = {"🟢 후보": ("🟢", "후보"), "🔥 스틸": ("🔥", "스틸"),
              "⚠️ 저신뢰": ("⚠️", "저신뢰·표본부족")}

    for _, r in view.iterrows():
        ic, lbl = _BADGE.get(r["신호"], ("•", "관망"))
        with st.container(border=True):
            top = st.columns([1, 1, 5])
            if r.get("image"):
                top[0].image(_upscale_img(r["image"]), caption="실물(판매자)",
                             use_container_width=True)
            if r.get("card_image"):
                top[1].image(r["card_image"], caption="공식(시세기준)",
                             use_container_width=True)
            with top[2]:
                hc = st.columns([8, 2])
                _done = "✅ " if r["item_id"] in _gx_marks else ""
                hc[0].markdown(f"#### {ic} {_done}{r['title']}")
                hc[1].markdown(
                    f"<div style='text-align:right;padding-top:10px;color:#888'>⏳ <b>{r['남은시간']}</b></div>",
                    unsafe_allow_html=True)
                _sfb = int(r.get("seller_feedback") or 0)
                _swarn = ("  ·  ⚠️ **신규/저평판 셀러 — 사기(가짜슬랩·미발송) 주의**"
                          if _sfb < config.SELLER_FLAG_FEEDBACK else "")
                st.caption(
                    f"신호 **{lbl}**  ·  👤 셀러 **{r.get('seller_name') or '-'}** "
                    f"(리뷰 {_sfb} · {r.get('seller_pct') or 0:.0f}%){_swarn}  "
                    "·  📷 왼쪽 두 이미지(실물/공식)가 같은 카드인지 확인하세요")
                st.toggle("⏱ Gixen 등록 완료 (켜두면 새로고침해도 유지)",
                          value=(r["item_id"] in _gx_marks), key=f"gx_{r['item_id']}",
                          on_change=_toggle_gixen, args=(r["item_id"],))

            m = st.columns(4)
            m[0].metric("현재가", _money(r["current_bid"]))
            m[1].metric("시세", _money(r["market_value"]),
                        help=f"실낙찰 표본 {int(r['sold_n'] or 0)}건")
            m[2].metric("권장 최대입찰", _money(r["max_bid"]))
            m[3].metric("예상수익", _money(r["profit"]),
                        help=(f"ROI {r['ROI%']:.0f}%" if pd.notna(r.get("ROI%")) else None))

            _roi = f"**ROI {r['ROI%']:.0f}%**  ·  " if pd.notna(r.get("ROI%")) else ""
            st.markdown(
                f"{_roi}**배송 {_money(r['shipping'], 2)}**  ·  역대 {_money(r['all_time_value'])}"
                f"  ·  표본 {int(r['sold_n'] or 0)}건  ·  손익분기 {_money(r['breakeven_bid'])}"
                f"  ·  {r['추세'] or ''}  ·  🔗 시세기준: **{r.get('matched_name') or '-'}**")

            _num = links.ebay_item_number(r.get("url"), r.get("item_id"))
            c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
            if r.get("url"):
                c1.link_button("🟢 eBay", r["url"], use_container_width=True)
            c2.link_button("⏱ Gixen", links.gixen_url(), use_container_width=True)
            c3.link_button(
                "📊 시세검증",
                links.pricecharting_url(links.verify_query(r.get("matched_name"), r.get("title"))),
                use_container_width=True)
            _mb = c4.number_input(
                "내 최대입찰가($)", min_value=0.0, step=1.0,
                value=float(round(r["max_bid"], 2)) if pd.notna(r.get("max_bid")) else 0.0,
                key=f"bid_{r['item_id']}")
            st.markdown(
                f"📋 Gixen 붙여넣기 → eBay번호 `{_num or '?'}` · 최대입찰 `${_mb:.2f}` "
                "— 위 칸에서 직접 조절(얇은 카드는 시세검증 보고)")

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
        f1, f2, f3 = st.columns([3, 1, 1])
        t_card = f1.text_input("카드명")
        t_buy = f2.number_input("매입가($)", min_value=0.0, step=1.0)
        t_sell = f3.number_input("판매가($, 미판매=0)", min_value=0.0, step=1.0)
        t_note = st.text_input("메모 (선택)")
        if st.form_submit_button("기록 추가") and t_card:
            db.add_trade(t_card, t_buy, t_sell or None, t_note)
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
