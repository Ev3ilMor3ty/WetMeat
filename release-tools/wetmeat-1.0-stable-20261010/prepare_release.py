"""Package unchanged stable WetMeat with German instructions. GPL-3.0-or-later."""
import datetime as dt
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import zipfile

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Preformatted, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parent
PROJECT = Path('/workspace/aurora-stockfish')
TRIAL = PROJECT / 'results/original-100ms-1000-20261007-1835'
EXPECTED = {
    'wetmeat-windows-avx2.exe': 'ba3b51c100e2f7525b61d0a3fed9ffebc587d4b596c4264974cac500dc715282',
    'wetmeat-linux-avx2': '80ef6e114018f3ee823ba6c7411ff4f6160bc8d1f72f9ced399ed3144aa9ab6b',
    'wetmeat-linux-avx512': '53a537c92e0ecf1ba5c1170e1f0724879bad871062ffbcd47dbffa9ff343d2c2',
}


def load(path):
    return json.loads(Path(path).read_text())


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n' if isinstance(data, dict) else data)


def inline(text):
    text = html.escape(text)
    text = re.sub(r'`([^`]+)`', r'<font name="Mono">\1</font>', text)
    return re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)


def make_pdf(source, output):
    fonts = Path('/usr/share/fonts/truetype/dejavu')
    for name, filename in [('Body', 'DejaVuSans.ttf'), ('Body-Bold', 'DejaVuSans-Bold.ttf'),
                           ('Mono', 'DejaVuSansMono.ttf')]:
        pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
    pdfmetrics.registerFontFamily('Body', normal='Body', bold='Body-Bold', italic='Body', boldItalic='Body-Bold')
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='GuideBody', fontName='Body', fontSize=9.5, leading=14, spaceAfter=7))
    styles.add(ParagraphStyle(name='GuideTitle', fontName='Body-Bold', fontSize=22, leading=27,
                              textColor=colors.HexColor('#15463c'), spaceAfter=14))
    styles.add(ParagraphStyle(name='GuideHeading', fontName='Body-Bold', fontSize=12, leading=16,
                              textColor=colors.HexColor('#15463c'), spaceBefore=11, spaceAfter=7))
    styles.add(ParagraphStyle(name='GuideCode', fontName='Mono', fontSize=8, leading=12,
                              backColor=colors.HexColor('#f2f5f4'), borderPadding=8, spaceAfter=9))
    styles.add(ParagraphStyle(name='GuideCell', fontName='Body', fontSize=8.4, leading=12))
    story = []
    lines = source.read_text().splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line:
            index += 1
            continue
        if line.startswith('```'):
            index += 1
            code = []
            while index < len(lines) and not lines[index].startswith('```'):
                code.append(lines[index]); index += 1
            story.append(Preformatted('\n'.join(code), styles['GuideCode'], maxLineLength=92))
            index += 1
        elif line.startswith('|'):
            rows = []
            while index < len(lines) and lines[index].startswith('|'):
                cells = lines[index].strip('|').split('|')
                if not all(re.fullmatch(r'[\s:-]+', cell) for cell in cells):
                    rows.append([Paragraph(inline(cell.strip()), styles['GuideCell']) for cell in cells])
                index += 1
            table = Table(rows, colWidths=[59 * mm, 113 * mm], repeatRows=1, hAlign='LEFT')
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e3efeb')),
                ('GRID', (0, 0), (-1, -1), .35, colors.HexColor('#b9c9c4')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
                ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            story += [table, Spacer(1, 8)]
        elif line.startswith('# '):
            story.append(Paragraph(inline(line[2:]), styles['GuideTitle'])); index += 1
        elif line.startswith('## '):
            story.append(Paragraph(inline(line[3:]), styles['GuideHeading'])); index += 1
        else:
            paragraph = [line]
            numbered = bool(re.match(r'\d+\. ', line)) or line.startswith('- ')
            index += 1
            while index < len(lines) and lines[index] and not lines[index].startswith(('#', '|', '```', '- ')) \
                    and not re.match(r'\d+\. ', lines[index]):
                paragraph.append(lines[index].strip()); index += 1
            text = ' '.join(paragraph)
            story.append(Paragraph(inline(text), styles['GuideBody']))

    def footer(canvas, document):
        canvas.setFont('Body', 8)
        canvas.setFillColor(colors.HexColor('#566d66'))
        canvas.drawString(19 * mm, 13 * mm, 'WetMeat 1.0 Stable | Installation | 10.10.2026')
        canvas.drawRightString(191 * mm, 13 * mm, str(document.page))

    SimpleDocTemplate(str(output), pagesize=A4, rightMargin=19 * mm, leftMargin=19 * mm,
                      topMargin=18 * mm, bottomMargin=23 * mm, title='WetMeat 1.0 Stable — Installation',
                      author='WetMeat project', subject='Deutsche Anleitung für Windows und Linux') \
        .build(story, onFirstPage=footer, onLaterPages=footer)


def collect_evidence():
    plan = load(TRIAL / 'plan.json')
    assert digest(TRIAL / 'plan.json') == load(TRIAL / 'ready.json')['plan_sha256']
    for binary, expected in EXPECTED.items():
        assert digest(PROJECT / 'bin' / binary) == expected
    scores = {'wins': 0, 'draws': 0, 'losses': 0}
    pgns = []
    records = []
    for path in sorted((TRIAL / 'training').glob('batch-*/game-*.json')):
        game = load(path)
        assert game['tested_binary_sha256'] == plan['stable_sha256']
        assert game['opponent_binary_sha256'] == plan['opponent_sha256']
        assert game['requested_movetime_ms'] == 100
        assert game['phase'] == 'training' and game['variant'] == 'baseline'
        assert not game['engine_error'] and game['tested_points'] is not None
        for side in ['tested_uci_settings', 'opponent_uci_settings']:
            assert all(game[side][key] == value for key, value in plan['common_uci'].items())
        scores[{1: 'wins', .5: 'draws', 0: 'losses'}[game['tested_points']]] += 1
        pgn = path.with_suffix('.pgn')
        pgns.append(pgn.read_text())
        records.append({'round': game['round'], 'pair': game['pair'], 'result': game['result'],
                        'tested_color': game['tested_color'], 'termination': game['termination'],
                        'game_sha256': digest(path), 'pgn_sha256': digest(pgn)})
    totals = {side: {key: 0 for key in ['moves', 'checked_moves', 'mistakes', 'blunders', 'shallow_judge_moves']}
              for side in ['wetmeat', 'stockfish']}
    batch_sources = []
    audited_scores = {key: 0 for key in scores}
    for path in sorted((TRIAL / 'training').glob('batch-*/batch-evidence.json')):
        assert digest(path) == load(path.with_name('batch-evidence-ready.json'))['sha256']
        batch = load(path)
        assert batch['audit_complete'] and batch['completed_games'] == 20
        assert batch['engine_faults'] == batch['incomplete_games_excluded'] == 0
        for key in ['stable_sha256', 'opponent_sha256', 'common_uci', 'audit_settings']:
            assert batch[key] == plan[key]
        for side, stats in totals.items():
            assert batch['by_engine'][side]['checked_moves'] == batch['by_engine'][side]['moves']
            for key in stats:
                stats[key] += batch['by_engine'][side][key]
        for key in scores:
            audited_scores[key] += batch[key]
        batch_sources.append({'file': str(path), 'sha256': digest(path)})
    for stats in totals.values():
        stats['mistake_rate'] = stats['mistakes'] / stats['moves']
        stats['blunder_rate'] = stats['blunders'] / stats['moves']
    assert scores == {'wins': 55, 'draws': 318, 'losses': 47} and len(batch_sources) == 20
    (ROOT / 'evidence').mkdir(exist_ok=True)
    write(ROOT / 'evidence' / 'baseline-420-games.pgn', '\n\n'.join(pgns))
    report = {'packaged_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'version': 'WetMeat 1.0 Stable',
              'binaries_sha256': EXPECTED, 'plan_sha256': digest(TRIAL / 'plan.json'),
              'source_progress_last_saved_utc': load(TRIAL / 'progress.json')['snapshot_utc'],
              'completed_games': len(records), 'scores': scores, 'game_records': records,
              'fully_audited_games': 400, 'fully_audited_subset_scores': audited_scores,
              'fully_audited_400game_subset_by_engine': totals, 'batch_sources': batch_sources,
              'first100_game_sample': load(TRIAL / 'observations/milestone-100.json'),
              'remaining420game_coverage_incomplete': True, 'full420_error_rates': None,
              'planned1000games_complete': False, 'candidate_adopted': False, 'engine_changed': False,
              'strength_measurement_binary': plan['stable_sha256'],
              'windows_native_hardware_tested': False, 'windows_test_platform': 'Wine on Linux',
              'test_processes_observed_live_at_packaging': False,
              'limits': 'TRAINING data, finite shared-family common-depth judge, shallower comparisons and correlated '
                        'opening pairs. No general superiority, Elo or perfect-play claim. Windows/Linux-AVX2 '
                        'do not inherit Linux-AVX512 head-to-head measured scores.'}
    write(ROOT / 'evidence' / 'release-evidence.json', report)
    text = '# WetMeat 1.0 Stable — Ergebnisstand 10.10.2026\n\n'
    text += 'Empfohlen wird die unveränderte stabile Version. Keine experimentelle Version wurde als Verbesserung bestätigt oder übernommen. '
    text += 'Das Paket erneuert die Anleitung und stellt vorhandene Ergebnisse bereit; kein neuer Schachalgorithmus und keine neue NNUE.\n\n'
    text += '420 abgeschlossene Partien mit 100 ms pro Zug: **55 Siege, 318 Remis, 47 Niederlagen**. Erste 100 Partien: **14 Siege, 72 Remis, 14 Niederlagen**. '
    text += 'Gegner: Stockfish 19 bei voller Einstellung. Beide: Threads 1, Hash 128 MB, 100 ms/Zug, Skill 20, keine Elo-Begrenzung, kein Ponder, keine Tablebases; CPUs 0/1 rotierend, beide Farben.\n\n'
    text += '## Vollständig auditierter Teil mit 400 Partien\n\n| Engine | Züge geprüft | Fehler 50–199 cp | Grobe Fehler ab 200 cp | Flachere Richtertiefe |\n|---|---:|---:|---:|---:|\n'
    for side, stats in totals.items():
        text += f"| {side} | {stats['checked_moves']}/{stats['moves']} | {stats['mistakes']} | {stats['blunders']} | {stats['shallow_judge_moves']} |\n"
    text += '\nDie übrigen 20 Partien sind nur teilweise auditiert. Deshalb gibt es keine vollständige Fehlerquote für alle 420 Partien. '
    text += 'Die Stichprobe bestätigt bisher keine niedrigere Fehlerquote gegenüber Stockfish. '
    text += 'Die geplanten 1000 Partien sind nicht abgeschlossen. Letzter gespeicherter Fortschritt: 08.10.2026. Am 10.10.2026 waren bei der Prüfung keine Testprozesse aktiv. Checkpoints bleiben erhalten.\n\n'
    text += 'Vergleichsergebnisse wurden ausschließlich mit dem Linux-AVX-512-Binary gemessen. Andere ausgelieferte Builds haben denselben Quellstand und dieselben Gewichte, aber eigene Prüfsummen und keine übernommenen Matchresultate. '
    text += 'Windows-Protokolltests liefen unter Wine, nicht auf echter Windows-Hardware. Keine macOS-/ARM-/Handy-Binaries getestet.\n\n'
    text += 'Fehlermethode: vollständige Partieverläufe; Stockfish 19 mit mehr Suchknoten; mindestens 1 Million und zweimal die gespielten Knoten; verdächtige Differenzen werden mit vierfachem Budget nachgeprüft; Alternativen bei gemeinsamer vollständig abgeschlossener MultiPV-Tiefe verglichen. '
    text += 'Endliche Bewertungen aus derselben Engine-Familie, flachere Richtertiefe, Abhängigkeit von Zügen/Eröffnungen und wiederholte Explorationsblicke begrenzen die Aussage. Kein Überlegenheits-, Elo- oder Perfektionsnachweis.\n\n'
    text += 'Historische Linux- und Wine-Prüfungen: `docs/TESTS.md`. Aktuelle Paketprüfungen: `docs/PACKAGE-VERIFICATION-20261010.json`. '
    text += 'Gemessene 420 Partien: `evidence/baseline-420-games.pgn`; Prüfsummen und Quellen: `evidence/release-evidence.json`. '
    text += 'Quellcode, tatsächlich verwendete NNUE-Datei, GPL und AUTHORS liegen vollständig im Paket. Die frühere 247-Züge-Studie und alle älteren Veröffentlichungen bleiben unverändert.\n'
    write(ROOT / 'RELEASE-STATUS-20261010.md', text)
    return report


def package(platform, binaries):
    original = Path('/workspace') / f'wetmeat-{platform.lower()}.zip'
    output = ROOT / f'WetMeat-1.0-Stable-{platform}.zip'
    assert not output.exists(), 'Preserve existing releases instead of overwriting'
    shutil.copyfile(original, output)
    additions = {
        'wetmeat/INSTALLATION-DE.md': ROOT / 'INSTALLATION-DE.md',
        'wetmeat/INSTALLATION-DE.pdf': ROOT / 'INSTALLATION-DE.pdf',
        'wetmeat/START-HERE-DE.txt': ROOT / 'START-HERE-DE.txt',
        'wetmeat/docs/RELEASE-STATUS-20261010.md': ROOT / 'RELEASE-STATUS-20261010.md',
        'wetmeat/evidence/release-evidence.json': ROOT / 'evidence/release-evidence.json',
        'wetmeat/evidence/baseline-420-games.pgn': ROOT / 'evidence/baseline-420-games.pgn',
        'wetmeat/docs/PACKAGE-VERIFICATION-20261010.json': ROOT / 'verification.json',
    }
    for path in sorted((ROOT / 'verification').iterdir()):
        if path.name.endswith('.protocol.json') or path.name.endswith('.protocol.log') or path.name == 'native-smoke-stdout.txt':
            additions['wetmeat/docs/release-checks/' + path.name] = path
    with zipfile.ZipFile(output, 'a', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in additions.items():
            assert name not in archive.namelist()
            archive.write(path, name)
        assert archive.testzip() is None
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert all(name.startswith('wetmeat/') and '..' not in Path(name).parts for name in names)
        hashes = {}
        for name in names:
            with archive.open(name) as stream:
                hashes[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
        for binary in binaries:
            assert hashes['wetmeat/bin/' + binary] == EXPECTED[binary]
        network = 'wetmeat/src/nn-252f33942263.nnue'
        assert hashes[network] == '252f33942263bc8b8f740ba8aec3fed5a159ff148113c47a55c18c33d6627ab3'
        for path in (PROJECT / 'src').rglob('*'):
            if path.is_file() and (path.suffix in {'.cpp', '.h'} or path.name == 'Makefile'):
                assert hashes['wetmeat/' + str(path.relative_to(PROJECT))] == digest(path)
        for name in ['Copying.txt', 'AUTHORS', 'tools/build.sh', 'scripts/get_native_properties.sh']:
            assert hashes['wetmeat/' + name] == digest(PROJECT / name)
        sums = ''.join(f'{value}  {name.removeprefix("wetmeat/")}\n' for name, value in sorted(hashes.items()))
        assert 'wetmeat/SHA256SUMS.txt' not in names
        archive.writestr('wetmeat/SHA256SUMS.txt', sums)
    return {'file': str(output), 'bytes': output.stat().st_size, 'sha256': digest(output),
            'files': len(hashes) + 1, 'original_archive_sha256': digest(original),
            'binaries_unchanged': True, 'full_source_weights_GPL_AUTHORS_verified': True,
            'all_entry_checksums_verified': True}


if __name__ == '__main__':
    collect_evidence()
    make_pdf(ROOT / 'INSTALLATION-DE.md', ROOT / 'INSTALLATION-DE.pdf')
    assert (ROOT / 'verification.json').exists(), 'Verify binaries before packaging'
    records = [package('Windows', ['wetmeat-windows-avx2.exe']),
               package('Linux', ['wetmeat-linux-avx2', 'wetmeat-linux-avx512'])]
    write(ROOT / 'release-packages.json', {'packages': records})
    write(ROOT / 'DOWNLOADS-SHA256.txt', ''.join(f"{row['sha256']}  {Path(row['file']).name}\n" for row in records))
    print(json.dumps({'packages': records}, indent=2))
