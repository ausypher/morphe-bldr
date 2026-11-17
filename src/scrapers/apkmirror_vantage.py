#!/usr/bin/env python3
"""Download the genuine split APKM for X/Twitter from APKMirror.

Adapted from pmaxhogan/vantage's scripts/apkmirror-dl.py. The downloader only
selects and fetches the APKMirror BUNDLE row; utils.sh verifies every split
against sig.txt before the archive is cached or passed to Morphe CLI.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from curl_cffi import requests
except Exception as exc:
    print(f"[apkmirror] curl_cffi unavailable: {exc}", file=sys.stderr)
    raise SystemExit(3)

BASE = "https://www.apkmirror.com"
SLUGS = {
    "com.twitter.android": "x-corp/x/x",
}


def log(*parts: object) -> None:
    print("[apkmirror]", *parts, file=sys.stderr)


def pick_bundle(html: str, arch: str) -> str | None:
    aliases = {
        "arm64-v8a": ("arm64-v8a",),
        "arm-v7a": ("armeabi-v7a", "arm-v7a"),
        "armeabi-v7a": ("armeabi-v7a", "arm-v7a"),
        "x86": ("x86",),
        "x86_64": ("x86_64",),
        "universal": ("universal", "noarch"),
        "all": (),
        "both": (),
    }.get(arch, (arch,))
    rows = re.findall(r'<div class="table-row[^"]*">.*?</div>\s*</div>', html, re.S)
    for row in rows:
        match = re.search(r'href="(/apk/[^"]*-android-apk-download/)"', row)
        if not match:
            continue
        plain = re.sub(r"<[^>]+>", " ", row)
        plain = re.sub(r"\s+", " ", plain)
        if not re.search(r"\bBUNDLE\b", plain, re.I):
            continue
        low = plain.lower()
        if aliases and not any(alias.lower() in low for alias in aliases):
            continue
        if arch == "arm64-v8a" and "arm64-v8a" not in low:
            continue
        return match.group(1)
    return None


def main() -> int:
    if len(sys.argv) != 5:
        log("usage: apkmirror_vantage.py PACKAGE VERSION ARCH OUTPUT_APKM")
        return 2
    package, version, arch, output = sys.argv[1:]
    slug = SLUGS.get(package)
    if not slug:
        log("no APKMirror mapping for", package)
        return 1

    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    partial.unlink(missing_ok=True)

    try:
        session = requests.Session(impersonate="chrome", timeout=120)
        release_url = f"{BASE}/apk/{slug}-{version.replace('.', '-')}-release/"
        log("release page", release_url)
        response = session.get(release_url, headers={"Referer": BASE + "/"})
        if response.status_code != 200:
            raise RuntimeError(f"release page HTTP {response.status_code}")

        variant_path = pick_bundle(response.text, arch)
        if not variant_path:
            raise RuntimeError(f"no BUNDLE variant matching arch={arch}")

        response = session.get(BASE + variant_path, headers={"Referer": release_url})
        if response.status_code != 200:
            raise RuntimeError(f"variant page HTTP {response.status_code}")
        match = re.search(r'href="(/apk/[^"]*/download/\?key=[^"]+)"', response.text)
        if not match:
            raise RuntimeError("no /download/?key= link on variant page")
        download_page = BASE + match.group(1).replace("&amp;", "&")

        response = session.get(download_page, headers={"Referer": BASE + variant_path})
        if response.status_code != 200:
            raise RuntimeError(f"download page HTTP {response.status_code}")
        match = re.search(r'href="(/wp-content/[^"]*download\.php\?[^"]+)"', response.text)
        if not match:
            raise RuntimeError("no download.php link on download page")
        file_url = BASE + match.group(1).replace("&amp;", "&")

        response = session.get(file_url, headers={"Referer": download_page}, stream=True)
        if response.status_code != 200:
            raise RuntimeError(f"APKMirror file HTTP {response.status_code}")
        size = 0
        with partial.open("wb") as stream:
            for chunk in response.iter_content(1 << 16):
                if chunk:
                    stream.write(chunk)
                    size += len(chunk)
        if size == 0:
            raise RuntimeError("APKMirror returned an empty file")
        partial.replace(destination)
        log(f"downloaded {size} bytes -> {destination}")
        return 0
    except Exception as exc:
        partial.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        log(f"download failed: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
