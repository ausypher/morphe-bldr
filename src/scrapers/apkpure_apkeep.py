#!/usr/bin/env python3
"""Validate and normalize an APKPure XAPK into a Morphe-compatible APKM.

The apkeep binary performs the version-pinned APKPure download. This helper
checks the base package/version/ABI and writes base.apk plus the original split
APKs into an APKM-style ZIP. utils.sh then verifies every split signature.
"""
from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath


def badging(aapt: str, apk: Path) -> str:
    result = subprocess.run(
        [aapt, "dump", "badging", str(apk)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(f"aapt could not read {apk.name}: {result.stderr.strip()}")
    return result.stdout


def main() -> int:
    if len(sys.argv) != 7:
        print(
            "usage: apkpure_apkeep.py PACKAGE VERSION ARCH INPUT.XAPK OUTPUT.APKM AAPT",
            file=sys.stderr,
        )
        return 2
    package, version, arch, xapk_name, output_name, aapt = sys.argv[1:]
    xapk = Path(xapk_name)
    output = Path(output_name)
    partial = output.with_name(output.name + ".part")

    try:
        with zipfile.ZipFile(xapk) as source:
            names = [
                name for name in source.namelist()
                if name.lower().endswith(".apk")
                and not name.startswith("__MACOSX/")
                and not name.endswith("/")
            ]
            if not names:
                raise RuntimeError("XAPK contains no APK splits")

            basenames = [PurePosixPath(name).name for name in names]
            if len(set(basenames)) != len(basenames):
                raise RuntimeError("XAPK contains duplicate APK filenames")

            extracted: dict[str, bytes] = {}
            for name in names:
                extracted[PurePosixPath(name).name] = source.read(name)

        base_name = next(
            (name for name in extracted if name.lower() in {f"{package}.apk", "base.apk"}),
            None,
        )
        if base_name is None:
            # Some XAPK producers use opaque base names. Identify the base by
            # package/version metadata rather than guessing from file order.
            for name, data in extracted.items():
                probe = output.parent / f".{output.name}.{name}"
                probe.write_bytes(data)
                try:
                    info = badging(aapt, probe)
                finally:
                    probe.unlink(missing_ok=True)
                if f"name='{package}'" in info and f"versionName='{version}'" in info:
                    base_name = name
                    break
        if base_name is None:
            raise RuntimeError(f"XAPK has no base APK for {package} {version}")

        probe = output.parent / f".{output.name}.base-check.apk"
        probe.write_bytes(extracted[base_name])
        try:
            info = badging(aapt, probe)
        finally:
            probe.unlink(missing_ok=True)

        if not re.search(rf"^package: name='{re.escape(package)}'\b", info, re.M):
            raise RuntimeError("base APK package name does not match the requested package")
        if f"versionName='{version}'" not in info:
            raise RuntimeError(
                f"base APK version mismatch (requested {version}); "
                "APKPure may have returned a different release"
            )

        native_line = next(
            (line for line in info.splitlines() if line.startswith("native-code:")),
            "",
        )
        arch_aliases = {
            "arm64-v8a": ("'arm64-v8a'",),
            "arm-v7a": ("'armeabi-v7a'", "'arm-v7a'"),
            "armeabi-v7a": ("'armeabi-v7a'", "'arm-v7a'"),
            "x86": ("'x86'",),
            "x86_64": ("'x86_64'",),
        }
        expected = arch_aliases.get(arch, (f"'{arch}'",))
        if not any(token in native_line for token in expected):
            raise RuntimeError(
                f"base APK does not match ABI {arch} "
                f"(aapt native-code: {native_line or '<none>'})"
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        partial.unlink(missing_ok=True)
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_STORED) as bundle:
            bundle.writestr("base.apk", extracted[base_name])
            for name, data in extracted.items():
                if name == base_name:
                    continue
                bundle.writestr(name, data)

        with zipfile.ZipFile(partial) as check:
            bad = check.testzip()
            if bad:
                raise RuntimeError(f"normalized APKM failed ZIP integrity check at {bad}")
            if "base.apk" not in check.namelist():
                raise RuntimeError("normalized APKM has no base.apk")
        partial.replace(output)
        print(
            f"APKPure XAPK normalized: {len(extracted)} APK splits, "
            f"{package} {version} ({arch})",
            file=sys.stderr,
        )
        return 0
    except Exception as exc:
        partial.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        print(f"APKPure/apkeep error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
