#!/usr/bin/env python3
"""Publish verified package folders as new Git tags for GitHub ZIP downloads."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent
REPO = ROOT / "repo"
ORIGINAL = ROOT.parent / "wetmeat-english-discord-20261014"
URL = "https://github.com/mwmwqxzk5h-del/WetMeat"
LIMIT = 100 * 1024 * 1024


def git(*args, data=None, env=None):
    result = subprocess.run(
        ["git", *args], cwd=REPO, input=data, capture_output=True,
        check=True, env=env,
    )
    return result.stdout.decode().strip()


def sha256(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main():
    packages = [
        ("windows", ORIGINAL / "staging" / "WetMeat-Windows"),
        ("linux", ORIGINAL / "staging" / "WetMeat-Linux"),
        ("source", ORIGINAL / "staging" / "WetMeat-Source"),
        ("discord", ORIGINAL / "discord-parts" / "WetMeat-Discord-Upload-Pack"),
    ]
    result = {"prepared_utc": datetime.now(timezone.utc).isoformat(), "packages": []}
    for key, folder in packages:
        tag = "v1.0.0-" + key
        index = ROOT / ("package-index-" + key)
        environment = dict(os.environ, GIT_INDEX_FILE=str(index))
        git("read-tree", "--empty", env=environment)
        entries = []
        files = []
        for path in sorted(folder.rglob("*")):
            if path.is_symlink():
                raise RuntimeError("Package symlink needs review: " + str(path))
            if not path.is_file():
                continue
            if path.stat().st_size >= LIMIT:
                raise RuntimeError("Package file exceeds GitHub's Git limit: " + path.name)
            name = (Path(folder.name) / path.relative_to(folder)).as_posix()
            blob = git("hash-object", "-w", "--no-filters", str(path))
            mode = "100755" if path.stat().st_mode & 0o111 else "100644"
            entries.append(f"{mode} {blob}\t{name}\0")
            files.append({"path": name, "bytes": path.stat().st_size, "sha256": sha256(path)})
        start = (
            "WetMeat 1.0 Stable\n\n"
            f"Open the {folder.name} folder inside this download.\n"
            "Read its README before running the installer or engine.\n"
            "On Windows, use Install-WetMeat.cmd or add the EXE in bin to a UCI interface.\n"
            "On Linux, run bash install.sh in the WetMeat-Linux folder.\n"
            "The source collection has its own README and build instructions.\n"
            "The optional Discord pack contains numbered parts and Join helpers.\n\n"
            "Windows and Linux executables need a compatible PC.\n"
            "Stockfish/GPL credits and the corresponding source are included or linked.\n"
            f"All downloads and instructions: {URL}/releases/tag/v1.0.0\n"
        ).encode()
        blob = git("hash-object", "-w", "--stdin", data=start)
        entries.append(f"100644 {blob}\tSTART-HERE.txt\0")
        files.append({"path": "START-HERE.txt", "bytes": len(start),
                      "sha256": hashlib.sha256(start).hexdigest()})
        git("update-index", "--add", "-z", "--index-info",
            data="".join(entries).encode(), env=environment)
        tree = git("write-tree", env=environment)
        exists = git("tag", "--list", tag)
        if exists:
            commit = git("rev-parse", tag + "^{}")
            if git("rev-parse", tag + "^{tree}") != tree:
                raise RuntimeError("Existing package tag differs; refusing to replace it: " + tag)
        else:
            commit = git("commit-tree", tree, "-m", "Package WetMeat 1.0 Stable: " + key)
            git("tag", "-a", tag, "-m", "WetMeat 1.0 Stable package: " + key, commit)
        result["packages"].append({
            "kind": key, "folder": folder.name, "tag": tag,
            "commit": commit, "tree": tree, "files": files,
            "download_url": f"{URL}/archive/refs/tags/{tag}.zip",
        })
        (ROOT / "git-downloads-prepared.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"package": key, "tag": tag, "commit": commit, "files": len(files)}), flush=True)
    if git("status", "--porcelain"):
        raise RuntimeError("The main source checkout changed during package preparation.")
    state_path = ROOT / "publication-state.json"
    state = json.loads(state_path.read_text())
    state.update({"phase": "git_download_tags_prepared", "updated_utc": datetime.now(timezone.utc).isoformat(),
                  "delivery_method": "GitHub-generated ZIPs of package-specific immutable tags",
                  "release_file_upload_endpoint_error": "uploads.github.com returned HTTP401 Bad credentials",
                  "engine_or_package_files_changed": False,
                  "package_tags": [{k: p[k] for k in ["kind", "tag", "commit", "download_url"]}
                                   for p in result["packages"]]})
    state_path.write_text(json.dumps(state, indent=2) + "\n")


if __name__ == "__main__":
    main()
