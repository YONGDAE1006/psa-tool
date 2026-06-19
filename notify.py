"""
텔레그램 푸시 알림.
강력한 비딩 후보가 뜨면 폰으로 알려줌 (대시보드를 안 보고 있어도 됨).

설정(.env):
  TELEGRAM_BOT_TOKEN = @BotFather 로 만든 봇 토큰
  TELEGRAM_CHAT_ID   = 내 chat id (봇에게 아무 메시지 보낸 뒤 확인)
"""
import datetime as dt
import json
import re

import requests

import config
import links

_session = requests.Session()


def enabled():
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def send(text, buttons=None):
    """buttons: [[(라벨, url), ...], ...] 형태의 인라인 버튼(탭하면 열림)."""
    if not enabled():
        return False
    data = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    if buttons:
        kb = [[{"text": t, "url": u} for (t, u) in row if u] for row in buttons]
        data["reply_markup"] = json.dumps({"inline_keyboard": kb})
    try:
        r = _session.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            data=data, timeout=15,
        )
        return r.ok
    except Exception:
        return False


def _secs_left(end_iso):
    if not end_iso:
        return None
    try:
        end = dt.datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (end - dt.datetime.now(dt.timezone.utc)).total_seconds()


def _fmt_left(secs):
    if secs is None:
        return "?"
    h, m = int(secs // 3600), int((secs % 3600) // 60)
    return f"{h}시간 {m}분" if h else f"{m}분"


def ebay_item_number(r):
    """Gixen 등록에 쓰는 eBay 숫자 아이템 번호 추출."""
    return links.ebay_item_number(r.get("url"), r.get("item_id"))


def _query(r):
    return links.build_query(r.get("pc_console"), r.get("pc_name"),
                             r.get("title"), r.get("match_score") or 0)


def format_candidate(r, risky=False):
    if risky:
        tag = "⚠️ 위험(하락) — 신중! 그래도 매우 쌈"
    else:
        tag = "🔥 스틸 (입찰 적지만 저평가)" if r.get("is_steal") else "✅ 비딩 후보"
    trend = {"up": "📈", "down": "📉"}.get(r.get("value_trend"), "")
    left = _fmt_left(_secs_left(r.get("end_time")))
    num = ebay_item_number(r)
    lines = [
        f"<b>{tag}</b> · 종료 {left} 전",
        f"<b>{r.get('title','')[:95]}</b>",
        "",
        f"💵 현재가 ${r.get('current_bid',0):,.0f}  ·  시세 ${r.get('market_value') or 0:,.0f} {trend} (표본 {int(r.get('sold_n') or 0)})",
        f"🎯 권장 최대입찰가  <b>${r.get('max_bid') or 0:,.0f}</b>",
        f"📈 예상수익 ${r.get('profit') or 0:,.0f} (ROI {(r.get('roi') or 0)*100:.0f}%)",
    ]
    if num:
        lines.append(f"🔢 eBay 번호 <code>{num}</code> (탭해서 복사 → Gixen)")
    return "\n".join(lines)


def build_buttons(r):
    """폰에서 바로 행동할 수 있는 탭 버튼."""
    q = _query(r)
    rows = []
    if r.get("url"):
        rows.append([("🟢 eBay 앱에서 입찰", r["url"])])
    rows.append([("⏱ Gixen 등록", links.gixen_url()),
                 ("💰 최근 낙찰가", links.ebay_sold_url(q))])
    rows.append([("📊 시세·그래프(PriceCharting)", links.pricecharting_url(q))])
    return rows
