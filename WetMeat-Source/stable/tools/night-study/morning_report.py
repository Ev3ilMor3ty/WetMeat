"""Read-only overnight scoreboard and audit report. GPL-3.0-or-later."""
import argparse
import datetime as dt
import fcntl
import json
import os
import re
import time
from pathlib import Path

import chess.pgn

from journal_replay import reconstruct
from summarize_study import summarize
from verify_records import verify_audit, verify_game


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(value)
    temporary.replace(path)


def previous_study(root):
    versions = {}
    games = 0
    for phase in ('training', 'validation'):
        for path in sorted((root / phase).glob('game-*.json')):
            raw = path.read_bytes()
            recorded = json.loads(raw)
            with path.with_suffix('.pgn').open() as stream:
                game = chess.pgn.read_game(stream)
            moves = verify_game(recorded, game)
            audit_path = root / (phase + '-audit') / path.name
            audit = json.loads(audit_path.read_text())
            rows = verify_audit(audit, raw, recorded, moves)
            if audit['status'] != 'completed':
                raise ValueError('Historical audit is no longer complete')
            version = recorded.get('variant', 'baseline')
            statistics = versions.setdefault(version, {'binary_sha256': recorded['tested_binary_sha256'],
                'moves': 0, 'mistakes': 0, 'blunders': 0, 'shallow_judge_moves': 0,
                'wins': 0, 'draws': 0, 'losses': 0})
            if statistics['binary_sha256'] != recorded['tested_binary_sha256']:
                raise ValueError('Historical version identity differs')
            statistics['moves'] += len(rows)
            statistics['mistakes'] += sum(row['category'] == 'mistake' for row in rows)
            statistics['blunders'] += sum(row['category'] == 'blunder' for row in rows)
            statistics['shallow_judge_moves'] += sum(row.get('oracle_depth_below_played', False) for row in rows)
            points = recorded['tested_points']
            field = 'wins' if points == 1 else 'draws' if points == .5 else 'losses' if points == 0 else None
            if field is None:
                raise ValueError('Historical game has no completed result')
            statistics[field] += 1
            games += 1
    if games != 6 or sum(version['moves'] for version in versions.values()) != 247:
        raise ValueError('Historical six-game247-move coverage differs')
    return {'games': games, 'by_version': versions, 'total_checked_moves': 247,
            'mistakes': sum(version['mistakes'] for version in versions.values()),
            'blunders': sum(version['blunders'] for version in versions.values()),
            'report': str(root / 'REPORT.md'),
            'limitations': 'The 247 moves cover 155 stable moves and 92 earlier timing-candidate moves. These finite results do not transfer to a new candidate.'}


def totals(study):
    versions = {}
    fields = ('wins', 'draws', 'losses', 'unfinished', 'tested_moves', 'checked_moves',
              'mistakes_detected', 'blunders_detected', 'shallow_judge_moves')
    for phases in study['by_phase_and_variant'].values():
        for version, stats in phases.items():
            combined = versions.setdefault(version, {field: 0 for field in fields})
            for field in fields:
                combined[field] += stats[field]
    for stats in versions.values():
        complete = stats['tested_moves'] > 0 and stats['checked_moves'] == stats['tested_moves']
        stats['audit_complete_for_completed_games'] = complete
        stats['wins_minus_losses'] = stats['wins'] - stats['losses']
        stats['more_wins_than_losses_observed'] = stats['wins'] > stats['losses']
        stats['zero_detected_errors_in_at_least247_moves'] = (
            complete and stats['checked_moves'] >= 247 and stats['mistakes_detected'] == stats['blunders_detected'] == 0)
    return versions


def snapshot(previous, original, independent, cutoff_path):
    current = summarize(original)
    historical = previous_study(previous)
    rewrite = summarize(independent)
    live = []
    for path in sorted(original.glob('pair-*/live/game-*.jsonl')):
        if not re.fullmatch(r'game-\d+', path.stem):
            continue
        if (path.parent.parent / path.with_suffix('.json').name).exists():
            continue
        game, details = reconstruct(path)
        live.append(details)
    state_path = original / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    cutoff = json.loads(cutoff_path.read_text())
    cutoff_watch_path = cutoff_path.with_name('cutoff-watch.json')
    watcher = json.loads(cutoff_watch_path.read_text()) if cutoff_watch_path.exists() else {}
    combined = totals(current)
    stable = dict(historical['by_version']['baseline'])
    for game in current['games']:
        if game['variant'] == 'baseline' and game['tested_binary_sha256'] != stable['binary_sha256']:
            raise ValueError('New baseline does not match prior stable release')
    baseline = combined.get('baseline', {})
    stable['moves'] += baseline.get('checked_moves', 0)
    stable['mistakes'] += baseline.get('mistakes_detected', 0)
    stable['blunders'] += baseline.get('blunders_detected', 0)
    stable['new_games_audit_complete'] = baseline.get('audit_complete_for_completed_games', False)
    return {'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'cutoff': cutoff,
            'cutoff_watch_status': watcher.get('status'), 'original_runner_status': state.get('status'),
            'original_current': current, 'original_current_totals': combined,
            'verified_previous_study': historical, 'same_stable_cumulative_audited_moves': stable,
            'original_unscored_journal_snapshots': live, 'separate_independent_pilot': rewrite,
            'adopted_release': 'WetMeat 1.0 stable; draw-aversion 16 remains experimental',
            'limitations': ['No new candidate inherits the 247-move result of different binaries.',
                           'Only completed games count. Live/interrupted journals are diagnostic snapshots.',
                           'Finite Stockfish-family judging, with 50/200 cp thresholds, is not proof of perfect play.',
                           'Prior prospective draw claims and new reached-condition rules differ; both current variants use identical rules.',
                           'Training and heldout scores are separate. A small score lead cannot establish strength superiority.',
                           'No Elo estimate or automatic adoption. Account quota/reset status is unknown.']}


def markdown(report):
    old = report['verified_previous_study']
    lines = ['# Original WetMeat overnight results', '',
             f"Snapshot: {report['created_utc']}. Cutoff: {report['cutoff']['local']} Europe/Berlin.", '',
             f"Current phase: {report['original_runner_status']}. {report['adopted_release']}.", '',
             'Only finished games count below. Training and heldout results stay separate.', '',
             '| Version | Phase | Wins | Draws | Losses | Own moves checked | Mistakes detected | Blunders detected |',
             '|---|---|---:|---:|---:|---:|---:|---:|']
    phases = report['original_current']['by_phase_and_variant']
    if not phases:
        lines.append('| No completed original games yet | — | — | — | — | — | — | — |')
    for phase, versions in phases.items():
        for version, stats in versions.items():
            label = 'Stable 1.0' if version == 'baseline' else 'Draw-aversion 16 experiment'
            coverage = f"{stats['checked_moves']}/{stats['tested_moves']}" + (' complete' if stats['audit_complete'] else ' incomplete')
            lines.append(f"| {label} | {phase} | {stats['wins']} | {stats['draws']} | {stats['losses']} | {coverage} | {stats['mistakes_detected']} | {stats['blunders_detected']} |")
    lines.extend(['', 'Partial audit counts are not error rates. Mistakes: 50–199 cp; blunders: 200 cp or more.', '',
                  '## Requested targets', ''])
    for version, stats in report['original_current_totals'].items():
        label = 'Stable original' if version == 'baseline' else 'Current experimental original'
        target = 'yes, observed in this sample' if stats['more_wins_than_losses_observed'] else 'not reached'
        lines.append(f"- {label}: wins minus losses: {stats['wins_minus_losses']}; more wins than losses: {target}. This does not prove superiority.")
    if not report['original_current_totals']:
        lines.append('- More wins than losses: no completed current original results yet.')
    stable = report['same_stable_cumulative_audited_moves']
    lines.extend([f"- Same stable binary: {stable['moves']} audited moves across prior/current studies; {stable['mistakes']} detected mistakes, {stable['blunders']} detected blunders.",
                  '- Current draw-aversion candidate: its own audit coverage is required; it cannot inherit old results.', '',
                  '## Preserved 247-move study', '',
                  f"All {old['total_checked_moves']} old WetMeat moves were checked: {old['mistakes']} detected mistakes, {old['blunders']} detected blunders. Six 10+5 games all drew.", '',
                  'The 247 moves comprise 155 stable 1.0 moves and 92 moves from the earlier timing candidate. The earlier candidate was not adopted. '
                  'The judge reached a lower completed depth than the original search on 130 moves, despite larger node budgets. '
                  'This is a finite study, not a perfect-play certificate.', '',
                  f"[Full earlier report]({old['report']})", '', '## Live or interrupted games', ''])
    live = report['original_unscored_journal_snapshots']
    if not live:
        lines.append('No unscored original journal snapshots at this snapshot time.')
    for game in live:
        lines.append(f"- {Path(game['source']).parent.parent.name}/{Path(game['source']).name}: {game['variant']}, {game['phase']}, {game['played_moves']} recorded nonbook plies; excluded from scores.")
    lines.extend(['', '## Separate independent rewrite', '',
                  'The rewrite remains separate from original WetMeat. Its four 10+5 games were all losses; its audit is intentionally paused at checkpoints. '
                  'Its partial results are not original-engine error rates.', '',
                  '## Reproducibility and limits', '',
                  'Current games use actual 600+5 clocks, one thread and 128 MB hash per engine, full-strength Stockfish 19, '
                  '30 ms move overhead, no pondering/tablebases, paired colors and rotating CPU assignments. '
                  'No heavy judge/build runs overlap the two clocked games. '
                  'Prior games used 256 MB hash and the earlier valid prospective draw-claim policy. '
                  'Current candidate 16 was frozen before the games. Keep previous releases and all PGNs/audit checkpoints.', '',
                  'Finite model WDL loss is an estimate, not an empirical win rate. Tiny paired scores cannot prove a Stockfish-level advantage.', ''])
    return '\n'.join(lines)


def signature(paths):
    items = []
    for root in paths:
        files = root.rglob('*') if root.is_dir() else [root]
        for path in files:
            if path.is_file() and path.suffix in ('.json', '.jsonl', '.pgn'):
                stat = path.stat()
                items.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(items))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--previous', type=Path, required=True)
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--independent', type=Path, required=True)
    p.add_argument('--cutoff', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--watch', action='store_true')
    args = p.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    lock = args.output.with_suffix('.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('A report writer already owns this output')
    cutoff = json.loads(args.cutoff.read_text())
    deadline = dt.datetime.fromisoformat(cutoff['utc']).timestamp()
    if args.watch and time.time() >= deadline:
        raise SystemExit('Cutoff reached; no new reporting watcher started')
    last = None
    while True:
        current = signature([args.previous, args.original, args.independent, args.cutoff,
                             args.cutoff.with_name('cutoff-watch.json')])
        if current != last:
            try:
                report = snapshot(args.previous, args.original, args.independent, args.cutoff)
                write(args.output.with_suffix('.json'), json.dumps(report, indent=2) + '\n')
                write(args.output.with_suffix('.md'), markdown(report))
                last = current
                print(json.dumps({'status': 'report_saved', 'pid': os.getpid(),
                                  'created_utc': report['created_utc'],
                                  'original_totals': report['original_current_totals']}), flush=True)
            except (ValueError, OSError, KeyError, AssertionError) as error:
                if not args.watch:
                    raise
                print(json.dumps({'status': 'report_not_updated', 'error': str(error),
                                  'note': 'Previous verified report retained; retry on next poll.'}), flush=True)
        if not args.watch or time.time() >= deadline:
            return
        time.sleep(min(60, max(0, deadline - time.time())))


if __name__ == '__main__':
    main()
