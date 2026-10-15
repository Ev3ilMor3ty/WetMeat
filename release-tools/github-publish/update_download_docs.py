#!/usr/bin/env python3
"""Point the public documentation at the verified GitHub package tags."""

from pathlib import Path
import json
import shutil


ROOT = Path(__file__).resolve().parent
REPO = ROOT / "repo"
URL = "https://github.com/mwmwqxzk5h-del/WetMeat"
RELEASE = URL + "/releases/tag/v1.0.0"
RAW = "https://raw.githubusercontent.com/mwmwqxzk5h-del/WetMeat/main"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n")


def main():
    meta = json.loads((ROOT / "git-downloads-prepared.json").read_text())
    packages = {p["kind"]: p for p in meta["packages"]}
    links = {key: p["download_url"] for key, p in packages.items()}
    guide = RAW + "/docs/WetMeat-Setup-English.pdf"
    write(REPO / "README.md", f'''# WetMeat 1.0 Stable

WetMeat is a Stockfish-based chess-engine project for Windows and Linux.
The stable engine comes with English instructions, optional installers and its
complete corresponding source, including the actual neural-network file.

## Downloads

**[Open the download release]({RELEASE})** or choose a package below.

| Package | Download | Requirements |
| --- | --- | --- |
| Windows, about 80 MB | [Windows ZIP]({links['windows']}) | Windows 10/11, x64 AVX2 |
| Linux, about 161 MB | [Linux ZIP]({links['linux']}) | x64 AVX2; optional AVX-512 build included |
| Complete source, about 81 MB | [Source ZIP]({links['source']}) | Code, actual model, licences and research archive |
| English setup guide | [PDF]({guide}) | Readable on a phone or PC |
| Optional Discord attachments, about 323 MB | [Discord upload pack]({links['discord']}) | Numbered parts and reassembly helpers |

GitHub adds a versioned outer folder to each ZIP. After extracting it, open the
inner **WetMeat-Windows**, **WetMeat-Linux** or **WetMeat-Source** folder.
`START-HERE.txt` also explains where to go. You do not need to rename the ZIP.
Use the Windows or Linux package to play. The green **Code** button on this
repository downloads source code rather than a ready-to-run engine package.

## Windows setup

1. Download the Windows ZIP and choose **Extract All**.
2. Open its outer folder, then **WetMeat-Windows**.
3. Use `bin/wetmeat-windows-avx2.exe` directly, or run `Install-WetMeat.cmd`
   to copy it into your user folder.
4. Install a UCI chess interface such as
   [Cute Chess](https://github.com/cutechess/cutechess/releases) or Arena.
5. Add the EXE as a **UCI engine** in that interface.

The optional installer uses `%LOCALAPPDATA%\\WetMeat\\1.0-stable` and needs no
administrator account. This build needs AVX2, BMI1, POPCNT and SSE4.1 on a 64-bit
Windows PC. It is not a Windows-on-ARM executable.

[Full Windows instructions](docs/Windows-Setup.txt)

## Linux setup

Extract the Linux ZIP. Inside its outer folder, open **WetMeat-Linux** in a
terminal and run:

```bash
bash install.sh
```

The script verifies the package and installs to
`~/.local/share/wetmeat/1.0-stable`. Add the printed engine path to a UCI interface.
The AVX2 build is the usual choice. Only select AVX-512 on compatible hardware.

[Full Linux instructions](docs/Linux-Setup.txt)

## Engine settings

Use **Skill Level 20**, **UCI_LimitStrength false** and **MultiPV 1** for games.
Start with **2 threads** and **256 MB hash**, adjusting for your computer's
resources. Pondering can stay off. The model is embedded in the executables;
no extra model download is needed to play. The graphical chess interface is
downloaded separately.

These are PC programs. On an iPhone or iPad, save the ZIP and transfer it to
your PC before installing. The English PDF can be read on your phone.

## Source and credits

WetMeat Stable uses Stockfish's search, evaluation and official NNUE weights.
Its upstream source is commit `49ea5ded38315cff8e67f4a677a9e7811612fbf6`,
30 September 2026. WetMeat's changes include UCI stop/ponder handling,
a Windows CPU-topology fallback, release builds and project tools.
The Stockfish core is not an independent WetMeat implementation.

See [CREDITS.txt](CREDITS.txt), [Stockfish's AUTHORS](stable/AUTHORS) and
[the GNU GPL](stable/Copying.txt). The stable engine is GPL v3 or later.
Archived prototypes retain their own licence files and separate identities.

The complete corresponding source is available both in this repository and in
the Source ZIP linked above. It includes the actual
`stable/src/nn-252f33942263.nnue` model. Keep that source available alongside
any executables you redistribute.

[Source directory guide](README.txt) · [Build instructions](docs/Building-from-source.txt)

## Verification and research

Each inner package contains its own `SHA256SUMS.txt`. The public ZIPs are generated
by GitHub from separate, fixed package tags. The engine, source, model, licence
and installer files are preserved byte for byte from the verified release.
See [download verification](docs/Verify-downloads.md).

The archive, split-file reconstruction and Linux installer checks passed. The
installed Linux engine returned a legal move from an unrelated directory.
Windows executable checks used Wine. The new CMD installation helpers have
not been run on native Windows hardware.
[Packaging verification](docs/RELEASE-VERIFICATION.json) records those limits.

The recorded 100 ms training study reached 420 completed games: **55 wins,
318 draws and 47 losses** against full-strength Stockfish 19 with matched settings.
The first 100 fully audited games were **14 wins, 72 draws and 14 losses**.
The planned 1,000-game study and full 420-game audits are incomplete. The audited
subset does not establish a lower mistake rate or general superiority.
[TEST-NOTES.txt](TEST-NOTES.txt) gives binary identities, coverage and finite-judge limits.

No experimental version replaces the stable release. These exploratory results
do not establish a calibrated Elo, Stockfish superiority or perfect play.

## Share on Discord

Share **{RELEASE}** so people can choose their operating system.
The [ready-to-copy English post](docs/DISCORD-POST.txt) includes the download links,
setup steps and credits.

If your server prefers its own attachments, use the optional Discord upload pack.
Open its inner **WetMeat-Discord-Upload-Pack** folder and upload all numbered parts,
the README and the Join helpers for each package. Each part is at most 8 MiB.
Keep the Source set available alongside the engine files.
''')

    write(REPO / "docs" / "DISCORD-POST.txt", f'''**WetMeat 1.0 Stable — Windows & Linux**

I've put together a release of WetMeat, my Stockfish-based chess-engine project.
It includes English instructions, optional installers and the full source.

**Download page:** {RELEASE}

Windows: {links['windows']}
Linux: {links['linux']}
Complete source and actual model: {links['source']}
English guide: {guide}

Extract the ZIP on your PC. Open the versioned outer folder, then WetMeat-Windows
or WetMeat-Linux. Follow the README and add the engine to Cute Chess or Arena
as a UCI engine. The optional installer copies it to your user folder.

Use Skill Level 20, UCI_LimitStrength off and MultiPV 1. The network is embedded;
there is no extra model download for playing. These are x64 PC programs and
do not run directly on iPhone or iPad.

Cute Chess GUI: https://github.com/cutechess/cutechess/releases

WetMeat Stable uses Stockfish's search, evaluation and official NNUE weights.
Stockfish credits, GPL notices and the corresponding source are included.
The research versions are separate; this release makes no claim of being
stronger than Stockfish.
''')

    write(REPO / "docs" / "Verify-downloads.md", '''# Verify a download

GitHub generates each ZIP from a fixed package tag. Extract it and enter the
inner WetMeat-Windows, WetMeat-Linux or WetMeat-Source folder. The outer ZIP's
name contains its version; it does not need to match an example filename in
the original setup guide.

The inner `SHA256SUMS.txt` covers the actual package files. On Linux, run:

```bash
sha256sum -c SHA256SUMS.txt
```

The Linux installer checks that manifest before copying files. The Windows CMD
installer checks the engine EXE with the native Windows `certutil` command.
Both installers preserve an existing installation instead of replacing it.

The Discord pack's parts and Join helpers reconstruct the original saved ZIPs;
its checksums apply to those reconstructed files. GitHub's outer ZIP is a
separate container and is not expected to have the original saved ZIP hash.
GitHub may also change how it compresses generated archives over time; use the
inner file checksums to verify their contents.

Stable Windows AVX2 engine SHA256:
`ba3b51c100e2f7525b61d0a3fed9ffebc587d4b596c4264974cac500dc715282`

Stable Linux AVX2 engine SHA256:
`80ef6e114018f3ee823ba6c7411ff4f6160bc8d1f72f9ced399ed3144aa9ab6b`

Stable Linux AVX-512 engine SHA256:
`53a537c92e0ecf1ba5c1170e1f0724879bad871062ffbcd47dbffa9ff343d2c2`

The packaging checks do not measure engine strength. Native Windows installer
execution remains untested; the unchanged EXE had earlier checks under Wine.
''')

    write(ROOT / "release-notes-public.md", f'''WetMeat 1.0 Stable for Windows and Linux, with English instructions and
the complete corresponding source, actual NNUE model and Stockfish/GPL credits.

## Download your package

* **[Windows ZIP — about 80 MB]({links['windows']})**
* **[Linux ZIP — about 161 MB]({links['linux']})**
* **[Complete source and model — about 81 MB]({links['source']})**
* **[English setup guide (PDF)]({guide})**
* **[Ready-to-copy Discord post]({URL}/blob/main/docs/DISCORD-POST.txt)**
* **[Optional Discord attachment pack — about 323 MB]({links['discord']})**

These links download ZIPs directly from fixed package tags in this public repository.
After extracting one, open its versioned outer folder, then **WetMeat-Windows**,
**WetMeat-Linux** or **WetMeat-Source**. A `START-HERE.txt` file is included.
Use these Windows/Linux links for ready-to-run engines. GitHub's default
Source code links below contain the source checkout.

Windows: run the optional `Install-WetMeat.cmd`, or add the EXE under `bin` to a UCI
chess interface. Linux: run `bash install.sh` inside the WetMeat-Linux folder.
[Cute Chess](https://github.com/cutechess/cutechess/releases) and Arena are suitable
interfaces; the GUI is a separate download. The model is embedded in the engines.
Use a compatible x64 PC, not an iOS or ARM device.

## Source, licence and checks

The stable engine uses Stockfish's search, evaluation and official neural-network
weights. GPL v3-or-later and Stockfish author notices are preserved. The matching
source and actual model are available in the Source download and this repository.
Keep access to that source when redistributing the executables.

The engine, model, source and installer files are unchanged from the verified
stable packages. Each inner package has its own SHA256 manifest. The Discord pack
retains the original numbered parts and tested reassembly helpers.
[Verification details]({URL}/blob/main/docs/Verify-downloads.md)

Linux installation and archive/reassembly checks passed. Windows executable checks
used Wine; the new CMD installation helpers are not natively Windows-tested.

The saved 420-game training score at 100 ms/move was 55 wins, 318 draws and 47 losses;
the first 100 fully audited games were 14 wins, 72 draws and 14 losses. The planned
1,000-game study and full 420-game audits are incomplete. These exploratory results
do not establish superiority, a lower error rate, calibrated Elo or perfect play.

[Repository and full setup instructions]({URL})
''')

    for name in ["prepare_git_downloads.py", "update_download_docs.py", "upload_assets.py"]:
        shutil.copy2(ROOT / name, REPO / "release-tools" / "github-publish" / name)
    public = [{k: p[k] for k in ["kind", "tag", "commit", "folder", "download_url"]}
              for p in meta["packages"]]
    write(REPO / "docs" / "Package-downloads.json", json.dumps(public, indent=2))
    print(json.dumps({"documentation_updated": True, "packages": public}))


if __name__ == "__main__":
    main()
