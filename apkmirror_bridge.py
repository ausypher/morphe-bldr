#!/usr/bin/env python3
"""Adapter for the Morphe bldr APKMirror scraper."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.core.network import NetworkManager
from src.scrapers.apkmirror import APKMirrorScraper


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: apkmirror_bridge.py metadata URL | download URL VERSION OUTPUT ARCH DPI [VERSION_CODE]", file=sys.stderr)
        return 2

    action, url = sys.argv[1], sys.argv[2]
    try:
        with NetworkManager() as net:
            scraper = APKMirrorScraper(net)
            if action == "metadata":
                metadata = scraper.cached_metadata(url)
                print(json.dumps({
                    "pkg_name": metadata.pkg_name,
                    "versions": metadata.versions,
                    "category": scraper._category,
                }))
                return 0

            if action == "download":
                if len(sys.argv) not in (7, 8):
                    print("download requires URL VERSION OUTPUT ARCH DPI [VERSION_CODE]", file=sys.stderr)
                    return 2
                _, _, _, version, output, arch, dpi, *rest = sys.argv
                version_code = rest[0] if rest and rest[0] else None
                if arch == "arm-v7a":
                    arch = "armeabi-v7a"
                result = scraper.download(
                    url, version, Path(output), arch, dpi, version_code
                )
                print(json.dumps({"path": str(result.path), "is_bundle": result.is_bundle}))
                return 0

            print(f"Unknown action: {action}", file=sys.stderr)
            return 2
    except Exception as exc:
        print(f"APKMirror bridge error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
