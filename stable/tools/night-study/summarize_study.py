"""Read completed games and partial audits without launching an engine. GPL-3.0-or-later."""
import argparse
import datetime as dt
import json
from pathlib import Path

import chess
import chess.pgn

from clock_match import DRAW_RULE, adjudicated_outcome
from match import OPENINGS
from verify_records import verify_audit, verify_game


def summarize(root):
    phases = {}
    games = []
    batches = {}
    frozen = {}
    state_path = root / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    for path in sorted(root.glob('pair-*/game-*.json')):
        raw = path.read_bytes()
        recorded = json.loads(raw)
        with path.with_suffix('.pgn').open() as stream:
            game = chess.pgn.read_game(stream)
        moves = verify_game(recorded, game)
        if not game or game.errors or game.end().board().fen() != recorded['final_fen']:
            raise ValueError('Game PGN/FEN mismatch: ' + str(path))
        if game.headers['Result'] != recorded['result']:
            raise ValueError('Game PGN result mismatch: ' + str(path))
        color = recorded['tested_color']
        if color not in ('white', 'black'):
            raise ValueError('Unknown tested color')
        result = recorded['result']
        if result not in ('*', '1-0', '0-1', '1/2-1/2'):
            raise ValueError('Unknown result: ' + str(path))
        board = game.end().board()
        policy = recorded.get('draw_rule')
        if policy not in (None, DRAW_RULE):
            raise ValueError('Unrecognized draw policy: ' + str(path))
        if recorded['termination'] not in ('TIME_FORFEIT', 'ENGINE_ERROR', 'ILLEGAL_MOVE_FORFEIT', 'UNFINISHED_PLY_CAP'):
            natural = board.outcome(claim_draw=True) if policy is None else adjudicated_outcome(board)
            if natural is None or natural.result() != result or natural.termination.name != recorded['termination']:
                raise ValueError('Natural result/termination disagrees with the played board: ' + str(path))
        expected = None if result == '*' else .5 if result == '1/2-1/2' else (
            1 if (result == '1-0') == (color == 'white') else 0)
        if expected != recorded['tested_points']:
            raise ValueError('Result-to-points mismatch: ' + str(path))
        variant = recorded.get('variant', 'baseline')
        phase = recorded.get('phase', 'pilot')
        fingerprints = state.get('fingerprints')
        if fingerprints:
            expected_sha = fingerprints['candidate' if variant == 'candidate' else 'engine']
            if recorded['tested_binary_sha256'] != expected_sha or recorded['opponent_binary_sha256'] != fingerprints['opponent']:
                raise ValueError('Recorded engine differs from frozen study identity')
            expected_options = {'Draw Aversion': fingerprints['candidate_draw_aversion']} if variant == 'candidate' and fingerprints.get('candidate_draw_aversion') else {}
            if recorded.get('tested_options', {}) != expected_options:
                raise ValueError('Recorded options differ from frozen experiment')
        if state.get('opening_schedule'):
            pair = int(path.parent.name.removeprefix('pair-'))
            opening_index = state['opening_schedule'][(pair - 1) % len(state['opening_schedule'])]
            expected_phase = 'training' if opening_index in state['training_opening_indices'] else 'heldout'
            if recorded['opening'] != OPENINGS[opening_index] or phase != expected_phase:
                raise ValueError('Opening/phase differs from predeclared study schedule')
        if game.headers.get('StudyPhase', phase) != phase:
            raise ValueError('PGN/report phase mismatch')
        identity = json.dumps({key: recorded.get(key) for key in ('tested_binary_sha256', 'tested_options',
                              'opponent_binary_sha256', 'draw_rule', 'base_seconds', 'increment_seconds',
                              'hash_mb_each', 'threads_each')}, sort_keys=True)
        if variant in frozen and frozen[variant] != identity:
            raise ValueError('Frozen engine/options/clock changed within study: ' + variant)
        frozen[variant] = identity
        statistics = phases.setdefault(phase, {}).setdefault(variant, {
            'wins': 0, 'draws': 0, 'losses': 0, 'unfinished': 0,
            'terminations': {}, 'tested_moves': 0, 'checked_moves': 0,
            'partial_game_moves': 0,
            'mistakes_detected': 0, 'blunders_detected': 0, 'shallow_judge_moves': 0,
            'wdl_loss_positions': 0, 'wdl_expectation_loss_sum': 0})
        field = 'unfinished' if expected is None else 'wins' if expected == 1 else 'draws' if expected == .5 else 'losses'
        statistics[field] += 1
        terminations = statistics['terminations']
        terminations[recorded['termination']] = terminations.get(recorded['termination'], 0) + 1
        if expected is not None:
            statistics['tested_moves'] += len(moves)
        else:
            statistics['partial_game_moves'] += len(moves)
        audit_path = path.parent / 'audit' / path.name
        audit_count = 0
        if expected is not None and audit_path.exists():
            audit = json.loads(audit_path.read_text())
            rows = verify_audit(audit, raw, recorded, moves)
            for row in rows:
                if row['played'] != moves[row['ply']]['uci']:
                    raise ValueError('Audited move differs from the game')
                statistics['checked_moves'] += 1
                statistics['mistakes_detected'] += row['category'] == 'mistake'
                statistics['blunders_detected'] += row['category'] == 'blunder'
                statistics['shallow_judge_moves'] += row.get('oracle_depth_below_played', False)
                if row.get('wdl_expectation_loss') is not None:
                    statistics['wdl_loss_positions'] += 1
                    statistics['wdl_expectation_loss_sum'] += row['wdl_expectation_loss']
            audit_count = len(rows)
        item = {'file': str(path), 'variant': variant, 'phase': phase, 'color': color,
                'points': expected, 'tested_moves': len(moves), 'checked_moves': audit_count,
                'opening': recorded['opening'], 'cpu': recorded['cpu'],
                'tested_binary_sha256': recorded['tested_binary_sha256'],
                'opponent_binary_sha256': recorded['opponent_binary_sha256'],
                'engine_error': recorded.get('engine_error')}
        games.append(item)
        batches.setdefault(path.parent.name, []).append((item, recorded))
    comparisons = []
    for batch, reports in batches.items():
        keys = {(g['variant'], g['color']) for g, r in reports}
        if keys != {('baseline', 'white'), ('baseline', 'black'), ('candidate', 'white'), ('candidate', 'black')}:
            continue
        if len(reports) != 4 or any(g['points'] is None for g, r in reports):
            continue
        settings = {json.dumps({key: r.get(key) for key in ('opening', 'base_seconds', 'increment_seconds',
                       'hash_mb_each', 'threads_each', 'draw_rule', 'phase', 'opponent_binary_sha256')}, sort_keys=True)
                    for g, r in reports}
        if len(settings) != 1:
            raise ValueError('Paired versions have different clock/opponent/opening/policy: ' + batch)
        baseline = sum(g['points'] for g, r in reports if g['variant'] == 'baseline')
        candidate = sum(g['points'] for g, r in reports if g['variant'] == 'candidate')
        comparisons.append({'batch': batch, 'phase': reports[0][0]['phase'],
                            'opening': reports[0][1]['opening'],
                            'baseline_points_of_2': baseline, 'candidate_points_of_2': candidate,
                            'candidate_minus_baseline_points': candidate - baseline})
    for variants in phases.values():
        for stats in variants.values():
            count = stats['wins'] + stats['draws'] + stats['losses']
            stats['score_fraction'] = (stats['wins'] + .5 * stats['draws']) / count if count else None
            complete = stats['tested_moves'] > 0 and stats['checked_moves'] == stats['tested_moves']
            stats['audit_complete'] = complete
            # Audits prioritize suspicious moves; a partial sample is biased.
            stats['mistake_rate'] = stats['mistakes_detected'] / stats['tested_moves'] if complete else None
            stats['blunder_rate'] = stats['blunders_detected'] / stats['tested_moves'] if complete else None
            stats['mean_judge_wdl_expectation_loss'] = (
                stats['wdl_expectation_loss_sum'] / stats['wdl_loss_positions']
                if complete and stats['wdl_loss_positions'] else None)
    return {'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'study': str(root),
            'by_phase_and_variant': phases, 'paired_opening_comparisons': comparisons, 'games': games,
            'limitations': ['Partial audits are prioritized and cannot give unbiased error rates.',
                           'Finite judge estimates and shallow completed depths are disclosed.',
                           'Training/held-out phases and incomplete games stay separate.',
                           'Tiny paired scores do not prove superiority; no Elo estimate or promotion.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    report = summarize(args.study)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.report.tmp')
    temporary.write_text(json.dumps(report, indent=2) + '\n')
    temporary.replace(args.output)
    print(json.dumps({key: report[key] for key in ('by_phase_and_variant', 'paired_opening_comparisons')}))


if __name__ == '__main__':
    main()
