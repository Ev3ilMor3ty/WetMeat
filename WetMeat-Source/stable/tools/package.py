"""Package source, networks and verified executables. SPDX-License-Identifier: GPL-3.0-or-later."""

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    files = {root / item for item in subprocess.check_output(
        ["git", "ls-files"], cwd=root, text=True).splitlines()}
    files.update([root / "UPSTREAM_README.md", root / "requirements-test.txt"])
    files.update((root / "tools").rglob("*.py"))
    files.update((root / "tools").rglob("*.sh"))
    files.update((root / "tools").rglob("*.html"))
    files.update((root / "docs").glob("*"))
    files.update((root / "src").glob("*.nnue"))
    excluded = {"differential-smoke.json", "relink-static.log", "build-windows.log"}
    files = {file for file in files if file.is_file() and file.name not in excluded}
    manifest = json.loads((root / "docs/build-manifest.json").read_text())
    platforms = {
        "windows": ["wetmeat-windows-avx2.exe"],
        "linux": ["wetmeat-linux-avx512", "wetmeat-linux-avx2"],
    }
    reports = []
    for platform, binaries in platforms.items():
        output = root.parent / f"wetmeat-{platform}.zip"
        contents = files | {root / "bin" / name for name in binaries}
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for file in sorted(contents):
                archive.write(file, "wetmeat/" + file.relative_to(root).as_posix())
        with zipfile.ZipFile(output) as archive:
            for name in binaries:
                with archive.open("wetmeat/bin/" + name) as binary:
                    digest = hashlib.file_digest(binary, "sha256").hexdigest()
                if digest != manifest["binaries"][name]["sha256"]:
                    raise AssertionError("Packaged executable changed")
            with archive.open("wetmeat/src/nn-252f33942263.nnue") as network:
                if hashlib.file_digest(network, "sha256").hexdigest() != manifest["network"]["sha256"]:
                    raise AssertionError("Packaged network changed")
            for required in ["Copying.txt", "AUTHORS", "src/search.cpp", "src/numa.h", "src/Makefile", "docs/TESTS.md"]:
                if "wetmeat/" + required not in archive.namelist():
                    raise AssertionError("Missing corresponding source or license: " + required)
        reports.append({"file": output.name, "bytes": output.stat().st_size,
                        "files": len(contents), "sha256": hashlib.file_digest(output.open("rb"), "sha256").hexdigest(),
                        "verified": "executables, network, source and license"})
    report_path = root.parent / "wetmeat-packages.json"
    report_path.write_text(json.dumps(reports, indent=2) + "\n")
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
