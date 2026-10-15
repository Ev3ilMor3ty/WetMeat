#!/usr/bin/env python3
"""Read training game/audit evidence without engine searches. GPL-3.0-or-later.

This tool is separate from the frozen running queue. It does not select parameters,
change any game input, evaluate alternatives, or inspect heldout move histories.
"""
import argparse
import collections
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import sys

import chess
import chess.pgn

sys.path.insert(0, '/workspace/aurora-stockfish/tools/night-study')
from verify_records import require, verify_audit, verify_game


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def repetition_choices(record):
    board = chess.Board()
    for uci in record['opening'].split():
        board.push_uci(uci)
    repeated, terminal = [], []
    for row in record['moves']:
        move = chess.Move.from_uci(row['uci'])
        if row['tested']:
            board.push(move)
            second, third = board.is_repetition(2), board.is_repetition(3)
            board.pop()
            if second:
                repeated.append(row['ply'])
            if third:
                alternatives = []
                for other in list(board.legal_moves):
                    if other == move:
                        continue
                    san = board.san(other)
                    board.push(other)
                    if not board.is_repetition(3):
                        alternatives.append({'uci': other.uci(), 'san': san})
                    board.pop()
                terminal.append({'ply': row['ply'], 'chosen': move.uci(),
                                 'legal_alternatives_without_immediate_third_occurrence': alternatives,
                                 'alternative_values_unknown': True})
        board.push(move)
    return repeated, terminal


def review(plan):
    games, totals = [], {}
    for context in plan['study_contexts']:
        if not context.get('selectable_training'):
            continue
        require(context['phase'] == 'training', 'Review must not consume heldout histories')
        bias = context['bias']
        for path in sorted(Path(context['path']).glob('pair-*/game-*.json')):
            if not path.with_suffix('.pgn').exists():
                continue
            raw, pgn_raw = path.read_bytes(), path.with_suffix('.pgn').read_bytes()
            record = json.loads(raw)
            variant = record['variant']
            require(variant in ('baseline', 'candidate'), 'Unknown engine role')
            options = {'Draw Aversion': bias} if variant == 'candidate' else {}
            binary = plan['candidate_binary_sha256'] if variant == 'candidate' else plan['stable_binary_sha256']
            require(record['tested_options'] == options and record['tested_binary_sha256'] == binary,
                    'Engine configuration differs from the frozen plan')
            require(record['phase'] == 'training', 'Heldout game in training directory')
            pair = int(path.parent.name.removeprefix('pair-'))
            require(record['opening'] == context['openings'][pair - 1], 'Training opening differs')
            require(record['cpu'] == int((variant == 'baseline') == (record['tested_color'] == 'black')),
                    'Frozen CPU rotation differs')
            for key, expected in plan['game_settings'].items():
                require(record.get(key) == expected, 'Game resources or policy differ: ' + key)
            for side in ('tested_uci_settings', 'opponent_uci_settings'):
                require(all(record[side].get(k) == v for k, v in plan['common_uci_settings'].items()),
                        'Applied strength or resources differ')
            tested = verify_game(record, chess.pgn.read_game(io.StringIO(pgn_raw.decode())))
            if record['tested_points'] is None:
                continue
            audit_path = path.parent / 'audit' / path.name
            audit_raw, rows, complete = None, [], False
            if audit_path.exists():
                audit_raw = audit_path.read_bytes()
                audit = json.loads(audit_raw)
                require(audit['settings'] == plan['audit_settings'], 'Judge method or budget differs')
                rows = verify_audit(audit, raw, record, tested)
                require(len(rows) == len(audit['moves']), 'Audit includes opponent moves')
                complete = audit['status'] == 'completed' and len(rows) == len(tested)
            repeated, terminal = repetition_choices(record)
            moves = list(tested.values())
            categories = collections.Counter(row['category'] for row in rows)
            key = 'baseline' if variant == 'baseline' else f'draw-aversion-{bias}'
            outcome = {1: 'wins', .5: 'draws', 0: 'losses'}[record['tested_points']]
            total = totals.setdefault(key, {'wins': 0, 'draws': 0, 'losses': 0,
                                           'checked_moves': 0, 'own_moves': 0,
                                           'mistakes': 0, 'blunders': 0, 'audit_complete': True})
            total[outcome] += 1
            total['checked_moves'] += len(rows)
            total['own_moves'] += len(moves)
            total['mistakes'] += categories['mistake']
            total['blunders'] += categories['blunder']
            total['audit_complete'] &= complete
            games.append({'file': str(path), 'game_sha256': digest(raw), 'pgn_sha256': digest(pgn_raw),
                          'configuration': key, 'binary_sha256': binary, 'options': options,
                          'phase': 'training', 'opening': record['opening'], 'color': record['tested_color'],
                          'result': record['result'], 'termination': record['termination'],
                          'own_moves': len(moves), 'checked_moves': len(rows), 'audit_complete': complete,
                          'audit_snapshot_sha256': digest(audit_raw) if audit_raw else None,
                          'mistakes': categories['mistake'], 'blunders': categories['blunder'],
                          'largest_checked_loss_cp': max((row['loss_cp'] for row in rows), default=None),
                          'shallower_judge_moves': sum(row.get('oracle_depth_below_played', False) for row in rows),
                          'minimum_clock_after_s': min((m['clock_after_s'] for m in moves), default=None),
                          'final_own_clock_s': record['final_clocks_s'][str(record['tested_color'] == 'white')],
                          'total_own_elapsed_s': sum(m['elapsed_s'] for m in moves),
                          'total_own_nodes': sum(m['nodes'] or 0 for m in moves),
                          'tested_moves_repeating_a_position': repeated,
                          'tested_third_occurrence_choices': terminal,
                          'full_uci_history': record['opening'].split() + [m['uci'] for m in record['moves']]})
    for total in totals.values():
        for name in ('mistake', 'blunder'):
            total[name + '_rate'] = total[name + 's'] / total['own_moves'] if total['audit_complete'] and total['own_moves'] else None
    return {'snapshot_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'engine_searches': 0,
            'scope': 'Fresh selectable training games only; no heldout move histories used',
            'frozen_parameter_selection_unchanged': True, 'totals': totals, 'games': games,
            'limits': 'Legal alternatives to repetition are not necessarily sound or winning. Clocks and nodes describe these games, not playing strength. Partial audits give no full error rate. Finite common-depth judging may miss errors, especially at shallower depth. No tuning, promotion, superiority or Elo conclusion.'}


def markdown(data):
    lines = ['# Original WetMeat: fresh training evidence', '', 'Snapshot: ' + data['snapshot_utc'], '',
             'Only completed training games are included. Stockfish19 used full skill, no Elo limit, '
             'and the same actual 10+5 clock, one thread and 128 MB hash.', '',
             '| Configuration | Color | Result | End condition | Own moves checked/total | Lowest clock after move |',
             '|---|---|---|---|---|---|']
    for game in data['games']:
        lines.append(f"| {game['configuration']} | {game['color']} | {game['result']} | {game['termination']} | "
                     f"{game['checked_moves']}/{game['own_moves']} | {game['minimum_clock_after_s']:.2f} s |")
    lines += ['', 'No training or validation input has been changed. Setting32/64 remain experimental. '
              'The predeclared selection rule still applies after both training openings and their audits finish.', '', data['limits'], '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = review(json.loads(args.plan.read_text()))
    args.output.mkdir(parents=True, exist_ok=True)
    for name, content in [('training-review.json', json.dumps(data, indent=2) + '\n'),
                          ('training-review.md', markdown(data))]:
        target = args.output / name
        temporary = target.with_suffix(target.suffix + '.tmp')
        temporary.write_text(content)
        temporary.replace(target)
    print(json.dumps({'output': str(args.output), 'games': len(data['games']), 'totals': data['totals'], 'engine_searches': 0}))
