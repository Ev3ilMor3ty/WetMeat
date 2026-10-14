"""Verify and summarize the completed WetMeat rapid pilot.

SPDX-License-Identifier: GPL-3.0-or-later.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import chess
import chess.pgn


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def verify_game(source, audit_path, opponent_sha):
    record, audit = read(source), read(audit_path)
    with source.with_suffix('.pgn').open() as stream:
        game = chess.pgn.read_game(stream)
        assert stream.read().strip() == ''
    assert game and not game.errors
    assert audit['status'] == 'completed'
    assert audit['scope'] == 'tested-engine-only'
    assert audit['source_sha256'] == digest(source)
    assert audit['judge_sha256'] == opponent_sha == record['opponent_binary_sha256']
    assert record['base_seconds'] == 600 and record['increment_seconds'] == 5
    assert record['threads_each'] == 1 and record['hash_mb_each'] == 256
    assert record['move_overhead_ms_each'] == 30
    assert game.headers['TimeControl'] == '600+5'
    assert game.headers['Result'] == record['result'] != '*'
    assert game.headers['Termination'] == record['termination']
    played = {row['ply']: row for row in record['moves']}
    assert len(played) == len(record['moves'])
    own = {ply for ply, row in played.items() if row['tested']}
    inspected = {row['ply']: row for row in audit['moves']}
    assert len(inspected) == len(audit['moves']) and set(inspected) == own
    clocks = {'white': 600.0, 'black': 600.0}
    board = game.board()
    opening = record['opening'].split()
    assert len(opening) == int(game.headers['OpeningPlies'])
    largest_clock_difference = 0.0
    for node in game.mainline():
        move, ply = node.move, node.ply()
        assert move in board.legal_moves
        if ply <= len(opening):
            assert move.uci() == opening[ply-1] and ply not in played
        else:
            row = played[ply]
            color = 'white' if board.turn else 'black'
            assert row['color'] == color
            assert row['tested'] == (color == record['tested_color'])
            assert row['engine'] == game.headers['White' if board.turn else 'Black']
            assert row['fen_before'] == board.fen()
            assert row['uci'] == move.uci() and row['san'] == board.san(move)
            assert abs(row['clock_before_s'] - clocks[color]) < 1e-8
            assert 0 <= row['elapsed_s'] < clocks[color]
            clocks[color] -= row['elapsed_s']
            clocks[color] += 5
            assert abs(row['clock_after_s'] - clocks[color]) < 1e-8
            assert abs(node.clock() - clocks[color]) <= .0011
            assert abs(node.emt() - row['elapsed_s']) <= .0011
            largest_clock_difference = max(largest_clock_difference, abs(node.clock()-clocks[color]))
            if row['tested']:
                check = inspected[ply]
                assert check['tested'] and check['played'] == move.uci()
                assert check['engine'] == row['engine']
                assert check['fen'] == board.fen()
                assert check['played_nodes'] == row['nodes']
                assert check['played_depth'] == row['depth']
                assert check['audit_budget_nodes_per_search'] >= max(1_000_000, 2*(row['nodes'] or 0))
                assert chess.Move.from_uci(check['best']) in board.legal_moves
                loss = check['loss_cp']
                assert loss >= 0
                assert check['category'] == ('blunder' if loss >= 200 else 'mistake' if loss >= 50 else 'acceptable')
                if check.get('initial_loss_cp', 0) >= 40:
                    assert check['refined']
                    assert check['refined_budget_nodes_per_search'] >= 4*check['audit_budget_nodes_per_search']
                if not check.get('forced_only_move'):
                    assert check['best_evaluation']['depth'] == check['played_evaluation']['depth']
                    assert loss == max(0, check['best_evaluation']['value']-check['played_evaluation']['value'])
        board.push(move)
    assert len(board.move_stack) == record['plies']
    assert len(played) == record['plies']-len(opening)
    assert board.fen() == record['final_fen']
    if record['termination'] == 'TIME_FORFEIT':
        flagging_color = 'white' if board.turn else 'black'
        clocks[flagging_color] = 0.0
        winner = None if board.has_insufficient_material(not board.turn) else not board.turn
        result = '1/2-1/2' if winner is None else '1-0' if winner else '0-1'
        assert result == record['result']
    else:
        outcome = board.outcome(claim_draw=True)
        assert outcome and outcome.result() == record['result']
        assert outcome.termination.name == record['termination']
    assert abs(clocks['white']-record['final_clocks_s']['True']) < 1e-8
    assert abs(clocks['black']-record['final_clocks_s']['False']) < 1e-8
    return record, audit, {'game': str(source), 'legal_plies': record['plies'],
                           'clocked_moves': len(played), 'audited_wetmeat_moves': len(own),
                           'largest_pgn_clock_rounding_s': largest_clock_difference,
                           'source_sha256': digest(source), 'pgn_sha256': digest(source.with_suffix('.pgn'))}


def main():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, default=project/'results/rapid-study')
    parser.add_argument('--stable', type=Path, default=project/'bin/wetmeat-linux-avx512')
    parser.add_argument('--candidate', type=Path, default=project.parent/'wetmeat-experimental/src/wetmeat-safety')
    parser.add_argument('--opponent', type=Path, required=True)
    args = parser.parse_args()
    protocol = read(args.study/'protocol.json')
    frozen = read(args.study/'candidate-frozen.json')
    assert protocol['candidate']['tactical_time_boost_percent'] == frozen['tactical_time_boost'] == 25
    assert frozen['parameters_changed_after_validation'] is False
    candidate_sha, stable_sha, opponent_sha = digest(args.candidate), digest(args.stable), digest(args.opponent)
    assert candidate_sha == frozen['binary_sha256']
    for name, expected in frozen['source_sha256'].items():
        assert digest(args.candidate.parent/name) == expected
    records, checks, rates = [], [], defaultdict(lambda: {'moves':0,'mistakes':0,'blunders':0,'loss_cp_sum':0,'refined_moves':0,'lower_completed_depth_moves':0})
    for stage, expected_count in [('training',2),('validation',4)]:
        paths = sorted((args.study/stage).glob('game-*.json'))
        assert len(paths) == expected_count
        for path in paths:
            record, audit, check = verify_game(path, args.study/(stage+'-audit')/path.name, opponent_sha)
            variant = record.get('variant','baseline')
            assert record['tested_binary_sha256'] == (candidate_sha if variant == 'candidate' else stable_sha)
            records.append((stage,record))
            checks.append(check)
            for scope in [variant, stage+'/'+variant]:
                stat = rates[scope]
                for row in audit['moves']:
                    stat['moves'] += 1
                    stat['mistakes'] += row['category']=='mistake'
                    stat['blunders'] += row['category']=='blunder'
                    stat['loss_cp_sum'] += row['loss_cp']
                    stat['refined_moves'] += row['refined']
                    stat['lower_completed_depth_moves'] += row.get('oracle_depth_below_played',False)
    for stat in rates.values():
        stat['mistake_rate'] = stat['mistakes']/stat['moves']
        stat['blunder_rate'] = stat['blunders']/stat['moves']
        stat['average_centipawn_loss'] = stat['loss_cp_sum']/stat['moves']
    heldout = [record for stage,record in records if stage == 'validation']
    assert len({row['opening'] for row in heldout}) == 1
    assert {row['opening'] for stage,row in records if stage == 'training'}.isdisjoint({row['opening'] for row in heldout})
    match = read(args.study/'validation/summary.json')['by_variant']
    for variant in ('baseline','candidate'):
        subset = [row for row in heldout if row['variant'] == variant]
        assert len(subset) == 2 and {row['tested_color'] for row in subset} == {'white','black'}
        assert {row['cpu'] for row in subset} == {0,1}
        stat = match[variant]['statistics']
        assert stat['wins'] == sum(row['tested_points']==1 for row in subset)
        assert stat['draws'] == sum(row['tested_points']==.5 for row in subset)
        assert stat['losses'] == sum(row['tested_points']==0 for row in subset)
        assert stat['score'] == sum(row['tested_points'] for row in subset)/2
    baseline, candidate = match['baseline']['statistics'], match['candidate']['statistics']
    improved = candidate['score'] > baseline['score']
    wins_more = candidate['wins'] > candidate['losses']
    baseline_wins_more = baseline['wins'] > baseline['losses']
    if improved and wins_more:
        headline = 'The candidate won more than it lost in this pilot; broader superiority remains unproven.'
    elif improved:
        headline = 'The candidate scored better in this pilot, but did not win more than it lost.'
    elif candidate['score'] == baseline['score'] and wins_more:
        headline = 'Both versions won more than they lost in this pilot; the timing boost did not improve the score.'
    elif candidate['score'] == baseline['score']:
        headline = 'The timing experiment did not improve the validation score. Stable WetMeat remains the release.'
    elif baseline_wins_more:
        headline = 'Stable WetMeat won more than it lost in this pilot; the timing experiment scored worse.'
    else:
        headline = 'The timing experiment scored worse in validation. Stable WetMeat remains the release.'
    decision = {'summary':headline, 'primary_objective_met_in_pilot':wins_more or baseline_wins_more,
                'baseline_wins_more_than_losses':baseline_wins_more,
                'candidate_wins_more_than_losses':wins_more,
                'candidate_score_improved':improved, 'promote_candidate_to_stable':False,
                'reason':'Only two held-out games per version and one held-out opening. This pilot does not justify a proven stronger stable release.',
                'candidate_sha256':candidate_sha,'stable_sha256':stable_sha,'opponent_sha256':opponent_sha,
                'heldout':match,'estimated_rates':dict(rates),
                'limitations':['Rates are finite-engine estimates of the recorded moves, not perfect ground truth.',
                               'Zero observed blunders does not establish a zero true blunder rate.',
                               'No reliable Elo advantage can be inferred from this six-game, two-opening pilot.']}
    (args.study/'decision.json').write_text(json.dumps(decision,indent=2)+'\n')
    verification = {'status':'passed','games':len(checks),'checks':checks,
                    'candidate_frozen_hashes_verified':True,'clock_arithmetic_verified':True,
                    'all_recorded_wetmeat_moves_audited':True,'paired_colors_and_cpu_rotation_verified':True}
    (args.study/'verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    lines = ['# WetMeat vs Stockfish 19: real 10+5 pilot','',headline,'',
             'Both engines ran at full strength with one thread, 256 MB hash, identical clocks and no pondering or tablebases. No heavy audits or builds ran alongside the two concurrent clocked games.','',
             '## Match results','', '| Stage | Version | Wins | Draws | Losses |', '|---|---|---:|---:|---:|']
    for stage,variant in [('training','baseline'),('validation','baseline'),('validation','candidate')]:
        subset = [row for s,row in records if s==stage and row.get('variant','baseline')==variant]
        counts = [sum(row['tested_points']==p for row in subset) for p in (1,.5,0)]
        lines.append(f'| {stage} | {variant} | {counts[0]} | {counts[1]} | {counts[2]} |')
    lines += ['', '## Estimated WetMeat error rates','',
              '| Scope | Audited moves | Mistakes (50–199 cp) | Blunders (200+ cp) | Mean estimated loss |',
              '|---|---:|---:|---:|---:|']
    for scope,stat in rates.items():
        lines.append(f"| {scope} | {stat['moves']} | {stat['mistakes']} ({100*stat['mistake_rate']:.2f}%) | {stat['blunders']} ({100*stat['blunder_rate']:.2f}%) | {stat['average_centipawn_loss']:.2f} cp |")
    lines += ['', 'Book moves and Stockfish opponent moves are excluded. Every WetMeat move in all six games is included. Training and validation are shown separately; the aggregate baseline rate includes both stages.','',
              f"A larger node budget still produced a lower completed comparison depth on {rates['baseline']['lower_completed_depth_moves']+rates['candidate']['lower_completed_depth_moves']} audited moves. This illustrates why these rates are estimates rather than certificates of perfect play.",'',
              '## Experiment and decision','',
              'The experimental build adds 25% to the soft time budget when its evaluation falls or its preferred root move is unstable. It preserves the hard time cap, evaluator, neural networks and search pruning. The parameter was frozen before validation; it was not fitted to the held-out results. The training audit had not identified a threshold mistake when this hypothesis was selected, so it is an exploratory timing experiment, not a demonstrated repair of a specific blunder.','',
              'The candidate passed 12 UCI protocol cases, 50 exact depth-eight search regressions, and the unchanged 1,714,434-node benchmark signature. A small alternating benchmark found it about 2.8% slower, so no speed improvement is claimed.','',
              decision['reason'],'The stable release is unchanged; the candidate remains explicitly experimental.','',
              '## Limits and reproducibility','',
              'This is a six-game rapid pilot, not an extensive Elo certification. The games cover a Spanish training pair and a Sicilian held-out pair per version. Six games and two openings cannot demonstrate an ultimate Stockfish counter. The mistake thresholds are study definitions. The Stockfish-family judge uses finite analysis and may share engine biases. Zero observed mistakes or blunders does not mean zero true error probability.','',
              'Read METHOD.md and protocol.json for exact conditions. Per-game JSON and PGN files contain complete moves, searches and clocks. Audit JSON files contain every inspected WetMeat move and same-depth comparisons. candidate-frozen.json records frozen source and binary hashes. verification.json checks legality, full audit coverage, PGN clock rounding, actual clock arithmetic, paired colors, CPU rotation and binary identity.','',
              'Tools: clock_match.py, analyse_games.py, finalize_study.py and replays/create_study_report.py. All are GPL-3.0-or-later. The experimental source retains Stockfish attribution and GPL licensing.','']
    (args.study/'REPORT.md').write_text('\n'.join(lines))
    (args.study/'all-games.pgn').write_text(''.join((args.study/stage/f"game-{row['round']:03d}.pgn").read_text() for stage,row in records))
    print(json.dumps({'summary':headline,'rates':dict(rates),'verified_games':len(checks)},indent=2))


if __name__ == '__main__':
    main()
