"""
Gixen 웹 폼 자동화 — 공식 API(api.php)가 막혔을 때(예: [501] API DISABLED) 웹사이트에
직접 로그인해 스나이프 추가/조회/삭제. API와 동일한 결과.

인증: config.GIXEN_USERNAME / GIXEN_PASSWORD (= gixen.com 로그인).
흐름: 로그인 POST(home_1.php) → sessionid 발급 → home_2.php?sessionid=X 의 addsnipe 폼 제출.
"""
import re

import requests

import config

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
_ROOT = "https://www.gixen.com"
_BASE = _ROOT + "/main"

_sess = {"s": None, "sid": None}   # 로그인 세션 캐시(재사용)


class GixenWebError(Exception):
    pass


def enabled():
    return bool(config.GIXEN_USERNAME and config.GIXEN_PASSWORD)


def _digits(item_id):
    m = re.search(r"(\d{9,15})", str(item_id or ""))
    return m.group(1) if m else str(item_id or "").strip()


def _login():
    if not enabled():
        raise GixenWebError("GIXEN_USERNAME/PASSWORD 미설정 (.env 확인)")
    s = requests.Session()
    s.headers.update(_UA)
    s.get(_ROOT, timeout=30)   # 쿠키 수신
    r = s.post(_BASE + "/home_1.php",
               data={"username": config.GIXEN_USERNAME,
                     "password": config.GIXEN_PASSWORD,
                     "signin": "signin", "Submit": "Log in Now"},
               headers={"Referer": _ROOT + "/"}, timeout=30)
    m = re.search(r"sessionid=(\d+)", r.text)
    if not m:
        raise GixenWebError("로그인 실패 — 아이디/비밀번호 확인")
    sid = m.group(1)
    # 검증 GET(97KB) 생략 — sessionid 발급=로그인 성공. 세션 불량 시 add_snipe가 재로그인.
    _sess["s"], _sess["sid"] = s, sid
    return s, sid


def _ensure():
    if _sess["s"] and _sess["sid"]:
        return _sess["s"], _sess["sid"]
    return _login()


def _home(s, sid):
    return s.get("%s/home_2.php?sessionid=%s" % (_BASE, sid), timeout=30).text


def add_snipe(item_id, max_bid, bidoffset=None):
    """스나이프 1건 등록. 성공 dict, 실패 GixenWebError."""
    iid = _digits(item_id)
    bid = float(max_bid)
    if bid <= 0:
        raise GixenWebError("입찰가가 0 이하 — 금액 확인")
    off = str(int(bidoffset)) if bidoffset else "4"

    def _post(s, sid):
        return s.post("%s/home_2.php?sessionid=%s" % (_BASE, sid),
                      data={"newitemid": iid, "newmaxbid": "%.2f" % bid,
                            "username": config.GIXEN_USERNAME,
                            "newsnipegroup": "0", "newbidoffset": off,
                            "newbidoffsetmirror": off},
                      headers={"Referer": "%s/home_2.php?sessionid=%s" % (_BASE, sid)},
                      timeout=30)

    s, sid = _ensure()
    r = _post(s, sid)
    if "logout" not in r.text.lower():        # 세션 만료 → 1회 재로그인 후 재시도
        s, sid = _login()
        r = _post(s, sid)
    # 검증: 갱신된 목록에 해당 itemid가 등록돼 있으면 성공
    if re.search(r"edititemid_%s\b" % re.escape(iid), r.text):
        return {"ok": True, "item_id": iid, "max_bid": bid}
    if re.search(r"(error|invalid|ended|expired|cannot)", r.text, re.I):
        raise GixenWebError("Gixen 거부 — 종료된 매물이거나 잘못된 번호일 수 있음")
    raise GixenWebError("등록 확인 실패 (목록에 안 보임)")


def list_snipes():
    """등록된 스나이프 itemid 목록."""
    s, sid = _ensure()
    return re.findall(r"edititemid_(\d+)", _home(s, sid))


def delete_snipe(item_id):
    """itemid로 스나이프 삭제 (itemid→dbidid 매핑 후 delete_<dbidid> 제출)."""
    iid = _digits(item_id)
    s, sid = _ensure()
    html = _home(s, sid)
    pos = html.find("edititemid_%s" % iid)
    if pos < 0:
        raise GixenWebError("삭제 대상 없음 (목록에 %s 없음)" % iid)
    m = re.search(r"delete_(\d+)", html[pos:pos + 2000])
    if not m:
        raise GixenWebError("dbidid 못 찾음")
    dbidid = m.group(1)
    r = s.post("%s/home_2.php?sessionid=%s" % (_BASE, sid),
               data={"delete_%s" % dbidid: "Delete",
                     "username": config.GIXEN_USERNAME},
               headers={"Referer": "%s/home_2.php?sessionid=%s" % (_BASE, sid)},
               timeout=30)
    if re.search(r"edititemid_%s\b" % re.escape(iid), r.text):
        raise GixenWebError("삭제 확인 실패 (여전히 목록에 있음)")
    return True
