"""Enabled-setting tactical, legality and context checks. GPL-3.0-or-later."""
import argparse
import hashlib
import importlib.util
import json
import random
import re
import sys
from pathlib import Path

import chess

sys.path.insert(0, '/workspace/aurora-stockfish')
from tools.uci_client import UCIClient

SPEC = importlib.util.spec_from_file_location('frozen_cases', '/workspace/wetmeat-original-experiments/draw-aversion/check_experiment.py')
CASES_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CASES_MODULE)


def configure(client, bias):
    for name, value in {'Threads': 1, 'Hash': 16, 'Draw Aversion': bias,
                        'Skill Level': 20, 'UCI_LimitStrength': 'false'}.items():
        client.send(f'setoption name {name} value {value}')
    client.ready()


def search(client, fen, depth=8):
    client.send('position fen ' + fen)
    best, lines = client.search(f'go depth {depth}')
    last = next(line for line in reversed(lines) if line.startswith('info depth '))
    return best, re.sub(r' (?:time|nps) \d+', '', last)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine', type=Path, required=True)
    p.add_argument('--bias', type=int, choices=[32, 64], required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    checks = []
    rng = random.Random(2026100732)
    with UCIClient(args.engine, timeout=30) as engine:
        configure(engine, args.bias)
        for name, fen, kind, expected in CASES_MODULE.CASES:
            board = chess.Board(fen)
            engine.send('ucinewgame'); engine.ready()
            best, _ = search(engine, fen, 12)
            move = chess.Move.from_uci(best)
            assert move in board.legal_moves, (name, best)
            board.push(move)
            assert board.is_checkmate() if kind == 'mate' else (
                bool(move.promotion) and not board.is_stalemate() if kind == 'promotion' else best == expected), (name, best)
            checks.append({'case': name, 'bestmove': best})
        for name, fen in [('mate at100', '7k/6Q1/5K2/8/8/8/8/8 b - - 100 1'),
                          ('stalemate', '7k/5Q2/6K1/8/8/8/8/8 b - - 0 1')]:
            engine.send('position fen ' + fen)
            best, _ = engine.search('go depth 8')
            assert best in ('0000', '(none)'), (name, best)
            checks.append({'case': name, 'bestmove': best})
        board = chess.Board()
        for _ in range(100):
            if board.is_game_over(claim_draw=True) or len(board.move_stack) > 140:
                board.reset()
            engine.send('ucinewgame'); engine.ready()
            best, _ = search(engine, board.fen(en_passant='fen'))
            assert chess.Move.from_uci(best) in board.legal_moves
            _, generated = engine.inspect()
            assert generated == {m.uci() for m in board.legal_moves}
            board.push(rng.choice(sorted(board.legal_moves, key=lambda m: m.uci())))
        checks.append({'case': 'differential legality', 'positions': 100})
        white = '8/8/8/8/8/2k5/8/R1K5 w - - 99 1'
        black = white.replace(' w ', ' b ')
        engine.send('ucinewgame'); engine.ready()
        for fen in (white, black, white, black):
            warm = search(engine, fen, 4)
            with UCIClient(args.engine, timeout=30) as fresh:
                configure(fresh, args.bias)
                cold = search(fresh, fen, 4)
            assert warm == cold, ('root-color context', fen, warm, cold)
            assert int(re.search(r'score cp (-?\d+)', warm[1]).group(1)) < 0
        configure(engine, 0)
        _, zero = search(engine, white, 4)
        assert int(re.search(r'score cp (-?\d+)', zero).group(1)) == 0
        configure(engine, args.bias)
        engine.send('setoption name SyzygyPath value /workspace/scratch/nonexistent-tablebases'); engine.ready()
        _, exact = search(engine, white, 4)
        assert int(re.search(r'score cp (-?\d+)', exact).group(1)) == 0
        engine.send('setoption name SyzygyPath value <empty>'); engine.ready()
        checks.append({'case': 'root-color, option and tablebase context', 'positions': 4})
        engine.send('setoption name Threads value 2'); engine.ready()
        engine.send('position startpos moves g1f3 g8f6 f3g1 f6g8 g1f3 g8f6 f3g1 f6g8')
        best, _ = engine.search('go nodes 20000')
        assert chess.Move.from_uci(best) in chess.Board().legal_moves
        engine.send('position startpos'); engine.send('go infinite nodes 2000')
        engine.wait('info depth 2'); engine.send('stop')
        best = engine.wait('bestmove ')[-1].split()[1]
        assert chess.Move.from_uci(best) in chess.Board().legal_moves
        checks.append({'case': 'two-thread repetition and infinite-stop'})
    with args.engine.open('rb') as stream:
        binary_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    report = {'status': 'passed', 'binary_sha256': binary_sha,
              'draw_aversion': args.bias, 'checks': checks,
              'limits': 'Correctness and elementary tactics; no strength estimate.'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
