import re
import time
from urllib.parse import urlsplit

import requests

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
JS_HEAVY_MIN_SCRIPTS = 8
EMPTY_BODY_MAX_BYTES = 1500

ERROR_PAGE_MARKERS = (
    "404 not found",
    "this site can\u2019t be reached",
    "server error",
    "internal server error",
    "application error",
)


def smoke_test(url: str, timeout_sec: int = 20, user_agent: str = "HackathonJudge/1.0") -> dict:
    evidence: dict = {
        "submitted_url": url,
        "reachable": False,
        "flags": [],
        "signals": [],
    }

    if not url or not isinstance(url, str):
        evidence["flags"].append("url_missing")
        evidence["smoke_note"] = "No project URL submitted."
        return evidence

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parts = urlsplit(url)
    if not parts.netloc or "." not in parts.netloc.split(":")[0]:
        evidence["flags"].append("url_malformed")
        evidence["smoke_note"] = f"Malformed project URL: {url}"
        return evidence

    started = time.monotonic()
    try:
        resp = requests.get(
            url,
            timeout=timeout_sec,
            allow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml,*/*"},
        )
    except requests.exceptions.Timeout:
        evidence["flags"].append("url_timeout")
        evidence["smoke_note"] = f"Timed out after {timeout_sec}s: {url}"
        return evidence
    except requests.exceptions.SSLError:
        evidence["flags"].append("url_ssl_error")
        evidence["smoke_note"] = f"SSL error for {url}"
        return evidence
    except requests.exceptions.ConnectionError:
        evidence["flags"].append("url_unreachable")
        evidence["smoke_note"] = f"Connection failed for {url}"
        return evidence
    except requests.exceptions.RequestException as exc:
        evidence["flags"].append("url_error")
        evidence["smoke_note"] = f"Request error for {url}: {exc.__class__.__name__}"
        return evidence

    elapsed_ms = int((time.monotonic() - started) * 1000)
    body = resp.content[:200_000]
    text = body.decode("utf-8", errors="replace")
    lowered = text.lower()

    evidence.update(
        reachable=True,
        status_code=resp.status_code,
        final_url=resp.url,
        content_type=resp.headers.get("Content-Type", ""),
        elapsed_ms=elapsed_ms,
        body_bytes=len(resp.content),
    )

    if resp.status_code >= 400:
        evidence["flags"].append(f"http_{resp.status_code}")

    if resp.history:
        evidence["signals"].append(f"redirected_via_{len(resp.history)}_hops")

    content_type = evidence["content_type"].lower()
    if "text/html" in content_type or "<html" in lowered[:2000]:
        title_match = TITLE_RE.search(text)
        evidence["title"] = title_match.group(1).strip()[:200] if title_match else ""
        evidence["signals"].extend(
            [
                f"forms:{text.count('<form')}",
                f"inputs:{text.count('<input')}",
                f"buttons:{text.count('<button')}",
                f"links:{text.count('<a ')}",
                f"scripts:{text.count('<script')}",
            ]
        )
        if text.count("<script") >= JS_HEAVY_MIN_SCRIPTS and len(body) < EMPTY_BODY_MAX_BYTES * 10:
            evidence["signals"].append("possibly_spa_shell")
        if any(marker in lowered for marker in ERROR_PAGE_MARKERS) and resp.status_code < 400:
            evidence["flags"].append("soft_error_page")
    elif content_type.startswith("application/json"):
        evidence["signals"].append("raw_json_response")
        evidence["flags"].append("no_ui_at_root")
    else:
        evidence["signals"].append(f"content_type:{content_type.split(';')[0] or 'unknown'}")

    if elapsed_ms > 8000:
        evidence["flags"].append("slow_load")

    if not evidence["flags"]:
        evidence["smoke_note"] = (
            f"Loaded OK ({resp.status_code}, {elapsed_ms} ms"
            + (f", title: {evidence['title']}" if evidence.get("title") else "")
            + ")."
        )
    else:
        evidence["smoke_note"] = f"Loaded with issues: {', '.join(evidence['flags'])}."

    return evidence
