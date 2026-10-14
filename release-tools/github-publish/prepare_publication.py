#!/usr/bin/env python3
"""Prepare the public WetMeat repository without changing the saved release."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil


ROOT = Path(__file__).resolve().parent
PREPARED = ROOT.parent / "wetmeat-english-discord-20261014"
REPO = ROOT / "repo"
ASSETS = ROOT / "assets"
OWNER = "mwmwqxzk5h-del"
NAME = "WetMeat"
TAG = "v1.0.0"
URL = f"https://github.com/{OWNER}/{NAME}"
RELEASE = f"{URL}/releases/tag/{TAG}"
DOWNLOAD = f"{URL}/releases/download/{TAG}"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    if REPO.exists() or ASSETS.exists():
        raise SystemExit("Prepared folders already exist. Inspect them before continuing.")

    distribution = json.loads((PREPARED / "distribution.json").read_text())
    for package in distribution["packages"]:
        if digest(Path(package["file"])) != package["sha256"]:
            raise SystemExit(f"Saved archive changed: {Path(package['file']).name}")

    source = PREPARED / "staging" / "WetMeat-Source"
    shutil.copytree(source, REPO)
    (REPO / "docs").mkdir()
    ASSETS.mkdir()
    shutil.copy2(REPO / "stable" / "Copying.txt", REPO / "LICENSE")

    docs = {
        "README-WINDOWS.txt": "Windows-Setup.txt",
        "README-LINUX.txt": "Linux-Setup.txt",
        "SOURCE-BUILD.txt": "Building-from-source.txt",
        "SHARING-ON-DISCORD.txt": "Sharing-on-Discord.txt",
    }
    for original, renamed in docs.items():
        shutil.copy2(PREPARED / "docs" / original, REPO / "docs" / renamed)
    shutil.copy2(PREPARED / "dist" / "WetMeat-Setup-English.pdf", REPO / "docs" / "WetMeat-Setup-English.pdf")
    shutil.copy2(PREPARED / "verification.json", REPO / "docs" / "RELEASE-VERIFICATION.json")
    publication_tools = REPO / "release-tools" / "github-publish"
    publication_tools.mkdir(parents=True)
    shutil.copy2(Path(__file__), publication_tools / "prepare_publication.py")

    write(REPO / "README.md", f"""# WetMeat 1.0 Stable

WetMeat is a Stockfish-based chess-engine project for Windows and Linux.
This release packages the unchanged stable engine with English setup instructions,
optional installation helpers and the complete project source, including its actual
neural-network file.

## Downloads

**[Open the release and download the files here]({RELEASE}).**

| File | Download | Use |
| --- | --- | --- |
| Windows, about 80 MB | [WetMeat-Windows.zip]({DOWNLOAD}/WetMeat-Windows.zip) | Windows 10/11, x64 AVX2 |
| Linux, about 161 MB | [WetMeat-Linux.zip]({DOWNLOAD}/WetMeat-Linux.zip) | x64 AVX2 and AVX-512 builds |
| Complete project source, about 81 MB | [WetMeat-Source.zip]({DOWNLOAD}/WetMeat-Source.zip) | Code, actual model, licences and research archive |
| English setup guide | [WetMeat-Setup-English.pdf]({DOWNLOAD}/WetMeat-Setup-English.pdf) | Windows and Linux instructions |
| Download checksums | [SHA256SUMS.txt]({DOWNLOAD}/SHA256SUMS.txt) | Verify the release files |

Use the Windows or Linux package to play. GitHub's green **Code** button downloads
source code; it is not the ready-to-run engine package.

## Windows setup

1. Download `WetMeat-Windows.zip` and choose **Extract All**.
2. Open the extracted folder. You can use `bin/wetmeat-windows-avx2.exe` directly,
   or run `Install-WetMeat.cmd` to copy it to your user folder.
3. Install a chess interface such as [Cute Chess](https://github.com/cutechess/cutechess/releases)
   or Arena. The graphical interface is a separate download.
4. Add the EXE as a **UCI engine** in that interface.

The default installer destination is `%LOCALAPPDATA%\\WetMeat\\1.0-stable`.
No administrator account is needed. The package needs an x64 CPU with AVX2,
BMI1, POPCNT and SSE4.1. It is not a Windows-on-ARM executable.

[Full Windows instructions](docs/Windows-Setup.txt)

## Linux setup

Extract `WetMeat-Linux.zip`, open its `WetMeat-Linux` folder in a terminal, then run:

```bash
bash install.sh
```

The script verifies the files and installs to `~/.local/share/wetmeat/1.0-stable`.
Add the printed engine path to a UCI chess interface. The AVX2 build is the usual
choice; only select AVX-512 on hardware that supports it.

[Full Linux instructions](docs/Linux-Setup.txt)

## Engine settings

Use Skill Level **20**, `UCI_LimitStrength` **false** and MultiPV **1** for games.
Start with **2 threads** and **256 MB hash**, adjusting for the computer's resources.
Leave pondering off for a simple setup. The neural network is embedded in the
executables, so you do not need another model download to play.

These packages run on a PC, not directly on an iPhone or iPad. On a phone, download
them through the release page and transfer the files to the PC before installing.

## Source and credits

The stable engine uses Stockfish's search, evaluation and official NNUE weights.
Its upstream source is commit `49ea5ded38315cff8e67f4a677a9e7811612fbf6`
from 30 September 2026. WetMeat's changes include UCI stop/ponder handling,
a Windows CPU-topology fallback, release builds and project tooling.

The name change does not make the Stockfish core an independent implementation.
See [CREDITS.txt](CREDITS.txt), [Stockfish's AUTHORS](stable/AUTHORS) and
[the GNU GPL](stable/Copying.txt). The stable engine is GPL v3 or later;
the archived prototypes retain their own licence files.

The corresponding source is available both in this repository and as the
`WetMeat-Source.zip` release asset. It includes the actual
`stable/src/nn-252f33942263.nnue` model, not a placeholder.
Keep that source available alongside any copies of the executables you distribute.

[Source directory guide](README.txt) · [Build instructions](docs/Building-from-source.txt)

## Tests and research

The archive checks, split-file reconstruction and Linux installer checks passed.
The installed Linux engine returned a legal move from an unrelated directory.
Windows engine checks used Wine; the new CMD installation helpers have not been
executed on native Windows. [Packaging verification](docs/RELEASE-VERIFICATION.json)
records those limits.

The recorded 100 ms training study reached 420 completed games: **55 wins,
318 draws and 47 losses** against full-strength Stockfish 19 with matched settings.
The first 100 fully audited games were **14 wins, 72 draws and 14 losses**.
The planned 1,000-game study and the full 420-game audits remain incomplete.
The audited subset does not establish a lower mistake rate or general superiority.
See [TEST-NOTES.txt](TEST-NOTES.txt) for identities, coverage and finite-judge limits.

Research versions are archived separately. None replaces the stable release,
and no higher Elo, Stockfish superiority or perfect-play claim is made here.

## Sharing on Discord

Share **{RELEASE}** so people can choose their operating system.
The ready-to-copy [English Discord post](docs/DISCORD-POST.txt) includes the downloads,
setup steps and credits. GitHub hosts the binaries and their corresponding source;
there is no need to re-upload split files to Discord.

An optional `WetMeat-Discord-Upload-Pack.zip` release asset also contains parts of
at most 8 MiB and reassembly helpers, for servers that prefer their own attachments.
"""
    )

    post = f"""**WetMeat 1.0 Stable — Windows & Linux**

I've put together a release of WetMeat, my Stockfish-based chess-engine project.
It comes with English setup instructions, optional installers and the full source.

**Download:** {RELEASE}

• Windows: {DOWNLOAD}/WetMeat-Windows.zip
• Linux: {DOWNLOAD}/WetMeat-Linux.zip
• Complete source and the actual model: {DOWNLOAD}/WetMeat-Source.zip
• English setup guide: {DOWNLOAD}/WetMeat-Setup-English.pdf

Extract the Windows or Linux ZIP on your PC. Follow the README, then add the
engine to Cute Chess or Arena as a UCI engine. You can run the optional installer
to copy it to your user folder. Use Skill Level 20, UCI_LimitStrength off and
MultiPV 1. The network is embedded; there is no extra model download for playing.

Cute Chess downloads: https://github.com/cutechess/cutechess/releases
These are x64 PC builds and do not run directly on an iPhone or iPad.

WetMeat Stable uses Stockfish's search, evaluation and official NNUE weights.
Stockfish credits, GPL notices and the corresponding source are included.
The research versions are separate; this release makes no claim of being
stronger than Stockfish.
"""
    write(REPO / "docs" / "DISCORD-POST.txt", post)

    write(REPO / ".gitignore", """# Local build output and editor files
*.o
*.d
*.gcda
*.gcno
__pycache__/
.venv/
.DS_Store
build/
stable/bin/
stable/src/wetmeat
stable/src/wetmeat.exe
"""
    )

    for package in distribution["packages"]:
        shutil.copy2(package["file"], ASSETS / Path(package["file"]).name)
    for filename in ["WetMeat-Setup-English.pdf", "CREDITS.txt"]:
        shutil.copy2(PREPARED / "dist" / filename, ASSETS / filename)
    shutil.copy2(REPO / "docs" / "DISCORD-POST.txt", ASSETS / "DISCORD-POST.txt")
    for filename in ["Windows-Setup.txt", "Linux-Setup.txt", "RELEASE-VERIFICATION.json"]:
        shutil.copy2(REPO / "docs" / filename, ASSETS / filename)

    asset_records = [
        {"name": p.name, "bytes": p.stat().st_size, "sha256": digest(p)}
        for p in sorted(ASSETS.iterdir())
    ]
    sums = "".join(f"{item['sha256']}  {item['name']}\n" for item in asset_records)
    write(ASSETS / "SHA256SUMS.txt", sums)
    write(REPO / "docs" / "RELEASE-SHA256SUMS.txt", sums)

    forbidden = {".env", ".netrc", "credentials.json", "id_rsa", "id_ed25519"}
    patterns = [
        re.compile(rb"gh[pousr]_[A-Za-z0-9]{24,}"),
        re.compile(rb"github_pat_[A-Za-z0-9_]{40,}"),
        re.compile(rb"AKIA[A-Z0-9]{16}"),
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(rb"sk-(?:proj|svcacct)-[A-Za-z0-9_-]{40,}"),
    ]
    scanned = 0
    failures = []
    for path in REPO.rglob("*"):
        if path.is_symlink():
            failures.append(str(path.relative_to(REPO)))
        if not path.is_file():
            continue
        if path.name in forbidden:
            failures.append(str(path.relative_to(REPO)))
        if path.suffix == ".nnue" or path.suffix == ".pdf":
            continue
        data = path.read_bytes()
        scanned += 1
        if any(pattern.search(data) for pattern in patterns):
            failures.append(str(path.relative_to(REPO)))
    if failures:
        raise SystemExit("Review these files before publishing: " + ", ".join(failures))

    changed = [
        str(path.relative_to(source)) for path in source.rglob("*")
        if path.is_file() and digest(path) != digest(REPO / path.relative_to(source))
    ]
    if changed:
        raise SystemExit("Source copy changed: " + ", ".join(changed))

    write(ROOT / "release-notes.md", f"""English Windows and Linux distribution of **WetMeat 1.0 Stable**.

The engine binaries, corresponding stable source and official NNUE model are
unchanged from the verified local release. This publication adds GitHub downloads;
it is not a new engine-strength result.

## Downloads

* **Windows:** `WetMeat-Windows.zip` — extract and follow `README.txt`.
* **Linux:** `WetMeat-Linux.zip` — extract and run `bash install.sh`.
* **Complete source and actual model:** `WetMeat-Source.zip`.
* **English guide:** `WetMeat-Setup-English.pdf`.
* **Discord:** share this release link or copy `DISCORD-POST.txt`.
* **Optional split attachments:** extract `WetMeat-Discord-Upload-Pack.zip` and
  upload all parts, README and Join helpers for a package; include the Source set.

Use a UCI interface such as [Cute Chess](https://github.com/cutechess/cutechess/releases)
or Arena. The graphical interface is downloaded separately. Windows and the default
Linux build need x64 AVX2; these executables do not run directly on iOS or ARM.
No external model download is needed to play.

## Source, licence and checks

WetMeat Stable is Stockfish-derived and uses its official neural-network weights.
GPL v3-or-later and Stockfish author notices are included. Corresponding code and
the actual model are offered in this repository and the Source release asset.
Archived independent prototypes retain their separate licence files and identities.

Archive checks, all three real split-file reconstructions and the Linux installation
checks passed. The stable Windows executable had protocol/functional checks under
Wine; the new CMD installer is not natively Windows-tested. See
`RELEASE-VERIFICATION.json` and `SHA256SUMS.txt`.

The saved 420-game training score at 100 ms/move was 55 wins, 318 draws, 47 losses;
the first 100 fully audited games were 14 wins, 72 draws, 14 losses. The planned
1,000-game study and full 420-game audits are incomplete. This exploratory sample
does not establish superiority, a lower error rate, calibrated Elo or perfect play.

[Repository and setup instructions]({URL})
"""
    )
    record = {
        "owner": OWNER, "repository": NAME, "tag": TAG,
        "repository_url": URL, "release_url": RELEASE,
        "source_files_unchanged": True,
        "source_collection_files": distribution["source_file_count"],
        "source_scan_text_files": scanned, "source_scan_findings": [],
        "assets": asset_records,
        "checksum_manifest_sha256": digest(ASSETS / "SHA256SUMS.txt"),
        "prepared_only": True,
    }
    write(ROOT / "prepared.json", json.dumps(record, indent=2))
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
