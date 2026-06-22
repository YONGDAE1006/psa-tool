"""
Gixen 공식 API 클라이언트 — 스나이프 자동 등록/조회/삭제.

- 엔드포인트: https://www.gixen.com/api.php  (GET)
- 인증: username / password = Gixen 로그인 정보(.env의 GIXEN_USERNAME / GIXEN_PASSWORD).
        (Gixen 무료 계정도 메인 서버 스나이프 추가 가능. 미러 서버는 유료 구독 필요.)
- 응답: 성공  'OK {itemid} ADDED'  /  삭제 'OK {itemid} DELETED'
        실패  'ERROR (코드): 메시지'
"""
import re

import requests

import config

API_URL = "https://www.gixen.com/api.php"


class GixenError(Exception):
    pass


def enabled():
    """자동등록 사용 가능 여부(자격증명 설정됐는지)."""
    return bool(config.GIXEN_USERNAME and config.GIXEN_PASSWORD)


def _digits(item_id):
    """'v1|267696243434|0' 같은 내부 id → eBay 숫자번호만 추출."""
    m = re.search(r"(\d{9,15})", str(item_id or ""))
    return m.group(1) if m else str(item_id or "").strip()


def _call(extra):
    if not enabled():
        raise GixenError("GIXEN_USERNAME/PASSWORD 미설정 (.env 확인)")
    params = {
        "username": config.GIXEN_USERNAME,
        "password": config.GIXEN_PASSWORD,
        "notags": 1,
    }
    params.update(extra)
    r = requests.get(API_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.text.strip()


def add_snipe(item_id, max_bid, bidoffset=None):
    """스나이프 1건 등록. 성공 시 dict 반환, 실패 시 GixenError."""
    iid = _digits(item_id)
    bid = float(max_bid)
    if bid <= 0:
        raise GixenError("입찰가가 0 이하 — 금액 확인")
    extra = {"itemid": iid, "maxbid": "{:.2f}".format(bid)}
    if bidoffset:
        extra["bidoffset"] = int(bidoffset)
    txt = _call(extra)
    for line in txt.splitlines():
        line = line.strip()
        if re.match(r"^OK {} ADDED$".format(re.escape(iid)), line):
            return {"ok": True, "item_id": iid, "max_bid": bid, "raw": txt}
        m = re.match(r"^ERROR \((\d+)\): (.*)$", line)
        if m:
            raise GixenError("[{}] {}".format(m.group(1), m.group(2)))
    raise GixenError("예상치 못한 응답: " + txt[:200])


def list_snipes():
    """메인 서버에 등록된 스나이프 목록."""
    txt = _call({"listsnipesmain": 1})
    out = []
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("OK") or line.startswith("ERROR"):
            continue
        f = line.split("|")
        # break|itemid|endtime|maxbid|status|message|title|snipegroup|quantity|bidoffset
        if len(f) >= 6:
            out.append({
                "item_id": f[1], "endtime": f[2], "maxbid": f[3],
                "status": f[4], "message": f[5],
                "title": f[6] if len(f) > 6 else "",
            })
    return out


def delete_snipe(item_id):
    """스나이프 1건 삭제."""
    iid = _digits(item_id)
    txt = _call({"ditemid": iid})
    for line in txt.splitlines():
        line = line.strip()
        if re.match(r"^OK {} DELETED$".format(re.escape(iid)), line):
            return True
        m = re.match(r"^ERROR \((\d+)\): (.*)$", line)
        if m:
            raise GixenError("[{}] {}".format(m.group(1), m.group(2)))
    raise GixenError("예상치 못한 응답: " + txt[:200])
