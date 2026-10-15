"""Fault injection for report evidence; no engine searches. GPL-3.0-or-later."""
import copy
import hashlib
import json
import tempfile
from pathlib import Path

import chess
import chess.pgn

from summarize_study import summarize


def fixture(root, number, variant, color):
    directory = root / 'pair-001'
    directory.mkdir(exist_ok=True)
    path = directory / f'game-{number:03d}.json'
    game = chess.pgn.Game()
    game.headers.update(White='fixture-white', Black='fixture-black', TimeControl='600+5',
                        StudyPhase='heldout', Result='0-1', Termination='CHECKMATE')
    options = {'Draw Aversion': 16} if variant == 'candidate' else {}
    game.headers['TestedOptions'] = json.dumps(options, sort_keys=True)
    board = game.board()
    node = game
    moves = []
    for text in ('f2f3', 'e7e5', 'g2g4', 'd8h4'):
        move = chess.Move.from_uci(text)
        active = 'white' if board.turn else 'black'
        moves.append({'ply': board.ply() + 1, 'color': active, 'tested': color == active,
                      'engine': game.headers['White' if board.turn else 'Black'],
                      'fen_before': board.fen(), 'uci': text, 'san': board.san(move),
                      'clock_before_s': 600, 'elapsed_s': 5, 'clock_after_s': 600,
                      'nodes': 1200000, 'depth': 8})
        board.push(move)
        node = node.add_variation(move)
        node.set_clock(600)
        node.set_emt(5)
    report = {'variant': variant, 'phase': 'heldout', 'tested_color': color, 'opening': '',
              'result': '0-1', 'termination': 'CHECKMATE', 'tested_points': int(color == 'black'),
              'base_seconds': 600, 'increment_seconds': 5, 'plies': 4, 'moves': moves,
              'final_fen': board.fen(), 'final_clocks_s': {'True': 600, 'False': 600},
              'tested_binary_sha256': variant, 'opponent_binary_sha256': 'fixture-judge',
              'tested_options': options, 'move_overhead_ms_each': 30,
              'tested_uci_settings': {'Threads': 1, 'Hash': 128, 'Move Overhead': 30, **options},
              'opponent_uci_settings': {'Threads': 1, 'Hash': 128, 'Move Overhead': 30,
                                        'Skill Level': 20, 'UCI_LimitStrength': False, 'SyzygyPath': ''},
              'threads_each': 1, 'hash_mb_each': 128, 'cpu': number % 2}
    raw = json.dumps(report).encode()
    path.write_bytes(raw)
    path.with_suffix('.pgn').write_text(str(game) + '\n\n')
    rows = []
    for original in moves:
        if not original['tested']:
            continue
        evaluation = {'value': 0, 'depth': 10, 'nodes': 2400000, 'pv': [original['uci']]}
        rows.append({'ply': original['ply'], 'fen': original['fen_before'],
                     'played': original['uci'], 'tested': True, 'played_nodes': 1200000,
                     'played_depth': 8, 'audit_budget_nodes_per_search': 2400000,
                     'initial_loss_cp': 0, 'loss_cp': 0, 'category': 'acceptable',
                     'best': original['uci'], 'best_evaluation': evaluation,
                     'played_evaluation': copy.deepcopy(evaluation), 'refined': False,
                     'oracle_depth_below_played': False})
    audit = {'source_sha256': hashlib.sha256(raw).hexdigest(), 'status': 'completed',
             'settings': {'judge_sha': 'fixture-judge', 'min_nodes': 1000000, 'multiplier': 2,
                          'refine_multiplier': 4, 'mistake_cp': 50, 'blunder_cp': 200,
                          'method': 'completed-common-depth-multipv2-v1'}, 'moves': rows}
    destination = directory / 'audit' / path.name
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(audit))
    return path, report, destination, audit


def main():
    cases = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        files = [fixture(root, index + 1, variant, color)
                 for index, (variant, color) in enumerate((('baseline', 'white'), ('candidate', 'white'),
                                                         ('baseline', 'black'), ('candidate', 'black')))]
        (root / 'state.json').write_text(json.dumps({'fingerprints': {
            'engine': 'baseline', 'candidate': 'candidate', 'opponent': 'fixture-judge',
            'candidate_draw_aversion': 16}}))
        report = summarize(root)
        assert len(report['paired_opening_comparisons']) == 1
        assert report['paired_opening_comparisons'][0]['candidate_minus_baseline_points'] == 0
        assert all(stats['audit_complete'] for stats in report['by_phase_and_variant']['heldout'].values())
        cases.append('legal clocked paired fixture with complete coverage')
        path, game, audit_path, audit = files[0]

        def reject(label, mutate, target='audit', fixture_index=0):
            game_path, recorded, audit_destination, audited = files[fixture_index]
            value = copy.deepcopy(audited if target == 'audit' else recorded)
            mutate(value)
            destination = audit_destination if target == 'audit' else game_path
            destination.write_text(json.dumps(value))
            try:
                summarize(root)
            except ValueError:
                cases.append(label)
            else:
                raise AssertionError('Invalid evidence accepted: ' + label)
            finally:
                destination.write_text(json.dumps(audited) if target == 'audit' else json.dumps(recorded))
                # The original JSON fixture bytes exactly match this serialization.

        reject('missing recorded PGN move', lambda v: v['moves'].pop(), 'game')
        reject('duplicate recorded ply', lambda v: v['moves'][1].update(ply=1), 'game')
        reject('incorrect tested-side flag', lambda v: v['moves'][0].update(tested=False), 'game')
        reject('false clock arithmetic', lambda v: v['moves'][0].update(clock_after_s=601), 'game')
        reject('reduced opponent skill', lambda v: v['opponent_uci_settings'].update({'Skill Level': 5}), 'game')
        reject('opponent Elo limiter enabled', lambda v: v['opponent_uci_settings'].update(UCI_LimitStrength=True), 'game')
        reject('unequal applied hash resources', lambda v: v['tested_uci_settings'].update(Hash=256), 'game')
        reject('experiment option not applied', lambda v: v['tested_uci_settings'].pop('Draw Aversion'), 'game', 1)
        reject('wrong frozen engine version', lambda v: v.update(tested_binary_sha256='other'), 'game')
        reject('stale audit input', lambda v: v.update(source_sha256='wrong'))
        reject('unrecognized category', lambda v: v['moves'][0].update(category='perfect'))
        reject('concealed threshold blunder', lambda v: v['moves'][0].update(loss_cp=250))
        reject('duplicate audited ply', lambda v: v['moves'].append(copy.deepcopy(v['moves'][0])))
        reject('missing completed-audit move', lambda v: v['moves'].pop())
        reject('wrong judge binary', lambda v: v['settings'].update(judge_sha='other'))
        reject('insufficient per-move judge budget', lambda v: v['moves'][0].update(audit_budget_nodes_per_search=1000000))
        reject('mismatched comparison depth', lambda v: v['moves'][0]['played_evaluation'].update(depth=9))
        reject('invalid WDL expectation loss', lambda v: v['moves'][0].update(wdl_expectation_loss=float('nan')))
        partial = copy.deepcopy(audit)
        partial.update(status='running', moves=partial['moves'][:1])
        audit_path.write_text(json.dumps(partial))
        stats = summarize(root)['by_phase_and_variant']['heldout']['baseline']
        assert stats['checked_moves'] == 3 and stats['tested_moves'] == 4
        assert not stats['audit_complete'] and stats['mistake_rate'] is None and stats['blunder_rate'] is None
        cases.append('partial audit cannot yield zero-rate claim')
    print(json.dumps({'status': 'passed', 'cases': cases, 'engine_searches': 0}))


if __name__ == '__main__':
    main()
