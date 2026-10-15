# WetMeat 1.0 Stable

WetMeat is a Stockfish-based chess-engine project for Windows and Linux.
The stable engine comes with English instructions, optional installers and its
complete corresponding source, including the actual neural-network file.

## Downloads

**[Open the download release](https://github.com/mwmwqxzk5h-del/WetMeat/releases/tag/v1.0.0)** or choose a package below.

| Package | Download | Requirements |
| --- | --- | --- |
| Windows, about 80 MB | [Windows ZIP](https://github.com/mwmwqxzk5h-del/WetMeat/archive/refs/tags/v1.0.0-windows.zip) | Windows 10/11, x64 AVX2 |
| Linux, about 161 MB | [Linux ZIP](https://github.com/mwmwqxzk5h-del/WetMeat/archive/refs/tags/v1.0.0-linux.zip) | x64 AVX2; optional AVX-512 build included |
| Complete source, about 81 MB | [Source ZIP](https://github.com/mwmwqxzk5h-del/WetMeat/archive/refs/tags/v1.0.0-source.zip) | Code, actual model, licences and research archive |
| English setup guide | [PDF](https://raw.githubusercontent.com/mwmwqxzk5h-del/WetMeat/main/docs/WetMeat-Setup-English.pdf) | Readable on a phone or PC |
| Optional Discord attachments, about 323 MB | [Discord upload pack](https://github.com/mwmwqxzk5h-del/WetMeat/archive/refs/tags/v1.0.0-discord.zip) | Numbered parts and reassembly helpers |

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

The optional installer uses `%LOCALAPPDATA%\WetMeat\1.0-stable` and needs no
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

Share **https://github.com/mwmwqxzk5h-del/WetMeat/releases/tag/v1.0.0** so people can choose their operating system.
The [ready-to-copy English post](docs/DISCORD-POST.txt) includes the download links,
setup steps and credits.

If your server prefers its own attachments, use the optional Discord upload pack.
Open its inner **WetMeat-Discord-Upload-Pack** folder and upload all numbered parts,
the README and the Join helpers for each package. Each part is at most 8 MiB.
Keep the Source set available alongside the engine files.
