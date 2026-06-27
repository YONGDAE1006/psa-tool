"""
슬랩 라벨 OCR — 의심 카드의 eBay 실물사진(PSA 슬랩)을 비전 모델로 읽어
카드번호(#NNN)·등급(GEM MT 10)·인증번호를 추출. 셀러가 제목/aspects를 잘못
입력해 매칭이 틀어진 카드를 '슬랩의 진짜 정보'로 보정하는 용도.

- config.VISION_API_KEY 없으면 비활성(enabled()=False).
- 기본 provider=anthropic (Claude Haiku 비전, 저렴). 실패 시 빈 dict.
"""
import base64
import json
import re

import requests

import config


class OCRError(Exception):
    pass


def enabled():
    return bool(config.VISION_API_KEY)


def _upscale(url):
    """eBay 썸네일 → 고해상도 (s-l225 → s-l1600). OCR 정확도용."""
    return re.sub(r"s-l\d+", "s-l1600", url) if url else url


_PROMPT = (
    "This is a photo of a PSA-graded Pokemon card slab. Read the red PSA label at the top. "
    "Return ONLY one compact JSON object, no prose, with keys: "
    '"card_number" (the # number shown on the label such as "088", "TG29", "GG36" — just that '
    'token, NOT the /total), "grade" (the numeric grade, e.g. "10"), '
    '"cert" (the long certification serial number, digits only), '
    '"name" (the card/Pokemon name on the label), '
    '"set" (the set/series name on the label, e.g. "Ascended Heroes", "Mega Evolution", '
    '"Crown Zenith"). Use null for any field you cannot read.'
)


def _download_b64(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    mime = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    if mime not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        mime = "image/jpeg"
    return base64.b64encode(r.content).decode(), mime


def _anthropic(b64, mime):
    body = {
        "model": config.VISION_MODEL,
        "max_tokens": 200,
        "messages": [{"role": "user", "content": [
            {"type": "image",
             "source": {"type": "base64", "media_type": mime, "data": b64}},
            {"type": "text", "text": _PROMPT},
        ]}],
    }
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": config.VISION_API_KEY,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json=body, timeout=60,
    )
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", [])
                   if b.get("type") == "text")


def read_slab(image_url):
    """슬랩 사진 → {card_number, grade, cert, name}. 실패 시 {}."""
    if not enabled() or not image_url:
        return {}
    try:
        b64, mime = _download_b64(_upscale(image_url))
        if config.VISION_PROVIDER == "anthropic":
            txt = _anthropic(b64, mime)
        else:
            return {}
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return {}
        d = json.loads(m.group(0))
        out = {}
        for k in ("card_number", "grade", "cert", "name", "set"):
            v = d.get(k)
            out[k] = str(v).strip() if v not in (None, "", "null", "N/A") else None
        return out
    except Exception:
        return {}
