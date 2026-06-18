"""
올인원 상주 프로그램.
  - 자동 수집(기본 1시간마다) + 후보 텔레그램 알림
  - 텔레그램 명령 응답: /status /top /run /help (한글 상태/후보/수집 도 됨)
  - 생존신호: 아침·점심·저녁 3회 "정상 작동" 메시지
  - 수집 실패 시 ⚠️ 에러 알림

실행:  python agent.py   (또는 run_agent.bat 더블클릭)
중지:  창을 닫거나 Ctrl + C
"""
import datetime as dt
import time

import requests

import config
import collector
import db
import notify

API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"


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


def _candidates():
    """(전체 rows, 후보 리스트) 반환. 후보 = ROI 기준 + 신뢰 + 미종료."""
    rows = db.get_listings()
    cs = []
    for r in rows:
        reliable = (r.get("value_source") == "sold") or (
            r.get("value_source") == "estimate" and (r.get("match_score") or 0) >= config.MIN_MATCH_SCORE)
        if r.get("roi") is not None and r["roi"] >= config.MIN_ROI and reliable:
            s = notify._secs_left(r.get("end_time"))
            if s and s > 0:
                cs.append(r)
    cs.sort(key=lambda x: -(x.get("roi") or 0))
    return rows, cs


def _status_text():
    rows, cs = _candidates()
    last = max((r.get("collected_at") or "" for r in rows), default="")
    return (f"✅ <b>PSA봇 정상 작동 중</b>\n"
            f"마지막 수집: {_ago(last)}\n"
            f"표시 매물 {len(rows)}건 · 비딩 후보 {len(cs)}건")


def _collect():
    try:
        return collector.run(), None
    except Exception as e:
        return None, str(e)


def _handle(text):
    t = (text or "").strip().lower()
    if t.startswith(("/start", "/help")) or "도움" in t:
        notify.send("명령어\n/status 상태\n/top 비딩 후보\n/run 지금 수집\n(한글 '상태/후보/수집'도 인식)")
    elif t.startswith("/status") or "상태" in t:
        notify.send(_status_text())
    elif t.startswith("/top") or "후보" in t:
        _, cs = _candidates()
        if not cs:
            notify.send("지금 비딩 후보가 없습니다.")
        else:
            notify.send(f"🎯 비딩 후보 {len(cs)}건 — 상위 {min(5, len(cs))}")
            for r in cs[:5]:
                notify.send(notify.format_candidate(r), notify.build_buttons(r))
    elif t.startswith("/run") or "수집" in t:
        notify.send("🔄 수집 시작…")
        n, err = _collect()
        notify.send(f"✅ 수집 완료: {n}건" if err is None else f"⚠️ 수집 실패: {err}")
    else:
        notify.send("모르는 명령입니다. /help 참고")


def _register_commands():
    try:
        requests.post(f"{API}/setMyCommands", json={"commands": [
            {"command": "status", "description": "상태 확인"},
            {"command": "top", "description": "비딩 후보 보기"},
            {"command": "run", "description": "지금 수집"},
            {"command": "help", "description": "도움말"},
        ]}, timeout=10)
    except Exception:
        pass


def main():
    if not notify.enabled():
        print("텔레그램 미설정: .env 에 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 필요")
        return
    interval = config.COLLECT_INTERVAL_MINUTES * 60
    hb_hours = [int(x) for x in str(config.HEARTBEAT_HOURS).split(",") if x.strip().isdigit()]
    print(f"agent 시작 · 수집 {config.COLLECT_INTERVAL_MINUTES}분 간격 · 생존신호 {hb_hours}시")
    _register_commands()

    offset = None
    try:  # 시작 시 밀린 옛 명령은 무시
        j = requests.get(f"{API}/getUpdates", params={"timeout": 0}, timeout=15).json()
        if j.get("result"):
            offset = j["result"][-1]["update_id"] + 1
    except Exception:
        pass

    notify.send("🟢 PSA봇 시작됨. /status 로 상태 확인.")
    last_collect = 0.0
    sent_hb = set()

    while True:
        # 1) 명령 폴링 (long poll)
        try:
            j = requests.get(f"{API}/getUpdates",
                             params={"timeout": 20, "offset": offset}, timeout=30).json()
            for u in j.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                chat = str((msg.get("chat") or {}).get("id", ""))
                if chat != str(config.TELEGRAM_CHAT_ID):
                    continue  # 보안: 내 채팅만 응답
                _handle(msg.get("text", ""))
        except Exception:
            time.sleep(3)

        # 2) 예약 수집
        if time.time() - last_collect >= interval:
            last_collect = time.time()
            n, err = _collect()
            if err:
                notify.send(f"⚠️ 자동 수집 실패: {err}")

        # 3) 생존신호 (아침/점심/저녁)
        lt = dt.datetime.now()
        slot = (lt.date().isoformat(), lt.hour)
        if lt.hour in hb_hours and slot not in sent_hb:
            sent_hb.add(slot)
            notify.send(_status_text())


if __name__ == "__main__":
    main()
