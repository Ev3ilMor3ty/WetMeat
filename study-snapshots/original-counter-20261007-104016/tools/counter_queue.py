"""Frozen parameter trials with training-only selection. GPL-3.0-or-later."""
import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import chess.pgn

sys.path.insert(0, '/workspace/aurora-stockfish/tools/night-study')
import continue_original as bounded
from verify_records import verify_audit, verify_game


FIELDS = ('wins', 'draws', 'losses', 'own_moves', 'checked_moves', 'mistakes', 'blunders', 'shallow_judge_moves')


def empty():
    return {**dict.fromkeys(FIELDS, 0), 'audit_complete': True}


def progress(plan):
    phases, studies, games, comparisons, unscored = {}, {}, [], [], []
    seen = set()
    for context in plan['study_contexts']:
        root = Path(context['path'])
        paths = sorted(root.glob('pair-*/game-*.json'))
        if context.get('selected'):
            selection = Path(plan['output']) / 'selection.json'
            if not selection.exists():
                if paths:
                    raise RuntimeError('Validation games appeared before training selection')
                continue
            ready = json.loads(selection.with_name('selection-ready.json').read_text())
            if bounded.digest(selection) != ready['selection_sha256']:
                raise RuntimeError('Frozen training selection changed')
            bias = json.loads(selection.read_text())['draw_aversion']
            if bias not in [0, *plan['trial_settings']]:
                raise RuntimeError('Undeclared validation setting')
        else:
            bias = context['bias']
        paired = {}
        study_stats = studies.setdefault(str(root), {})
        for path in paths:
            if not path.with_suffix('.pgn').exists():
                continue
            if path.resolve() in seen:
                raise RuntimeError('A played game would be counted twice')
            seen.add(path.resolve())
            raw = path.read_bytes()
            game = json.loads(raw)
            variant = game['variant']
            if variant not in ('baseline', 'candidate') or (variant == 'candidate' and not bias):
                raise RuntimeError('Unplanned engine role')
            options = {'Draw Aversion': bias} if variant == 'candidate' else {}
            expected_sha = plan['candidate_binary_sha256'] if variant == 'candidate' else plan['stable_binary_sha256']
            if game['tested_binary_sha256'] != expected_sha or game['tested_options'] != options:
                raise RuntimeError('Game configuration identity differs')
            expected_cpu = int((variant == 'baseline') == (game['tested_color'] == 'black'))
            if game['cpu'] != expected_cpu:
                raise RuntimeError('Frozen color/CPU rotation differs')
            for key, expected in plan['game_settings'].items():
                if game.get(key) != expected:
                    raise RuntimeError(f'Game resources differ: {key}')
            for side in ('tested_uci_settings', 'opponent_uci_settings'):
                if any(game[side].get(key) != value for key, value in plan['common_uci_settings'].items()):
                    raise RuntimeError('Applied UCI resources/strength differ')
            pair = int(path.parent.name.removeprefix('pair-'))
            if game['phase'] != context['phase'] or game['opening'] != context['openings'][pair - 1]:
                raise RuntimeError('Opening or phase differs from the frozen study')
            with path.with_suffix('.pgn').open() as stream:
                moves = verify_game(game, chess.pgn.read_game(stream))
            if game['tested_points'] is None:
                unscored.append(str(path))
                continue
            key = 'baseline' if variant == 'baseline' else f'draw-aversion-{bias}'
            audit_path = path.parent / 'audit' / path.name
            rows = []
            complete = False
            if audit_path.exists():
                audit = json.loads(audit_path.read_text())
                if audit['settings'] != plan['audit_settings']:
                    raise RuntimeError('Audit settings changed')
                rows = verify_audit(audit, raw, game, moves)
                if len(rows) != len(audit['moves']):
                    raise RuntimeError('Audit contains opponent moves')
                complete = audit['status'] == 'completed' and len(rows) == len(moves)
            for statistics in (phases.setdefault(game['phase'], {}).setdefault(key, empty()),
                               study_stats.setdefault(variant, empty())):
                statistics[{1: 'wins', .5: 'draws', 0: 'losses'}[game['tested_points']]] += 1
                statistics['own_moves'] += len(moves)
                statistics['checked_moves'] += len(rows)
                statistics['mistakes'] += sum(row['category'] == 'mistake' for row in rows)
                statistics['blunders'] += sum(row['category'] == 'blunder' for row in rows)
                statistics['shallow_judge_moves'] += sum(row.get('oracle_depth_below_played', False) for row in rows)
                statistics['audit_complete'] &= complete
            games.append({'file': str(path), 'study': str(root), 'phase': game['phase'], 'variant': key,
                          'points': game['tested_points'], 'own_moves': len(moves), 'checked_moves': len(rows),
                          'audit_complete': complete, 'termination': game['termination']})
            paired.setdefault(pair, {})[(variant, game['tested_color'])] = game['tested_points']
        for pair, scores in paired.items():
            required = {(v, c) for v in ('baseline', 'candidate') for c in ('white', 'black')}
            if set(scores) == required:
                base = scores[('baseline', 'white')] + scores[('baseline', 'black')]
                candidate = scores[('candidate', 'white')] + scores[('candidate', 'black')]
                comparisons.append({'study': str(root), 'pair': pair, 'phase': context['phase'],
                                    'setting': bias, 'baseline_points': base, 'candidate_points': candidate,
                                    'candidate_minus_baseline': candidate - base})
    for variants in [*phases.values(), *studies.values()]:
        for row in variants.values():
            row['more_wins_than_losses_observed'] = row['wins'] > row['losses']
            for name in ('mistake', 'blunder'):
                row[name + '_rate'] = row[name + 's'] / row['own_moves'] if row['audit_complete'] and row['own_moves'] else None
    return {'by_phase': phases, 'by_study': studies, 'paired_comparisons': comparisons,
            'games': games, 'unscored_games': unscored,
            'limits': 'Completed games only, exact configurations kept separate. Finite shared-family common-depth estimates; correlated moves/openings, exploratory parameter search and repeated inspection do not establish superiority or Elo. No automatic adoption.'}


def choose_training(plan, evidence):
    trials, eligible = [], []
    for context in plan['study_contexts']:
        if not context.get('selectable_training'):
            continue
        if context['phase'] != 'training':
            raise RuntimeError('Selection may use training data only')
        rows = evidence['by_study'].get(context['path'], {})
        baseline, candidate = rows.get('baseline', empty()), rows.get('candidate', empty())
        completed = all(sum(row[k] for k in ('wins', 'draws', 'losses')) == 4 for row in (baseline, candidate))
        clean = all(row['audit_complete'] and row['own_moves'] and not row['mistakes'] and not row['blunders'] for row in (baseline, candidate))
        base_points = baseline['wins'] + .5 * baseline['draws']
        candidate_points = candidate['wins'] + .5 * candidate['draws']
        nonregressing = candidate_points >= base_points and candidate['losses'] <= baseline['losses']
        faults = any(game['termination'] in ('TIME_FORFEIT', 'ENGINE_ERROR', 'ILLEGAL_MOVE_FORFEIT')
                     for game in evidence['games'] if game['study'] == context['path'])
        passed = bool(completed and clean and nonregressing and not faults)
        trial = {'study': context['path'], 'bias': context['bias'], 'baseline': baseline, 'candidate': candidate,
                 'complete': completed, 'clean': clean, 'gate_passed': passed,
                 'candidate_minus_baseline_points': candidate_points - base_points}
        trials.append(trial)
        if passed:
            eligible.append((candidate_points - base_points, candidate['wins'] - candidate['losses'], -context['bias']))
    bias = -max(eligible)[2] if eligible else 0
    return {'draw_aversion': bias, 'candidate_binary_sha256': plan['candidate_binary_sha256'],
            'trials': trials, 'selection_data': 'training only', 'candidate_adopted': False,
            'rule': 'Four completed fully audited games per version on two fresh training openings; no faults/errors, no lower paired score or more losses than control. Rank paired score difference, net wins, then lower bias. Equal drawn pilots may enter exploratory validation; no gain or adoption established.'}


def select(plan):
    root = Path(plan['output'])
    if (root / 'selection.json').exists():
        raise RuntimeError('A frozen selection already exists; do not select again from validation')
    chosen = choose_training(plan, progress(plan))
    chosen['frozen_before_validation_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    bounded.write(root / 'selection.json', chosen)
    bounded.write(root / 'selection-ready.json', {'selection_sha256': bounded.digest(root / 'selection.json'),
                                                'plan_sha256': bounded.digest(root / 'plan.json')})
    state = {'status': 'frozen_validation_pending', 'opening_schedule': plan['heldout_order'],
             'training_opening_indices': [],
             'fingerprints': {'engine': plan['stable_binary_sha256'], 'candidate': plan['candidate_binary_sha256'],
                              'opponent': plan['judge_sha256'], 'candidate_draw_aversion': chosen['draw_aversion'],
                              'clock_runner': plan['frozen_sha256']['/workspace/aurora-stockfish/tools/night-study/pipelined_clock_match.py']}}
    bounded.write(root / 'validation/state.json', state)
    print(json.dumps(chosen, indent=2))


if __name__ == '__main__':
    if '--select-only' in sys.argv:
        p = argparse.ArgumentParser()
        p.add_argument('--select-only', action='store_true')
        p.add_argument('--plan', type=Path, required=True)
        args = p.parse_args()
        select(json.loads(args.plan.read_text()))
    else:
        original_verify = bounded.verify_inputs

        def verify_before_spawn(plan):
            original_verify(plan)
            if time.time() >= dt.datetime.fromisoformat(plan['deadline_utc']).timestamp():
                raise RuntimeError('Continuation budget ended during input verification; no new child started')

        bounded.verify_inputs = verify_before_spawn
        bounded.progress = progress
        bounded.main()
