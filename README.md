# WetMeat 1.0 Stable

WetMeat is a Stockfish-based chess-engine project for Windows and Linux.
This release packages the unchanged stable engine with English setup instructions,
optional installation helpers and the complete project source, including its actual
neural-network file.

## Downloads

**[Open the release and download the files here](https://github.com/mwmwqxzk5h-del/WetMeat/releases/tag/v1.0.0).**

| File | Download | Use |
| --- | --- | --- |
| Windows, about 80 MB | [WetMeat-Windows.zip](https://github.com/mwmwqxzk5h-del/WetMeat/releases/download/v1.0.0/WetMeat-Windows.zip) | Windows 10/11, x64 AVX2 |
| Linux, about 161 MB | [WetMeat-Linux.zip](https://github.com/mwmwqxzk5h-del/WetMeat/releases/download/v1.0.0/WetMeat-Linux.zip) | x64 AVX2 and AVX-512 builds |
| Complete project source, about 81 MB | [WetMeat-Source.zip](https://github.com/mwmwqxzk5h-del/WetMeat/releases/download/v1.0.0/WetMeat-Source.zip) | Code, actual model, licences and research archive |
| English setup guide | [WetMeat-Setup-English.pdf](https://github.com/mwmwqxzk5h-del/WetMeat/releases/download/v1.0.0/WetMeat-Setup-English.pdf) | Windows and Linux instructions |
| Download checksums | [SHA256SUMS.txt](https://github.com/mwmwqxzk5h-del/WetMeat/releases/download/v1.0.0/SHA256SUMS.txt) | Verify the release files |

Use the Windows or Linux package to play. GitHub's green **Code** button downloads
source code; it is not the ready-to-run engine package.

## Windows setup

1. Download `WetMeat-Windows.zip` and choose **Extract All**.
2. Open the extracted folder. You can use `bin/wetmeat-windows-avx2.exe` directly,
   or run `Install-WetMeat.cmd` to copy it to your user folder.
3. Install a chess interface such as [Cute Chess](https://github.com/cutechess/cutechess/releases)
   or Arena. The graphical interface is a separate download.
4. Add the EXE as a **UCI engine** in that interface.

The default installer destination is `%LOCALAPPDATA%\WetMeat\1.0-stable`.
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

Share **https://github.com/mwmwqxzk5h-del/WetMeat/releases/tag/v1.0.0** so people can choose their operating system.
The ready-to-copy [English Discord post](docs/DISCORD-POST.txt) includes the downloads,
setup steps and credits. GitHub hosts the binaries and their corresponding source;
there is no need to re-upload split files to Discord.

An optional `WetMeat-Discord-Upload-Pack.zip` release asset also contains parts of
at most 8 MiB and reassembly helpers, for servers that prefer their own attachments.
