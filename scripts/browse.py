#!/usr/bin/env python3
"""Render a public HTTP(S) page safely with headless Chromium."""
import argparse
import ipaddress
import re
import socket
import subprocess
from html.parser import HTMLParser
from urllib.parse import urlparse


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL must be public HTTP(S) without embedded credentials")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("URL hostname did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("private, local, and reserved network targets are blocked")


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, _attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--text", "--text-only", action="store_true", dest="text_only")
    args = parser.parse_args()
    validate_public_url(args.url)
    result = subprocess.run(
        [
            "chromium", "--headless=new", "--no-sandbox", "--disable-gpu",
            "--virtual-time-budget=8000", "--dump-dom", args.url,
        ],
        capture_output=True,
        text=True,
        timeout=45,
        check=True,
    )
    if not args.text_only:
        print(result.stdout[:12000])
        return 0
    extractor = TextExtractor()
    extractor.feed(result.stdout)
    print(re.sub(r"\s+", " ", " ".join(extractor.parts))[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
