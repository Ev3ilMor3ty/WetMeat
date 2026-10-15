#!/usr/bin/env python3
"""Download the public packages and compare every file with the saved release."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "public-download-verification"


def verify(package):
    key = package["kind"]
    destination = OUTPUT / (key + ".zip")
    temporary = destination.with_suffix(".zip.downloading")
    request = urllib.request.Request(package["download_url"], headers={
        "User-Agent": "WetMeat-release-verification",
        "Accept": "application/zip",
    })
    outer_digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as stream:
        status = response.status
        if status != 200:
            raise RuntimeError(f"Public download returned {status}: {key}")
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            stream.write(chunk)
            outer_digest.update(chunk)
    temporary.replace(destination)

    expected = {item["path"]: item for item in package["files"]}
    actual = {}
    with zipfile.ZipFile(destination) as archive:
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            parts = PurePosixPath(entry.filename).parts
            if len(parts) < 2 or ".." in parts or entry.filename.startswith("/"):
                raise RuntimeError("Unexpected archive path: " + entry.filename)
            relative = "/".join(parts[1:])
            if relative in actual or relative not in expected:
                raise RuntimeError("Unexpected or duplicate file: " + relative)
            record = expected[relative]
            if entry.file_size != record["bytes"]:
                raise RuntimeError("Changed file size: " + relative)
            digest = hashlib.sha256()
            with archive.open(entry) as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != record["sha256"]:
                raise RuntimeError("Changed package file: " + relative)
            actual[relative] = True
    if set(actual) != set(expected):
        raise RuntimeError("Missing package files: " + key)
    result = {
        "kind": key, "url": package["download_url"], "tag": package["tag"],
        "commit": package["commit"], "http_status": status,
        "request_included_authorization_header": False,
        "download_bytes": destination.stat().st_size,
        "observed_outer_archive_sha256": outer_digest.hexdigest(),
        "files_verified": len(actual), "all_file_sizes_sha256_and_crc_passed": True,
        "downloaded_archive": str(destination),
    }
    (OUTPUT / (key + ".json")).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"verified": key, "http_status": status,
                      "bytes": result["download_bytes"], "files": len(actual)}), flush=True)
    return result


def main():
    OUTPUT.mkdir(exist_ok=True)
    packages = json.loads((ROOT / "git-downloads-prepared.json").read_text())["packages"]
    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(verify, package) for package in packages]
        for task in as_completed(tasks):
            results.append(task.result())
    report = {
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "status": "passed", "public_package_downloads": sorted(results, key=lambda item: item["kind"]),
        "files_verified": sum(item["files_verified"] for item in results),
        "archive_hash_note": "These are observed GitHub-generated ZIP hashes, not the old saved ZIP hashes. Verify the unchanged inner package files; GitHub may change archive compression over time.",
        "engine_or_source_changes": False,
        "native_windows_installer_tested": False,
        "new_strength_claim": False,
    }
    (ROOT / "public-download-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": "passed", "packages": len(results),
                      "files_verified": report["files_verified"]}), flush=True)


if __name__ == "__main__":
    main()
