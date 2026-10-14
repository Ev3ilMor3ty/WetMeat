"""Build the English release and small, checksummed Discord attachments."""
# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat
import zipfile

ROOT = Path(__file__).resolve().parent
WORK = ROOT / 'staging'
DIST = ROOT / 'dist'
PROJECT = Path('/workspace/aurora-stockfish')
PART_BYTES = 8 * 1024 * 1024
MODEL_HASH = '252f33942263bc8b8f740ba8aec3fed5a159ff148113c47a55c18c33d6627ab3'
BINARIES = {
    'wetmeat-windows-avx2.exe': 'ba3b51c100e2f7525b61d0a3fed9ffebc587d4b596c4264974cac500dc715282',
    'wetmeat-linux-avx2': '80ef6e114018f3ee823ba6c7411ff4f6160bc8d1f72f9ced399ed3144aa9ab6b',
    'wetmeat-linux-avx512': '53a537c92e0ecf1ba5c1170e1f0724879bad871062ffbcd47dbffa9ff343d2c2',
}
CODE_TYPES = {'.cpp', '.c', '.h', '.hpp', '.s', '.S', '.py', '.sh', '.cmd', '.bat',
              '.ps1', '.js', '.ts', '.tsx', '.jsx', '.css', '.html', '.cmake', '.patch', '.yml', '.yaml', '.epd', '.exp'}
CODE_NAMES = {'Makefile', 'CMakeLists.txt', 'LICENSE', 'COPYING', 'Copying.txt', 'AUTHORS',
              'UNLICENSE', 'UPSTREAM_README.md', 'CITATION.cff', '.clang-format',
              'package.json', 'package-lock.json', 'pyproject.toml', '.gitignore', '.gitattributes', 'Top CPU Contributors.txt'}
SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.cache', 'bin',
             'staging', 'dist', 'downloads', 'verification', 'discord-parts', 'test-run'}


def checksum(path):
    digest = sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def copy_file(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def source_files(root):
    for directory, folders, files in os.walk(root):
        folders[:] = sorted(name for name in folders
                            if name not in SKIP_DIRS and not name.startswith('build'))
        for name in sorted(files):
            path = Path(directory) / name
            if (path.suffix in CODE_TYPES or name in CODE_NAMES
                    or name.startswith('requirements') and name.endswith('.txt')
                    or path.suffix in {'.txt', '.json', '.pgn', '.csv'} and 'tests' in path.relative_to(root).parts
                    or path.suffix in {'.jsonl', '.metadata.json'} and 'data' in path.relative_to(root).parts):
                yield path


def add_manifest(folder):
    manifest = folder / 'SHA256SUMS.txt'
    entries = [f'{checksum(path)}  {path.relative_to(folder).as_posix()}\n'
               for path in sorted(folder.rglob('*')) if path.is_file() and path != manifest]
    manifest.write_text(''.join(entries))


def make_zip(folder, output):
    if output.exists():
        raise FileExistsError(f'Keep the previous archive; choose a new output: {output}')
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                archive.write(path, (Path(folder.name) / path.relative_to(folder)).as_posix())
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError(f'ZIP integrity check failed: {output}')
        names = archive.namelist()
        if len(names) != len(set(names)) or any('..' in Path(name).parts for name in names):
            raise RuntimeError('Invalid archive paths')
    return {'file': str(output), 'bytes': output.stat().st_size, 'sha256': checksum(output)}


def make_guide():
    from xml.sax.saxutils import escape
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Preformatted, Spacer, PageBreak

    fonts = Path('/usr/share/fonts/truetype/dejavu')
    pdfmetrics.registerFont(TTFont('Guide', str(fonts / 'DejaVuSans.ttf')))
    pdfmetrics.registerFont(TTFont('GuideBold', str(fonts / 'DejaVuSans-Bold.ttf')))
    pdfmetrics.registerFont(TTFont('GuideMono', str(fonts / 'DejaVuSansMono.ttf')))
    body = ParagraphStyle('body', fontName='Guide', fontSize=9.5, leading=14, spaceAfter=7)
    title = ParagraphStyle('title', fontName='GuideBold', fontSize=21, leading=27,
                           spaceAfter=15, textColor=colors.HexColor('#164b3d'))
    heading = ParagraphStyle('heading', fontName='GuideBold', fontSize=12, leading=16,
                             spaceBefore=10, spaceAfter=7, keepWithNext=True)
    code = ParagraphStyle('code', fontName='GuideMono', fontSize=8.1, leading=12,
                          spaceAfter=8, backColor=colors.HexColor('#edf3f0'))
    story = []
    for document_index, filename in enumerate(('README-WINDOWS.txt', 'README-LINUX.txt', 'SHARING-ON-DISCORD.txt')):
        if document_index:
            story.append(PageBreak())
        lines = (ROOT / 'docs' / filename).read_text().splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            if not line:
                index += 1
                continue
            if index + 1 < len(lines) and lines[index + 1] and set(lines[index + 1]) <= {'=', '-'}:
                style = title if set(lines[index + 1]) == {'='} else heading
                story.append(Paragraph(escape(line), style)); index += 2
                continue
            if line.startswith('   ') or ':' in line and filename.startswith('README') and line.startswith(('Skill', 'UCI_', 'MultiPV', 'Threads', 'Hash', 'Ponder', 'Move Overhead', 'SyzygyPath')):
                block = [line]
                index += 1
                while index < len(lines) and lines[index] and lines[index].startswith('   '):
                    block.append(lines[index]); index += 1
                story.append(Preformatted('\n'.join(block), code, maxLineLength=92))
                continue
            paragraph = [line]
            index += 1
            while index < len(lines) and lines[index] and not lines[index].startswith('   ') \
                    and not (index + 1 < len(lines) and lines[index + 1] and set(lines[index + 1]) <= {'=', '-'}) \
                    and not (lines[index][:1].isdigit() and lines[index][1:3] == '. '):
                paragraph.append(lines[index]); index += 1
            story.append(Paragraph(escape(' '.join(paragraph)), body))
    def footer(canvas, document):
        canvas.setFont('Guide', 8)
        canvas.setFillColor(colors.HexColor('#526a60'))
        canvas.drawString(50, 28, 'WetMeat 1.0 Stable | English setup guide')
        canvas.drawRightString(A4[0] - 50, 28, str(document.page))
    output = DIST / 'WetMeat-Setup-English.pdf'
    SimpleDocTemplate(str(output), pagesize=A4, leftMargin=50, rightMargin=50,
                      topMargin=42, bottomMargin=48, title='WetMeat 1.0 — Windows and Linux setup') \
        .build(story, onFirstPage=footer, onLaterPages=footer)


def stage_runtime(platform, binaries):
    folder = WORK / ('WetMeat-' + platform)
    folder.mkdir(parents=True, exist_ok=True)
    for name in binaries:
        binary = PROJECT / 'bin' / name
        if checksum(binary) != BINARIES[name]:
            raise RuntimeError('The frozen release binary changed: ' + name)
        copy_file(binary, folder / 'bin' / name)
    for source, destination in [('CREDITS.txt', 'CREDITS.txt'), ('TEST-NOTES.txt', 'TEST-NOTES.txt'),
                                 ('README-' + platform.upper() + '.txt', 'README.txt')]:
        copy_file(ROOT / 'docs' / source, folder / destination)
    for name in ('Copying.txt', 'AUTHORS', 'UPSTREAM_README.md'):
        copy_file(PROJECT / name, folder / name)
    copy_file(DIST / 'WetMeat-Setup-English.pdf', folder / 'Setup-English.pdf')
    helper = 'Install-WetMeat.cmd' if platform == 'Windows' else 'install.sh'
    copy_file(ROOT / 'helpers' / helper, folder / helper)
    if helper.endswith('.cmd'):
        path = folder / helper
        path.write_bytes(path.read_text().replace('\n', '\r\n').encode('ascii'))
    else:
        (folder / helper).chmod(0o755)
    add_manifest(folder)
    return make_zip(folder, DIST / (folder.name + '.zip'))


def stage_source():
    folder = WORK / 'WetMeat-Source'
    projects = [
        (Path('/workspace/aurora-stockfish'), 'stable'),
        (Path('/workspace/wetmeat-experimental'), 'research/timing'),
        (Path('/workspace/wetmeat-original-experiments/draw-aversion'), 'research/draw-aversion'),
        (Path('/workspace/wetmeat-independent'), 'research/independent'),
        (Path('/workspace/aurora-chess'), 'research/aurora'),
        (Path('/workspace/aurora-lab'), 'research/aurora-lab'),
        (Path('/workspace/releases'), 'release-tools'),
    ]
    inventory = []
    for origin, prefix in projects:
        for path in source_files(origin):
            relative = path.relative_to(origin)
            if origin == PROJECT and relative.parts[0] == 'results':
                target = folder / 'study-snapshots' / Path(*relative.parts[1:])
            else:
                target = folder / prefix / relative
            copy_file(path, target)
            inventory.append({'project': prefix, 'file': target.relative_to(folder).as_posix(),
                              'sha256': checksum(target), 'bytes': target.stat().st_size})
    # Preserve the actual model once. The supplied helper populates the two
    # archived Stockfish-derived experiments without another download.
    model = PROJECT / 'src/nn-252f33942263.nnue'
    if checksum(model) != MODEL_HASH:
        raise RuntimeError('The supplied model changed')
    copy_file(model, folder / 'stable/src' / model.name)
    copy_file(ROOT / 'helpers/prepare-research.py', folder / 'prepare-research.py')
    copy_file(ROOT / 'docs/SOURCE-README.txt', folder / 'README.txt')
    copy_file(ROOT / 'docs/SOURCE-BUILD.txt', folder / 'stable/README.txt')
    copy_file(ROOT / 'docs/CREDITS.txt', folder / 'CREDITS.txt')
    copy_file(ROOT / 'docs/TEST-NOTES.txt', folder / 'TEST-NOTES.txt')
    # The small generated weights are source for the older standalone lab.
    for path in Path('/workspace/aurora-lab/data').glob('*.metadata.json'):
        copy_file(path, folder / 'research/aurora-lab/data' / path.name)
    for path in sorted((ROOT / 'docs').glob('*.txt')):
        copy_file(path, folder / 'release-tools' / ROOT.name / 'docs' / path.name)
    (folder / 'release-tools' / ROOT.name / 'requirements-release.txt').write_text('reportlab>=4,<5\n')
    write_json(folder / 'CODE-INVENTORY.json', {'files': inventory, 'count': len(inventory),
               'stable_model_sha256': MODEL_HASH, 'stable_cpp_unmodified': True,
               'source_of_build_tools': 'release-tools/wetmeat-english-discord-20261014',
               'excluded': ['compiled objects', 'virtual environments', 'caches', 'raw run outputs', 'private continuation records']})
    add_manifest(folder)
    return make_zip(folder, DIST / 'WetMeat-Source.zip'), inventory


def join_shell(archive, count, expected):
    return f'''#!/usr/bin/env bash
set -euo pipefail
part_dir="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
archive="$part_dir/{archive}"
expected='{expected}'
if [[ -e $archive ]]; then
    printf '%s  %s\\n' "$expected" "$archive" | sha256sum --strict --check -
    echo "Ready: $archive"
    exit 0
fi
for ((number=1; number<={count}; number++)); do
    printf -v name '{archive}.part%03d' "$number"
    if [[ ! -f "$part_dir/$name" ]]; then
        echo "Missing part: $name" >&2
        exit 1
    fi
done
temporary="$(mktemp "$part_dir/.wetmeat-join.XXXXXX")"
trap 'rm -f -- "$temporary"' EXIT
for ((number=1; number<={count}; number++)); do
    printf -v name '{archive}.part%03d' "$number"
    cat -- "$part_dir/$name" >> "$temporary"
done
printf '%s  %s\\n' "$expected" "$temporary" | sha256sum --strict --check -
ln -- "$temporary" "$archive"
echo "Ready: $archive"
echo 'Extract this ZIP and read README.txt inside it.'
'''


def join_windows(archive, count, expected):
    parts = '+'.join(f'"{archive}.part{number:03d}"' for number in range(1, count + 1))
    checks = '\n'.join(f'if not exist "{archive}.part{number:03d}" (echo Missing part {number:03d} & exit /b 1)'
                       for number in range(1, count + 1))
    return f'''@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 1
if exist "{archive}" goto existing
{checks}
set "wetmeat_temporary=%TEMP%\\wetmeat-join-%RANDOM%-%RANDOM%.zip"
if exist "%wetmeat_temporary%" exit /b 1
copy /b {parts} "%wetmeat_temporary%" >nul
if errorlevel 1 goto failed
call :verify "%wetmeat_temporary%"
if errorlevel 1 goto failed
move /-y "%wetmeat_temporary%" "{archive}" <nul >nul
if errorlevel 1 goto failed
echo Ready: {archive}
echo Extract the ZIP and read README.txt inside it.
popd
pause
exit /b 0
:existing
call :verify "{archive}"
if errorlevel 1 exit /b 1
echo Ready: {archive}
popd
exit /b 0
:verify
certutil -hashfile "%~1" SHA256 2>nul | findstr /i /x /c:"{expected}" >nul
exit /b %errorlevel%
:failed
if exist "%wetmeat_temporary%" del "%wetmeat_temporary%" >nul 2>nul
echo Joining failed. Check that every numbered part is present and unchanged.
popd
exit /b 1
'''


def split_package(package, group):
    archive = Path(package['file'])
    folder = ROOT / 'discord-parts' / 'WetMeat-Discord-Upload-Pack' / group
    folder.mkdir(parents=True, exist_ok=True)
    parts = []
    with archive.open('rb') as stream:
        number = 1
        while chunk := stream.read(PART_BYTES):
            path = folder / f'{archive.name}.part{number:03d}'
            path.write_bytes(chunk)
            parts.append({'name': path.name, 'bytes': len(chunk), 'sha256': sha256(chunk).hexdigest()})
            number += 1
    (folder / f'Join-{group}.sh').write_text(join_shell(archive.name, len(parts), package['sha256']))
    (folder / f'Join-{group}.sh').chmod(0o755)
    (folder / f'Join-{group}.cmd').write_bytes(join_windows(archive.name, len(parts), package['sha256']).replace('\n', '\r\n').encode('ascii'))
    write_json(folder / 'PARTS.json', {'archive': archive.name, 'archive_sha256': package['sha256'], 'parts': parts})
    (folder / 'README.txt').write_text(
        f'{group}: save all {len(parts)} numbered parts and the Join helper into ONE folder.\n'
        f'Windows: run Join-{group}.cmd. Linux: bash Join-{group}.sh\n'
        f'The result must be {archive.name}, SHA256 {package["sha256"]}.\n'
        'The helpers only join parts and check the archive; extract the finished ZIP separately.\n'
        'Keep original filenames. A numbered part is not an individual ZIP archive.\n')
    return {'group': group, 'directory': str(folder), 'archive': package, 'part_count': len(parts), 'parts': parts}


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(exist_ok=True)
    make_guide()
    windows = stage_runtime('Windows', ['wetmeat-windows-avx2.exe'])
    linux = stage_runtime('Linux', ['wetmeat-linux-avx2', 'wetmeat-linux-avx512'])
    source, inventory = stage_source()
    groups = [split_package(package, group) for package, group in
              [(windows, 'Windows'), (linux, 'Linux'), (source, 'Source')]]
    parts_root = ROOT / 'discord-parts/WetMeat-Discord-Upload-Pack'
    for name in ('DISCORD-POST.txt', 'SHARING-ON-DISCORD.txt', 'CREDITS.txt'):
        copy_file(ROOT / 'docs' / name, parts_root / name)
        copy_file(ROOT / 'docs' / name, DIST / name)
    copy_file(DIST / 'WetMeat-Setup-English.pdf', parts_root / 'WetMeat-Setup-English.pdf')
    add_manifest(parts_root)
    upload = make_zip(parts_root, DIST / 'WetMeat-Discord-Upload-Pack.zip')
    packages = [windows, linux, source, upload]
    (DIST / 'SHA256SUMS.txt').write_text(''.join(f'{item["sha256"]}  {Path(item["file"]).name}\n' for item in packages))
    report = {'prepared_utc': datetime.now(timezone.utc).isoformat(), 'packages': packages,
              'source_file_count': len(inventory), 'discord_part_bytes_max': PART_BYTES,
              'discord_groups': groups, 'engine_binaries_unchanged': True,
              'source_and_actual_model_provided': True, 'stockfish_credits_preserved': True,
              'externally_published': False, 'messages_sent_to_discord': False}
    write_json(ROOT / 'distribution.json', report)
    print(json.dumps({'packages': packages, 'source_files': len(inventory),
                      'discord_part_counts': {row['group']: row['part_count'] for row in groups}}, indent=2))


if __name__ == '__main__':
    main()
