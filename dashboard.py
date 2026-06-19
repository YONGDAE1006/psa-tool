"""
대시보드 (웹 화면).
실행:  streamlit run dashboard.py

종료임박순 eBay PSA10 매물 + PriceCharting 시세 비교 + 비딩 후보 하이라이트.
"""
import datetime as dt

import pandas as pd
import streamlit as st

import config
import db
import links

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
max_hours = st.sidebar.slider("남은 시간 최대(시간)", 1, 72, 24, 1)
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
c1.metric("표시 매물", len(df))
c2.metric("비딩 후보", int(df["후보"].sum()))
c3.metric("실낙찰가 확보", int((df["value_source"] == "sold").sum()))
c4.metric("종료 임박(1시간 내)", int((df["secs_left"].fillna(9e9) <= 3600).sum()))

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

tab1, tab2, tab3 = st.tabs(["🎯 비딩 후보", "🔥 인기·거래량", "📒 거래 기록"])

# ============== 탭 1: 비딩 후보 ==============
with tab1:
    view = df.copy().sort_values("secs_left", na_position="last")
    if only_good:
        view = view[view["후보"]]

    show = view[[
        "신호", "남은시간", "title", "current_bid", "max_bid",
        "ROI%", "profit", "추세", "market_value", "all_time_value", "sold_n",
        "matched_name", "bid_count", "shipping", "url", "sold_url",
    ]].rename(columns={
        "title": "eBay 제목", "current_bid": "현재가($)", "max_bid": "권장최대입찰가($)",
        "profit": "예상수익($)", "market_value": "시세($)", "all_time_value": "역대시세($)",
        "sold_n": "표본", "matched_name": "시세카드(검증)", "bid_count": "입찰수",
        "shipping": "배송비($)", "url": "매물", "sold_url": "낙찰가검증",
    })

    st.caption("👇 **행을 클릭**하면 아래 상세가 나옵니다 · 열 제목 클릭=정렬")
    event = st.dataframe(
        show, use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config={
            "신호": st.column_config.TextColumn("신호", help="🟢후보 / 🔥스틸"),
            "매물": st.column_config.LinkColumn("매물", display_text="eBay"),
            "낙찰가검증": st.column_config.LinkColumn(
                "낙찰가검증", display_text="실거래", help="이 카드의 eBay 실제 낙찰가(Sold)"),
            "시세카드(검증)": st.column_config.TextColumn(
                "시세카드(검증)", help="시세를 가져온 카드. eBay 제목과 다르면 매칭 오류!"),
            "예상수익($)": st.column_config.NumberColumn(format="%.0f"),
            "권장최대입찰가($)": st.column_config.NumberColumn(
                "권장최대입찰가($)", format="%.0f",
                help="eBay '최대 입찰가'에 넣으면 목표 수익 남기는 선까지만 자동 입찰"),
            "배송비($)": st.column_config.NumberColumn(format="%.2f"),
            "시세($)": st.column_config.NumberColumn(
                "시세($)", format="%.0f", help="ROI 계산 기준 현재 시세(최근 가중·위험 보정)"),
            "역대시세($)": st.column_config.NumberColumn(
                "역대시세($)", format="%.0f", help="역대 중앙값. 현재<역대=저점 / 현재>역대=추격 주의"),
            "표본": st.column_config.NumberColumn("표본", help="실낙찰 건수(많을수록 신뢰↑)"),
            "추세": st.column_config.TextColumn(
                "추세", help="📈상승/📉하락 · ⚠️신상/하락 · 신뢰↓"),
            "현재가($)": st.column_config.NumberColumn(format="%.2f"),
            "ROI%": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )

    st.markdown(
        f"🔎 추가 검증: [130point]({links.point130_url()}) · "
        f"[PSA APR]({links.psa_apr_url()}) · [alt.xyz]({links.alt_url()})"
    )

    st.divider()
    st.subheader("🔍 카드 상세")
    _selrows = event.selection.rows if event and event.selection else []
    if not _selrows:
        st.info("위 표에서 카드 행을 클릭하세요.")
    else:
        r = view.iloc[_selrows[0]]

        def _m(v, p="$"):
            return f"{p}{v:,.0f}" if v is not None and not pd.isna(v) else "-"

        st.markdown(f"### {r['title']}")
        if r.get("matched_name"):
            st.caption(f"🔗 시세 기준 카드: **{r['matched_name']}** (eBay 제목과 다르면 매칭 오류일 수 있음)")
        a, b, c, d = st.columns(4)
        a.metric("현재시세", _m(r["market_value"]))
        b.metric("역대중앙값", _m(r["all_time_value"]))
        c.metric("권장최대입찰가", _m(r["max_bid"]))
        roi_txt = f"ROI {r['ROI%']:.0f}%" if pd.notna(r["ROI%"]) else ""
        d.metric("예상수익", _m(r["profit"]), roi_txt)

        vd = f"기준 {int(r['value_days'])}일 · " if pd.notna(r.get("value_days")) else ""
        st.caption(
            f"추세 {r['추세'] or '-'} · 신뢰도 {r.get('value_confidence') or '-'} · "
            f"{vd}갱신 {_fresh(r.get('value_updated')) or '-'} · 낙찰표본 {int(r['sold_n'] or 0)}건 · "
            f"환금성 주 {r.get('sales_week') if pd.notna(r.get('sales_week')) else '-'}장 · "
            f"현재가 {_m(r['current_bid'])} · 손익분기 {_m(r['breakeven_bid'])}"
        )

        if pd.notna(r["market_value"]) and pd.notna(r["all_time_value"]):
            st.bar_chart(
                pd.DataFrame({"시세($)": [r["market_value"], r["all_time_value"]]},
                             index=["현재", "역대중앙"]), height=200)

        st.markdown(
            f"📊 **전체/1년 그래프 + 등급별 시세 + 개별 낙찰내역 →** "
            f"[PriceCharting]({links.pricecharting_url(r['검색어'])}) · "
            f"[eBay 낙찰가]({r['sold_url']}) · [130point]({links.point130_url()})"
        )
        st.caption("※ 대시보드 안 실시간 그래프/낙찰표는 PPT 유료($10/월) 필요. 무료에선 위 링크로 확인.")

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
