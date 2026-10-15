"""Combine matching frozen overnight stages without duplicating games. GPL-3.0-or-later."""
import argparse
import datetime as dt
import fcntl
import json
import re
import time
from pathlib import Path

import morning_report as previous
from journal_replay import reconstruct
from summarize_study import summarize


def merge_studies(studies):
    phases, games, comparisons, identities, seen = {}, [], [], {}, set()
    additive = ('wins', 'draws', 'losses', 'unfinished', 'tested_moves', 'checked_moves',
                'partial_game_moves', 'mistakes_detected', 'blunders_detected', 'shallow_judge_moves',
                'wdl_loss_positions', 'wdl_expectation_loss_sum')
    for study in studies:
        for game in study['games']:
            path = Path(game['file']).resolve()
            if path in seen:
                raise ValueError('Duplicate game in combined studies')
            seen.add(path)
            recorded = json.loads(path.read_text())
            identity = {key: recorded.get(key) for key in
                        ('tested_binary_sha256', 'tested_options', 'opponent_binary_sha256',
                         'draw_rule', 'base_seconds', 'increment_seconds', 'hash_mb_each', 'threads_each')}
            variant = game['variant']
            if variant in identities and identities[variant] != identity:
                raise ValueError('Different frozen conditions for ' + variant)
            identities[variant] = identity
            games.append({**game, 'study': study['study']})
        for phase, versions in study['by_phase_and_variant'].items():
            for variant, stats in versions.items():
                target = phases.setdefault(phase, {}).setdefault(variant, {**{key: 0 for key in additive}, 'terminations': {}})
                for key in additive:
                    target[key] += stats[key]
                for name, count in stats['terminations'].items():
                    target['terminations'][name] = target['terminations'].get(name, 0) + count
        comparisons.extend({**comparison, 'study': study['study']} for comparison in study['paired_opening_comparisons'])
    for versions in phases.values():
        for stats in versions.values():
            count = stats['wins'] + stats['draws'] + stats['losses']
            complete = stats['tested_moves'] > 0 and stats['tested_moves'] == stats['checked_moves']
            stats.update(audit_complete=complete,
                         score_fraction=(stats['wins'] + .5 * stats['draws']) / count if count else None,
                         mistake_rate=stats['mistakes_detected'] / stats['tested_moves'] if complete else None,
                         blunder_rate=stats['blunders_detected'] / stats['tested_moves'] if complete else None,
                         mean_judge_wdl_expectation_loss=(stats['wdl_expectation_loss_sum'] / stats['wdl_loss_positions']
                                                         if complete and stats['wdl_loss_positions'] else None))
    return {'study': 'matching original-engine stages', 'study_roots': [study['study'] for study in studies],
            'by_phase_and_variant': phases, 'paired_opening_comparisons': comparisons, 'games': games}


def snapshot(args):
    report = previous.snapshot(args.previous, args.original, args.independent, args.cutoff)
    additional = summarize(args.additional)
    initial = report['original_current']
    report['original_current'] = merge_studies([initial, additional])
    report['original_current_totals'] = previous.totals(report['original_current'])
    report['test_stages'] = [{'study': item['study'], 'by_phase_and_variant': item['by_phase_and_variant'],
                            'scored_games': len([game for game in item['games'] if game['points'] is not None])}
                           for item in (initial, additional)]
    stable = dict(report['verified_previous_study']['by_version']['baseline'])
    for game in report['original_current']['games']:
        if game['variant'] == 'baseline' and game['tested_binary_sha256'] != stable['binary_sha256']:
            raise ValueError('Combined baseline differs from the preserved stable release')
    baseline = report['original_current_totals'].get('baseline', {})
    stable['moves'] += baseline.get('checked_moves', 0)
    stable['mistakes'] += baseline.get('mistakes_detected', 0)
    stable['blunders'] += baseline.get('blunders_detected', 0)
    stable['new_games_audit_complete'] = baseline.get('audit_complete_for_completed_games', False)
    report['same_stable_cumulative_audited_moves'] = stable
    for path in sorted(args.additional.glob('pair-*/live/game-*.jsonl')):
        if re.fullmatch(r'game-\d+', path.stem) and not (path.parent.parent / path.with_suffix('.json').name).exists():
            _, details = reconstruct(path)
            report['original_unscored_journal_snapshots'].append(details)
    state = args.additional / 'state.json'
    if state.exists():
        report['original_runner_status'] = json.loads(state.read_text())['status']
    handoff = args.cutoff.parent / 'pipeline-handoff.json'
    report['pipeline_handoff'] = json.loads(handoff.read_text()) if handoff.exists() else None
    report['created_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('previous', 'original', 'additional', 'independent', 'cutoff', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--watch', action='store_true')
    args = p.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    lock = args.output.with_suffix('.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('A report writer already owns this output')
    deadline = dt.datetime.fromisoformat(json.loads(args.cutoff.read_text())['utc']).timestamp()
    if args.watch and time.time() >= deadline:
        raise SystemExit('Cutoff reached; no watcher started')
    last = None
    while True:
        current = previous.signature([args.previous, args.original, args.additional, args.independent,
                                      args.cutoff, args.cutoff.with_name('cutoff-watch.json'),
                                      args.cutoff.with_name('pipeline-handoff.json')])
        if current != last:
            try:
                report = snapshot(args)
                previous.write(args.output.with_suffix('.json'), json.dumps(report, indent=2) + '\n')
                text = previous.markdown(report) + '\n## Test stages\n\n'
                text += 'Initial training games and the later CPU-queue stage keep their frozen inputs and original resource assignments. '
                text += 'Only matching binaries, clocks, options and draw rules are combined; each played game is counted once. '
                text += 'Audits remain between completed game batches. This scheduling change is not an engine-strength improvement.\n'
                previous.write(args.output.with_suffix('.md'), text)
                last = current
                print(json.dumps({'status': 'report_saved', 'created_utc': report['created_utc'],
                                  'original_totals': report['original_current_totals']}), flush=True)
            except (ValueError, OSError, KeyError, AssertionError) as error:
                if not args.watch:
                    raise
                print(json.dumps({'status': 'report_not_updated', 'error': str(error),
                                  'note': 'Previous verified report retained.'}), flush=True)
        if not args.watch or time.time() >= deadline:
            return
        time.sleep(min(60, max(0, deadline - time.time())))


if __name__ == '__main__':
    main()
