#!/usr/bin/env python3
"""Upload the saved WetMeat release files without replacing existing assets."""

from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent
REPOSITORY = "mwmwqxzk5h-del/WetMeat"
RELEASE_ID = 413292122
TAG = "v1.0.0"
STATE = ROOT / "publication-state.json"


def save(state):
    state["updated_utc"] = datetime.now(timezone.utc).isoformat()
    temporary = STATE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(STATE)


def api(endpoint):
    result = subprocess.run(
        ["gh", "api", endpoint], check=True, capture_output=True, text=True
    )
    return json.loads(result.stdout)


def check_asset(remote, local, expected_hash):
    if remote["size"] != local.stat().st_size or remote["state"] != "uploaded":
        raise RuntimeError(f"Incomplete or changed asset: {local.name}")
    server_digest = remote.get("digest")
    if server_digest and server_digest != "sha256:" + expected_hash:
        raise RuntimeError(f"Uploaded checksum mismatch: {local.name}")
    return {
        "id": remote["id"],
        "name": local.name,
        "bytes": remote["size"],
        "sha256": expected_hash,
        "server_digest_verified": bool(server_digest),
        "browser_download_url": remote["browser_download_url"],
    }


def main():
    with (ROOT / "upload.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        meta = json.loads((ROOT / "prepared.json").read_text())
        state = json.loads(STATE.read_text())
        release = api(f"repos/{REPOSITORY}/releases/{RELEASE_ID}")
        if release["tag_name"] != TAG or not release["draft"]:
            raise RuntimeError("Expected the known draft release; inspect before continuing.")
        if not state.get("source_pushed"):
            raise RuntimeError("Publish the corresponding source before uploading binaries.")

        expected = {item["name"]: item["sha256"] for item in meta["assets"]}
        expected["SHA256SUMS.txt"] = meta["checksum_manifest_sha256"]
        order = [
            "WetMeat-Source.zip", "WetMeat-Windows.zip", "WetMeat-Linux.zip",
            "WetMeat-Setup-English.pdf", "Windows-Setup.txt", "Linux-Setup.txt",
            "CREDITS.txt", "DISCORD-POST.txt", "RELEASE-VERIFICATION.json",
            "SHA256SUMS.txt", "WetMeat-Discord-Upload-Pack.zip",
        ]
        if set(order) != set(expected):
            raise RuntimeError("Asset list differs from the saved manifest.")
        state.update({
            "phase": "uploading_release_assets", "release_id": RELEASE_ID,
            "release_tag": TAG, "uploader_pid": os.getpid(),
            "release_published": False, "uploaded_assets": [],
        })
        save(state)
        environment = dict(os.environ, GOMAXPROCS="2")

        try:
            for name in order:
                release = api(f"repos/{REPOSITORY}/releases/{RELEASE_ID}")
                current = {item["name"]: item for item in release["assets"]}
                if set(current) - set(expected):
                    raise RuntimeError("Unexpected assets appeared; inspect rather than overwrite.")
                local = ROOT / "assets" / name
                state["current_upload"] = name
                save(state)
                if name not in current:
                    result = subprocess.run(
                        ["gh", "release", "upload", TAG, str(local), "--repo", REPOSITORY],
                        capture_output=True, text=True, env=environment,
                    )
                    (ROOT / ("upload-" + name + ".log")).write_text(result.stdout + result.stderr)
                    if result.returncode:
                        raise RuntimeError(f"Upload failed for {name}: {result.stderr.strip()}")
                    release = api(f"repos/{REPOSITORY}/releases/{RELEASE_ID}")
                    current = {item["name"]: item for item in release["assets"]}
                if name not in current:
                    raise RuntimeError(f"Uploaded asset absent from GitHub: {name}")
                checked = check_asset(current[name], local, expected[name])
                state["uploaded_assets"].append(checked)
                save(state)
                print(json.dumps({"uploaded": name, "bytes": checked["bytes"],
                                  "server_digest_verified": checked["server_digest_verified"]}), flush=True)

            release = api(f"repos/{REPOSITORY}/releases/{RELEASE_ID}")
            if {item["name"] for item in release["assets"]} != set(expected):
                raise RuntimeError("Final uploaded asset list does not match the manifest.")
            (ROOT / "release-with-assets.json").write_text(json.dumps(release, indent=2) + "\n")
            state.update({
                "phase": "assets_uploaded_ready_to_publish", "assets_uploaded": True,
                "asset_server_digests_complete": all(item["server_digest_verified"] for item in state["uploaded_assets"]),
                "current_upload": None,
            })
            save(state)
            print(json.dumps({"phase": state["phase"], "assets": len(state["uploaded_assets"]),
                              "all_server_digests_verified": state["asset_server_digests_complete"]}), flush=True)
        except Exception as error:
            state.update({"phase": "asset_upload_blocked", "error": str(error)})
            save(state)
            raise


if __name__ == "__main__":
    main()
