"""Real-clock, paired engine games. SPDX-License-Identifier: GPL-3.0-or-later."""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import platform
import time
from pathlib import Path

import chess
import chess.engine
import chess.pgn

from match import OPENINGS, score_statistics


def fingerprint(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run_game(config):
    if config['cpu'] is not None:
        os.sched_setaffinity(0, {config['cpu']})
    output = Path(config['output'])
    if output.with_suffix('.json').exists() and output.with_suffix('.pgn').exists():
        cached = json.loads(output.with_suffix('.json').read_text())
        expected = {'tested_binary_sha256': config['tested_sha'],
                    'opponent_binary_sha256': config['opponent_sha'],
                    'base_seconds': config['base'], 'increment_seconds': config['increment'],
                    'hash_mb_each': config['hash_mb'], 'cpu': config['cpu'],
                    'max_plies': config['max_plies'],
                    'tested_color': 'white' if config['tested_color'] else 'black',
                    'opening': config['opening'], 'variant': config.get('variant', 'baseline')}
        if any(cached.get(k) != value for k, value in expected.items()):
            raise RuntimeError('Saved game does not match frozen settings')
        with output.with_suffix('.pgn').open() as stream:
            saved_game = chess.pgn.read_game(stream)
        assert saved_game and not saved_game.errors
        assert saved_game.end().board().fen() == cached['final_fen']
        assert saved_game.headers['Result'] == cached['result']
        print(f"Reusing completed game {config['round']}", flush=True)
        return cached
    tested = chess.engine.SimpleEngine.popen_uci(config['engine'], timeout=config['base'] + 30)
    opponent = chess.engine.SimpleEngine.popen_uci(config['opponent'], timeout=config['base'] + 30)
    moves = []
    try:
        for item in (tested, opponent):
            settings = {'Threads': 1, 'Hash': config['hash_mb'], 'Move Overhead': 30,
                        'Skill Level': 20, 'UCI_LimitStrength': False, 'SyzygyPath': ''}
            item.configure({k: v for k, v in settings.items() if k in item.options})
        board = chess.Board()
        game = chess.pgn.Game()
        node = game
        for text in config['opening'].split():
            move = board.parse_uci(text)
            board.push(move)
            node = node.add_variation(move)
        tested_color = config['tested_color']
        token = object()
        clocks = {chess.WHITE: config['base'], chess.BLACK: config['base']}
        game.headers.update({
            'Event': 'WetMeat real-clock paired validation', 'Site': 'local',
            'Date': dt.datetime.now(dt.timezone.utc).strftime('%Y.%m.%d'),
            'Round': str(config['round']),
            'White': (tested if tested_color else opponent).id['name'],
            'Black': (opponent if tested_color else tested).id['name'],
            'TimeControl': f"{config['base']:g}+{config['increment']:g}",
            'OpeningPlies': str(len(board.move_stack)),
            'CPU': str(config['cpu']),
        })
        termination = None
        winner = None
        while not board.is_game_over(claim_draw=True) and len(board.move_stack) < config['max_plies']:
            color = board.turn
            active = tested if color == tested_color else opponent
            limit = chess.engine.Limit(white_clock=clocks[chess.WHITE], black_clock=clocks[chess.BLACK],
                                       white_inc=config['increment'], black_inc=config['increment'])
            active.timeout = clocks[color] + 10
            started = time.monotonic()
            result = active.play(board, limit, game=token, info=chess.engine.INFO_ALL)
            elapsed = time.monotonic() - started
            if elapsed >= clocks[color]:
                clocks[color] = 0.0
                termination = 'TIME_FORFEIT'
                # If the opponent has insufficient mating material, a flag is a draw.
                winner = None if board.has_insufficient_material(not color) else not color
                break
            if result.move is None or result.move not in board.legal_moves:
                raise RuntimeError(f'Illegal engine move {result.move} at {board.fen()}')
            before = clocks[color]
            clocks[color] = max(0.0, before - elapsed) + config['increment']
            score = result.info.get('score')
            record = {
                'ply': len(board.move_stack) + 1,
                'color': 'white' if color else 'black',
                'engine': active.id['name'], 'tested': color == tested_color,
                'fen_before': board.fen(), 'uci': result.move.uci(), 'san': board.san(result.move),
                'clock_before_s': before, 'elapsed_s': elapsed, 'clock_after_s': clocks[color],
                'depth': result.info.get('depth'), 'nodes': result.info.get('nodes'),
                'score_cp_mover': score.pov(color).score() if score else None,
                'mate_mover': score.pov(color).mate() if score else None,
                'pv': [move.uci() for move in result.info.get('pv', [])],
            }
            board.push(result.move)
            node = node.add_variation(result.move)
            node.set_clock(clocks[color])
            node.set_emt(elapsed)
            if score:
                node.set_eval(score, depth=result.info.get('depth'))
            moves.append(record)
            if len(moves) % 10 == 0:
                print(f"Game {config['round']}: ply {len(board.move_stack)}, clocks "
                      f"{clocks[chess.WHITE]:.1f}/{clocks[chess.BLACK]:.1f}s", flush=True)
        if termination is None:
            outcome = board.outcome(claim_draw=True)
            termination = outcome.termination.name if outcome else 'UNFINISHED_PLY_CAP'
            winner = outcome.winner if outcome else None
            text = outcome.result() if outcome else '*'
        else:
            text = '1/2-1/2' if winner is None else '1-0' if winner else '0-1'
        game.headers['Result'] = text
        game.headers['Termination'] = termination
        output = Path(config['output'])
        output.with_suffix('.pgn').write_text(str(game) + '\n\n')
        report = {
            'variant': config.get('variant','baseline'),
            'round': config['round'], 'pair': config['pair'], 'opening': config['opening'],
            'tested_color': 'white' if tested_color else 'black', 'result': text,
            'termination': termination, 'tested_points': None if text == '*' else
                0.5 if winner is None else 1 if winner == tested_color else 0,
            'headers': dict(game.headers), 'plies': len(board.move_stack), 'moves': moves,
            'final_fen': board.fen(), 'final_clocks_s': {str(k): v for k, v in clocks.items()},
            'tested_engine': tested.id, 'opponent': opponent.id,
            'tested_binary_sha256': config['tested_sha'], 'opponent_binary_sha256': config['opponent_sha'],
            'base_seconds': config['base'], 'increment_seconds': config['increment'],
            'hash_mb_each': config['hash_mb'], 'threads_each': 1, 'cpu': config['cpu'],
            'max_plies': config['max_plies'],
            'move_overhead_ms_each': 30,
            'clock_rule': 'Wall time including UCI overhead is deducted; increment is added after a legal move. A response after clock expiry is a time loss.',
        }
        temporary = output.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(report, indent=2) + '\n')
        temporary.replace(output.with_suffix('.json'))
        print(f"Finished game {config['round']}: {text}, {termination}", flush=True)
        return report
    finally:
        tested.quit()
        opponent.quit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--opponent', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, help='Also run this candidate on identical paired validation openings')
    parser.add_argument('--pairs', type=int, default=2)
    parser.add_argument('--base', type=float, default=600)
    parser.add_argument('--increment', type=float, default=5)
    parser.add_argument('--hash', type=int, default=256)
    parser.add_argument('--opening-offset', type=int, default=0)
    parser.add_argument('--max-plies', type=int, default=500)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if min(args.pairs, args.base, args.hash, args.max_plies, args.workers) <= 0 or args.increment < 0:
        parser.error('Invalid resource/count setting')
    args.output.mkdir(parents=True, exist_ok=True)
    cpus = sorted(os.sched_getaffinity(0))
    if args.workers > len(cpus):
        parser.error('Too many workers for available CPU affinity')
    tested_sha, opponent_sha = fingerprint(args.engine), fingerprint(args.opponent)
    variants = [('baseline', args.engine, tested_sha)]
    if args.candidate:
        variants.append(('candidate', args.candidate, fingerprint(args.candidate)))
    jobs = []
    for pair in range(args.pairs):
        opening = OPENINGS[(pair + args.opening_offset) % len(OPENINGS)]
        for color in (chess.WHITE, chess.BLACK):
            for label, executable, digest in variants:
                number = len(jobs) + 1
                cpu_index = number - 1
                # Swap CPU assignments for Black so neither version is tied
                # to one CPU in a two-worker control/candidate comparison.
                if args.candidate and args.workers == 2 and color == chess.BLACK:
                    cpu_index += 1
                jobs.append({'round': number, 'pair': pair + 1, 'opening': opening,
                             'variant': label, 'tested_color': color, 'engine': str(executable.resolve()),
                             'opponent': str(args.opponent.resolve()), 'base': args.base,
                             'increment': args.increment, 'hash_mb': args.hash, 'max_plies': args.max_plies,
                             'cpu': cpus[cpu_index % args.workers],
                             'tested_sha': digest, 'opponent_sha': opponent_sha,
                             'output': str(args.output / f'game-{number:03d}')})
    (args.output / 'settings.json').write_text(json.dumps({'jobs': jobs, 'platform': platform.platform(),
             'date_utc': dt.datetime.now(dt.timezone.utc).isoformat()}, indent=2) + '\n')
    start = time.monotonic()
    # Fixed chunks keep each concurrent game on a distinct CPU, including when game lengths differ.
    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        for begin in range(0, len(jobs), args.workers):
            futures = [pool.submit(run_game, job) for job in jobs[begin:begin + args.workers]]
            results.extend(future.result() for future in futures)
    results.sort(key=lambda item: item['round'])
    wins = sum(game['tested_points'] == 1 for game in results)
    draws = sum(game['tested_points'] == 0.5 for game in results)
    losses = sum(game['tested_points'] == 0 for game in results)
    summary = {'statistics': score_statistics(wins, draws, losses),
               'unfinished_games': sum(game['tested_points'] is None for game in results),
               'elapsed_seconds': time.monotonic() - start,
               'base_seconds': args.base, 'increment_seconds': args.increment,
               'tested_binary_sha256': tested_sha, 'opponent_binary_sha256': opponent_sha,
               'games': [{'round': item['round'], 'result': item['result'], 'plies': item['plies'],
                          'variant': item['variant'], 'termination': item['termination']} for item in results]}
    summary['by_variant'] = {}
    for label, executable, digest in variants:
        subset = [game for game in results if game['variant'] == label]
        summary['by_variant'][label] = {
            'binary': str(executable), 'sha256': digest,
            'statistics': score_statistics(sum(game['tested_points'] == 1 for game in subset),
                                          sum(game['tested_points'] == 0.5 for game in subset),
                                          sum(game['tested_points'] == 0 for game in subset))}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (args.output / 'games.pgn').write_text(''.join((args.output / f'game-{item["round"]:03d}.pgn').read_text() for item in results))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
