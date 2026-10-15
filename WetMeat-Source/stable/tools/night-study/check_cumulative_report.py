"""Reproduce actual cumulative-report omissions; verify partial-sample safety. GPL-3.0-or-later."""
import argparse
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import combined_report as old
import combined_report_v2 as new


def direct_stable_counts(args):
    totals = {key: 0 for key in ('moves', 'mistakes', 'blunders', 'shallow_judge_moves', 'wins', 'draws', 'losses')}
    paths = [(path, args.previous / (phase + '-audit') / path.name)
             for phase in ('training', 'validation')
             for path in sorted((args.previous / phase).glob('game-*.json'))]
    paths += [(path, path.parent / 'audit' / path.name)
              for root in (args.original, args.additional)
              for path in sorted(root.glob('pair-*/game-*.json'))]
    stable_hash = None
    for path, audit in paths:
        game = json.loads(path.read_text())
        if game.get('variant', 'baseline') != 'baseline' or game['tested_points'] is None:
            continue
        if stable_hash is None:
            stable_hash = game['tested_binary_sha256']
        assert game['tested_binary_sha256'] == stable_hash
        points = game['tested_points']
        totals['wins' if points == 1 else 'draws' if points == .5 else 'losses'] += 1
        if audit.exists():
            rows = json.loads(audit.read_text())['moves']
            totals['moves'] += len(rows)
            totals['mistakes'] += sum(row['category'] == 'mistake' for row in rows)
            totals['blunders'] += sum(row['category'] == 'blunder' for row in rows)
            totals['shallow_judge_moves'] += sum(row.get('oracle_depth_below_played', False) for row in rows)
    return totals


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('previous', 'original', 'additional', 'independent', 'cutoff', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    args = p.parse_args()
    cases = []
    legacy = old.snapshot(args)
    expected = direct_stable_counts(args)
    observed = legacy['same_stable_cumulative_audited_moves']
    omissions = {key: {'reported': observed[key], 'actual': value}
                 for key, value in expected.items() if observed[key] != value}
    assert 'draws' in omissions and 'shallow_judge_moves' in omissions, omissions
    cases.append('actual frozen games reproduce stale cumulative draws and shallow-depth counts')
    updated = new.snapshot(args)
    actual = updated['same_stable_cumulative_audited_moves']
    assert all(actual[key] == value for key, value in expected.items())
    assert actual['zero_detected_errors_in_at_least247_moves'] and actual['sample_mistake_rate'] == 0
    assert actual['sample_blunder_rate'] == 0 and actual['moves'] == 258
    assert '136 of these audited moves' in new.markdown(updated)
    cases.append('all cumulative statistics match raw stable-only evidence; other candidates excluded')
    incomplete = copy.deepcopy(legacy)
    incomplete['original_current_totals']['baseline'].update(
        tested_moves=200, checked_moves=103, audit_complete_for_completed_games=False)
    with patch.object(new.frozen, 'snapshot', return_value=incomplete):
        partial = new.snapshot(args)['same_stable_cumulative_audited_moves']
    assert partial['moves'] == 258 and not partial['zero_detected_errors_in_at_least247_moves']
    assert partial['sample_mistake_rate'] is partial['sample_blunder_rate'] is None
    cases.append('incomplete current audits suppress cumulative rates and full-sample milestone')
    failed = copy.deepcopy(legacy)
    failed['original_current_totals']['baseline']['mistakes_detected'] = 1
    with patch.object(new.frozen, 'snapshot', return_value=failed):
        bad = new.snapshot(args)['same_stable_cumulative_audited_moves']
    assert bad['moves'] == 258 and bad['mistakes'] == 1 and not bad['zero_detected_errors_in_at_least247_moves']
    cases.append('a detected error prevents the zero-error milestone')
    report = {'status': 'passed', 'cases': cases, 'reproduced_legacy_omissions': omissions,
              'raw_stable_counts': expected, 'engine_searches': 0,
              'limitations': 'Reporting verification only; no engine strength gain.'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
