"""Audit played moves with larger, independent root-search budgets.

SPDX-License-Identifier: GPL-3.0-or-later. Centipawn thresholds are explicit
study definitions, not a universal chess-site accuracy score or perfect oracle.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import multiprocessing
import os
import time
from pathlib import Path

import chess
import chess.engine
import chess.pgn


def pin_audit_worker(cpu_queue):
    # Keep one judge per CPU while allowing the next game to start as soon
    # as a worker finishes. Node audits do not run alongside clocked games.
    os.sched_setaffinity(0, {cpu_queue.get()})


def score_value(info, color):
    score = info['score'].pov(color)
    cp = score.score()
    mate = score.mate()
    # Different lengths of a forced win/loss are not mistakes by themselves.
    value = cp if cp is not None else (10000 if score.score(mate_score=10000) > 0 else -10000)
    result = {'value': value, 'cp': cp, 'mate': mate, 'depth': info.get('depth'),
              'nodes': info.get('nodes'), 'pv': [m.uci() for m in info.get('pv', [])]}
    if 'wdl' in info:
        wdl = info['wdl'].pov(color)
        result['wdl'] = {'wins': wdl.wins, 'draws': wdl.draws, 'losses': wdl.losses,
                         'expectation': wdl.expectation()}
    return result


def analyse_game(config):
    if config['cpu'] is not None:
        os.sched_setaffinity(0, {config['cpu']})
    source = Path(config['source'])
    with source.with_suffix('.pgn').open() as stream:
        game = chess.pgn.read_game(stream)
    assert game and not game.errors
    records = json.loads(source.read_text())
    played = {item['ply']: item for item in records['moves']
              if not config.get('tested_only') or item['tested']}
    ordered_nodes = list(game.mainline())
    def priority(node):
        ply = node.parent.ply() + 1
        item = played.get(ply)
        if item is None:
            return (False, float('-inf'))
        following = played.get(ply+1, {})
        # Investigate the tested engine and suspicious evaluation swings first.
        swing = (item.get('score_cp_mover') or 0) + (following.get('score_cp_mover') or 0)
        return (item['tested'], swing)
    ordered_nodes.sort(key=priority, reverse=True)
    judge = chess.engine.SimpleEngine.popen_uci(config['judge'], timeout=600)
    judge.configure({'Threads': 1, 'Hash': config['hash_mb'], 'Move Overhead': 30,
                     'Skill Level': 20, 'UCI_LimitStrength': False, 'SyzygyPath': '',
                     'UCI_ShowWDL': True})
    board = game.board()
    rows = []
    started = time.monotonic()
    destination = Path(config['output'])
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    settings = {key: config[key] for key in ('judge_sha','min_nodes','multiplier','refine_multiplier','mistake_cp','blunder_cp','hash_mb')}
    settings['method'] = 'completed-common-depth-multipv2-v2-wdl'
    if destination.exists():
        saved = json.loads(destination.read_text())
        if saved.get('source_sha256') == source_digest and saved.get('settings') == settings:
            selected = [row for row in saved.get('moves', []) if row['ply'] in played]
            if saved.get('status') == 'completed' and {row['ply'] for row in selected} == set(played):
                judge.quit()
                print(f'Reusing completed audit {source.stem}', flush=True)
                saved['moves'] = selected
                saved['scope'] = 'tested-engine-only' if config.get('tested_only') else 'both-engines'
                return saved
            rows = selected
    cached_plies = {row['ply'] for row in rows}

    def search(move, budget, token):
        args = {'root_moves': [move]} if move else {}
        print(f"Audit {source.stem}: starting {'restricted' if move else 'full'} search, {budget:,} nodes", flush=True)
        return judge.analyse(board, chess.engine.Limit(nodes=budget), game=token, **args)

    def compare_moves(candidate, played_move, budget):
        # Compare both alternatives at the same fully completed depth. A
        # restricted single-move search otherwise gets an easier, deeper tree.
        completed = {}
        print(f'Audit {source.stem}: same-depth comparison, {2*budget:,} nodes', flush=True)
        roots = {candidate: {}, played_move: {}}
        with judge.analysis(board, chess.engine.Limit(nodes=2*budget), multipv=2,
                            root_moves=[candidate, played_move], game=object()) as analysis:
            for info in analysis:
                if not info.get('pv') or 'score' not in info or 'depth' not in info:
                    continue
                if info.get('lowerbound') or info.get('upperbound'):
                    continue
                first = info['pv'][0]
                if first not in roots:
                    continue
                depth = info['depth']
                roots[first][depth] = info
                if depth in roots[candidate] and depth in roots[played_move]:
                    completed[depth] = (roots[candidate][depth], roots[played_move][depth])
        if not completed:
            raise RuntimeError('No complete two-move audit iteration')
        first, second = completed[max(completed)]
        return score_value(first, board.turn), score_value(second, board.turn)

    try:
        for node in ordered_nodes:
            board = node.parent.board()
            move = node.move
            ply = board.ply() + 1
            if ply in played and ply not in cached_plies:
                original = played[ply]
                assert original['fen_before'] == board.fen()
                assert original['uci'] == move.uci() and move in board.legal_moves
                budget = max(config['min_nodes'], int((original.get('nodes') or 0) * config['multiplier']))
                row = {'ply': ply, 'engine': original['engine'], 'tested': original['tested'],
                       'fen': board.fen(), 'played': move.uci(), 'san': board.san(move),
                       'played_depth': original['depth'], 'played_nodes': original['nodes'],
                       'played_elapsed_s': original['elapsed_s'], 'clock_before_s': original['clock_before_s'],
                       'audit_budget_nodes_per_search': budget}
                if board.legal_moves.count() == 1:
                    row.update({'loss_cp': 0, 'category': 'acceptable', 'forced_only_move': True,
                                'best': move.uci(), 'refined': False, 'wdl_expectation_loss': 0})
                else:
                    best_info = search(None, budget, object())
                    best_move = best_info['pv'][0]
                    best = score_value(best_info, board.turn)
                    if best_move == move:
                        chosen = best
                    else:
                        best, chosen = compare_moves(best_move, move, budget)
                    initial_loss = max(0, best['value'] - chosen['value'])
                    refined = initial_loss >= config['mistake_cp'] * 0.8
                    if refined:
                        larger = max(budget + 1, int(budget * config['refine_multiplier']))
                        print(f'Audit {source.stem}: preliminary loss {initial_loss} cp; rechecking', flush=True)
                        best_info = search(None, larger, object())
                        best_move = best_info['pv'][0]
                        best = score_value(best_info, board.turn)
                        if best_move == move:
                            chosen = best
                        else:
                            best, chosen = compare_moves(best_move, move, larger)
                        row['refined_budget_nodes_per_search'] = larger
                    loss = max(0, best['value'] - chosen['value'])
                    category = 'blunder' if loss >= config['blunder_cp'] else 'mistake' if loss >= config['mistake_cp'] else 'acceptable'
                    row.update({'best': best_move.uci(), 'best_evaluation': best,
                                'played_evaluation': chosen, 'initial_loss_cp': initial_loss,
                                'loss_cp': loss, 'category': category, 'refined': refined,
                                'oracle_depth_below_played': bool(original['depth'] and best['depth'] < original['depth'])})
                    if 'wdl' in best and 'wdl' in chosen:
                        row['wdl_expectation_loss'] = max(0, best['wdl']['expectation'] - chosen['wdl']['expectation'])
                rows.append(row)
                # Checkpoints make a long audit resumable and reviewable while running.
                temporary = destination.with_suffix('.tmp')
                temporary.write_text(json.dumps({'status': 'running', 'source': str(source),
                    'source_sha256': source_digest, 'settings': settings, 'moves': rows}, indent=2) + '\n')
                temporary.replace(destination)
                print(f"Audit {source.stem}: {len(rows)}/{len(played)}, ply {ply}, "
                      f"{row['category']}, loss {row['loss_cp']} cp", flush=True)
            board.push(move)
        assert game.end().board().fen() == records['final_fen']
        assert len(rows) == len(played) and {row['ply'] for row in rows} == set(played)
        rows.sort(key=lambda row: row['ply'])
        report = {'status': 'completed', 'source': str(source), 'source_sha256':
                  source_digest, 'settings': settings,
                  'judge_sha256': config['judge_sha'], 'judge_name': judge.id['name'],
                  'min_nodes': config['min_nodes'], 'played_node_multiplier': config['multiplier'],
                  'flagged_refine_multiplier': config['refine_multiplier'],
                  'mistake_threshold_cp': config['mistake_cp'], 'blunder_threshold_cp': config['blunder_cp'],
                  'scope': 'tested-engine-only' if config.get('tested_only') else 'both-engines',
                  'elapsed_seconds': time.monotonic() - started, 'moves': rows}
        destination.write_text(json.dumps(report, indent=2) + '\n')
        return report
    finally:
        judge.quit()


def descriptive_interval(count, total):
    if total == 0:
        return None
    p = count / total
    z = 1.959963984540054
    divisor = 1 + z*z/total
    center = (p + z*z/(2*total)) / divisor
    margin = z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))/divisor
    return [max(0,center-margin), min(1,center+margin)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', type=Path, required=True)
    parser.add_argument('--judge', type=Path, required=True)
    parser.add_argument('--min-nodes', type=int, default=1000000)
    parser.add_argument('--multiplier', type=float, default=2)
    parser.add_argument('--refine-multiplier', type=float, default=4)
    parser.add_argument('--mistake-cp', type=int, default=50)
    parser.add_argument('--blunder-cp', type=int, default=200)
    parser.add_argument('--hash', type=int, default=512)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--rounds', type=int, nargs='+', help='Audit only these game round numbers')
    parser.add_argument('--tested-only', action='store_true', help='Audit every WetMeat move, excluding opponent moves')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.min_nodes < 1 or args.multiplier < 1 or args.refine_multiplier < 1 or args.mistake_cp < 1 or args.blunder_cp <= args.mistake_cp or args.hash < 1 or args.workers < 1:
        parser.error('Invalid audit settings')
    sources = sorted(args.games.glob('game-*.json'))
    if args.rounds:
        sources = [source for source in sources if int(source.stem.split('-')[-1]) in args.rounds]
    if not sources:
        parser.error('No recorded games found')
    args.output.mkdir(parents=True, exist_ok=True)
    cpus = sorted(os.sched_getaffinity(0))
    if args.workers > len(cpus):
        parser.error('Insufficient CPU affinity')
    with args.judge.open('rb') as stream:
        judge_sha = hashlib.file_digest(stream,'sha256').hexdigest()
    configs = [{'source': str(source), 'output': str(args.output / source.name),
                'judge': str(args.judge.resolve()), 'judge_sha': judge_sha, 'hash_mb': args.hash,
                'min_nodes': args.min_nodes, 'multiplier': args.multiplier,
                'refine_multiplier': args.refine_multiplier,
                'mistake_cp': args.mistake_cp, 'blunder_cp': args.blunder_cp,
                'tested_only': args.tested_only,
                'cpu': None} for source in sources]
    reports = []
    context = multiprocessing.get_context()
    cpu_queue = context.Queue()
    for cpu in cpus[:args.workers]:
        cpu_queue.put(cpu)
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers, mp_context=context,
            initializer=pin_audit_worker, initargs=(cpu_queue,)) as pool:
        futures = [pool.submit(analyse_game, config) for config in configs]
        reports.extend(future.result() for future in futures)
    cpu_queue.close()
    cpu_queue.join_thread()
    totals = {}
    for report in reports:
        for row in report['moves']:
            stats = totals.setdefault(row['engine'], {'moves': 0,'mistakes': 0,'blunders': 0,'loss_cp_sum': 0,
                                      'refined_moves': 0,'oracle_depth_below_played': 0,
                                      'wdl_loss_positions': 0, 'wdl_expectation_loss_sum': 0})
            stats['moves'] += 1
            stats['mistakes'] += row['category'] == 'mistake'
            stats['blunders'] += row['category'] == 'blunder'
            stats['loss_cp_sum'] += row['loss_cp']
            stats['refined_moves'] += row['refined']
            stats['oracle_depth_below_played'] += row.get('oracle_depth_below_played',False)
            if row.get('wdl_expectation_loss') is not None:
                stats['wdl_loss_positions'] += 1
                stats['wdl_expectation_loss_sum'] += row['wdl_expectation_loss']
    for stats in totals.values():
        stats['mistake_rate'] = stats['mistakes']/stats['moves']
        stats['blunder_rate'] = stats['blunders']/stats['moves']
        stats['average_centipawn_loss'] = stats['loss_cp_sum']/stats['moves']
        stats['descriptive_blunder_rate_interval_95'] = descriptive_interval(stats['blunders'],stats['moves'])
        if stats['wdl_loss_positions']:
            stats['average_wdl_expectation_loss'] = stats['wdl_expectation_loss_sum'] / stats['wdl_loss_positions']
    summary = {'status': 'completed', 'games': len(reports), 'by_engine': totals,
               'scope': 'tested-engine-only' if args.tested_only else 'both-engines',
               'definition': f'Mistake: {args.mistake_cp} <= loss < {args.blunder_cp} cp. Blunder: loss >= {args.blunder_cp} cp. Opening-book plies are excluded.',
               'limitations': ['Finite Stockfish-family judge, not perfect ground truth.',
                  'A full root search selects the alternative; a fresh two-move MultiPV search compares it to the played move at a common completed depth.',
                  'The judge receives the complete game history and more nodes than the played search.',
                  'Flagged moves are rechecked at larger budgets.',
                  'Node budget is larger, but completed depth can still be lower; these moves are counted and disclosed.',
                  'WDL expectation loss is the finite judge model estimate, not an empirical win rate. Centipawn mistake/blunder definitions remain50/200.',
                  'Rates describe these games only; moves within games are correlated and Wilson intervals are descriptive.'],
               'judge_binary_sha256': judge_sha}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    main()
