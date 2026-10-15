"""Correct cumulative stable statistics without changing frozen evidence. GPL-3.0-or-later."""
import argparse
import datetime as dt
import fcntl
import json
import time
from pathlib import Path

import combined_report as frozen
import morning_report as helpers


def snapshot(args):
    report = frozen.snapshot(args)
    stable = dict(report['verified_previous_study']['by_version']['baseline'])
    current = report['original_current_totals'].get('baseline', {})
    for historical, live in (
        ('moves', 'checked_moves'),
        ('mistakes', 'mistakes_detected'),
        ('blunders', 'blunders_detected'),
        ('shallow_judge_moves', 'shallow_judge_moves'),
        ('wins', 'wins'), ('draws', 'draws'), ('losses', 'losses'),
    ):
        stable[historical] += current.get(live, 0)
    complete = not current.get('tested_moves', 0) or current['audit_complete_for_completed_games']
    stable['new_games_audit_complete'] = complete
    stable['sample_audit_complete'] = complete
    stable['sample_mistake_rate'] = stable['mistakes'] / stable['moves'] if complete else None
    stable['sample_blunder_rate'] = stable['blunders'] / stable['moves'] if complete else None
    stable['zero_detected_errors_in_at_least247_moves'] = (
        complete and stable['moves'] >= 247 and stable['mistakes'] == stable['blunders'] == 0
    )
    stable['scope_note'] = (
        'Same frozen stable binary only; earlier timing and current draw-aversion candidates excluded. '
        'These are descriptive totals over different hash/draw-policy studies, not a controlled gain estimate. '
        'Cumulative error rates are unavailable while any completed current stable game lacks full audit coverage.'
    )
    report['same_stable_cumulative_audited_moves'] = stable
    report['reporter_schema'] = 2
    return report


def markdown(report):
    text = helpers.markdown(report)
    text += '\n## Test stages\n\n'
    text += ('Initial training games and the later CPU-queue stage retain their frozen inputs and '
             'original resource assignments. Only matching binaries, clocks, options and draw rules '
             'are combined; each played game is counted once. Audits remain between completed game '
             'batches. The scheduling change is not an engine-strength improvement.\n')
    stable = report['same_stable_cumulative_audited_moves']
    text += '\n## Same stable binary across studies\n\n'
    text += (f"Completed games: {stable['wins']} wins, {stable['draws']} draws, {stable['losses']} losses. "
             f"Audited own moves: {stable['moves']}; detected mistakes: {stable['mistakes']}; "
             f"detected blunders: {stable['blunders']}. The judge reached a shallower completed depth "
             f"than the original search on {stable['shallow_judge_moves']} of these audited moves.\n\n")
    if stable['zero_detected_errors_in_at_least247_moves']:
        text += ('This same-binary sample exceeds 247 fully audited moves with zero detected errors. '
                 'It is a finite result, not a certificate of perfect play or future performance.\n')
    elif not stable['sample_audit_complete']:
        text += 'Current stable-game audit coverage is incomplete; cumulative error rates are unavailable.\n'
    text += '\n' + stable['scope_note'] + '\n'
    return text


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('previous', 'original', 'additional', 'independent', 'cutoff', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--watch', action='store_true')
    args = p.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    lock = args.output.with_suffix('.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('A report writer already owns this output')
    deadline = dt.datetime.fromisoformat(json.loads(args.cutoff.read_text())['utc']).timestamp()
    if args.watch and time.time() >= deadline:
        raise SystemExit('Cutoff reached; no watcher started')
    last = None
    while True:
        current = helpers.signature([args.previous, args.original, args.additional, args.independent,
                                     args.cutoff, args.cutoff.with_name('cutoff-watch.json'),
                                     args.cutoff.with_name('pipeline-handoff.json')])
        if current != last:
            try:
                report = snapshot(args)
                helpers.write(args.output.with_suffix('.json'), json.dumps(report, indent=2) + '\n')
                helpers.write(args.output.with_suffix('.md'), markdown(report))
                last = current
                print(json.dumps({'status': 'report_saved', 'created_utc': report['created_utc'],
                                  'reporter_schema': 2, 'original_totals': report['original_current_totals']}), flush=True)
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
