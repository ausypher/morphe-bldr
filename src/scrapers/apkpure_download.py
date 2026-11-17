#!/usr/bin/env python3
"""Download a version-pinned APK or XAPK from APKPure.

APKPure often distributes current Instagram/X builds as XAPK. Keep the APK
splits in an APKM-style archive so the existing Morphe merge/signature checks
can process them; never silently feed an XAPK container to the patcher.
"""
from __future__ import annotations

import html
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from curl_cffi import requests

SLUGS = {
    "com.twitter.android": "x-formerly-twitter",
    "com.instagram.android": "instagram-app",
}


def main() -> int:
    if len(sys.argv) != 5:
        print("Usage: apkpure-dl.py PACKAGE VERSION ARCH OUTPUT", file=sys.stderr)
        return 2

    package, version, arch, output = sys.argv[1:]
    slug = SLUGS.get(package)
    if not slug:
        print(f"APKPure: no app slug mapping for {package}", file=sys.stderr)
        return 1

    session = requests.Session(impersonate="chrome", timeout=120)
    page_url = f"https://apkpure.net/{slug}/{package}/download/{version}"
    destination = Path(output)
    temp_download = destination.with_name(f"tmp.{destination.name}.download")
    try:
        page = session.get(page_url, headers={"Referer": "https://apkpure.net/"})
        if page.status_code != 200:
            raise RuntimeError(f"download page returned HTTP {page.status_code}")

        match = re.search(r'id="download_link"[^>]*href="([^"]+)"', page.text)
        if not match:
            match = re.search(
                r'href="(https?://d[.]apkpure[.]net/b/(?:APK|XAPK)/[^"]+)"',
                page.text,
            )
        if not match:
            raise RuntimeError("no direct APK/XAPK download link found")

        download_url = html.unescape(match.group(1))
        response = session.get(
            download_url,
            headers={"Referer": page_url},
            stream=True,
        )
        if response.status_code != 200:
            raise RuntimeError(f"download returned HTTP {response.status_code}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with temp_download.open("wb") as stream:
            for chunk in response.iter_content(1 << 16):
                if chunk:
                    stream.write(chunk)
                    size += len(chunk)
        if size == 0:
            raise RuntimeError("downloaded file is empty")

        with zipfile.ZipFile(temp_download) as archive:
            names = archive.namelist()
            # A standalone APK is itself a ZIP with AndroidManifest.xml at root.
            if "AndroidManifest.xml" in names:
                destination.write_bytes(temp_download.read_bytes())
            else:
                apk_names = [
                    name for name in names
                    if name.lower().endswith(".apk")
                    and not name.startswith("__MACOSX/")
                ]
                if not apk_names:
                    raise RuntimeError("download archive contains no APK files")

                bundle_path = destination.with_suffix(".apkm")
                with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                    for name in apk_names:
                        # Retain split filenames; discard unrelated XAPK metadata.
                        bundle.writestr(Path(name).name, archive.read(name))
                with zipfile.ZipFile(bundle_path) as check:
                    if not any(n.lower().endswith(".apk") for n in check.namelist()):
                        raise RuntimeError("could not construct APKM from XAPK")
                print(
                    f"APKPure extracted {len(apk_names)} APK splits for {package} {version} ({arch})",
                    file=sys.stderr,
                )

        print(f"APKPure downloaded {package} {version}: {size} bytes", file=sys.stderr)
        return 0
    except Exception as exc:
        destination.unlink(missing_ok=True)
        destination.with_suffix(".apkm").unlink(missing_ok=True)
        print(f"APKPure error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        temp_download.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
