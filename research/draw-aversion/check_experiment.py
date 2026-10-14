"""Checks for the root-relative draw experiment. GPL-3.0-or-later."""
import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

import chess

sys.path.insert(0, '/workspace/aurora-stockfish')
from tools.uci_client import UCIClient

CASES = [
    ('queen mate', '7k/5Q2/6K1/8/8/8/8/8 w - - 0 1', 'mate', None),
    ('rook mate', '7k/8/6K1/8/8/8/8/R7 w - - 0 1', 'mate', None),
    ('loose queen', '6k1/p7/8/3q4/8/8/8/3R2K1 w - - 0 1', 'move', 'd1d5'),
    ('royal fork', '8/p1q3k1/8/8/3N4/8/7P/K7 w - - 0 1', 'move', 'd4e6'),
    ('promotion', '7k/P7/6K1/8/8/8/8/8 w - - 0 1', 'promotion', None),
    ('en passant mate', '8/8/8/R4pPk/8/6K1/3B4/1B6 w - f6 0 1', 'mate', None),
    ('mate before fifty', '7k/5Q2/6K1/8/8/8/8/8 w - - 99 1', 'mate', None),
]


def configure(client, bias=16):
    client.send('setoption name Threads value 1')
    client.send('setoption name Hash value 16')
    client.send(f'setoption name Draw Aversion value {bias}')
    client.ready()


def search(client, fen, depth=8):
    client.send('position fen ' + fen)
    best, lines = client.search(f'go depth {depth}')
    last = next(line for line in reversed(lines) if line.startswith('info depth '))
    return best, re.sub(r' (?:time|nps) \d+', '', last)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--engine', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    checks = []
    rng = random.Random(2026100616)
    with UCIClient(args.engine, timeout=30) as engine:
        configure(engine)
        for name, fen, kind, expected in CASES:
            board = chess.Board(fen)
            engine.send('ucinewgame'); engine.ready()
            best, _ = search(engine, fen, 12)
            move = chess.Move.from_uci(best)
            assert move in board.legal_moves, (name, best)
            board.push(move)
            assert board.is_checkmate() if kind == 'mate' else (
                bool(move.promotion) and not board.is_stalemate() if kind == 'promotion'
                else best == expected), (name, best)
            checks.append({'case': name, 'bestmove': best})
        for name, fen in [('mate at 100', '7k/6Q1/5K2/8/8/8/8/8 b - - 100 1'),
                          ('stalemate', '7k/5Q2/6K1/8/8/8/8/8 b - - 0 1')]:
            engine.send('position fen ' + fen)
            best, _ = engine.search('go depth 8')
            assert best in ('0000', '(none)'), (name, best)
            checks.append({'case': name, 'bestmove': best})
        board = chess.Board()
        for index in range(100):
            if board.is_game_over(claim_draw=True) or len(board.move_stack) > 140:
                board.reset()
            engine.send('ucinewgame'); engine.ready()
            fen = board.fen(en_passant='fen')
            best, _ = search(engine, fen, 8)
            assert chess.Move.from_uci(best) in board.legal_moves
            _, generated = engine.inspect()
            assert generated == {m.uci() for m in board.legal_moves}
            board.push(rng.choice(sorted(board.legal_moves, key=lambda m: m.uci())))
        checks.append({'case': 'differential legality and enabled search', 'positions': 100})
        # At halfmove 99, every legal move in this rook ending reaches a draw.
        # The root's preference must be negative for either color, and cleared
        # when the option changes or a tablebase path disables the heuristic.
        white = '8/8/8/8/8/2k5/8/R1K5 w - - 99 1'
        black = white.replace(' w ', ' b ')
        engine.send('ucinewgame'); engine.ready()
        for fen in (white, black, white, black):
            warm = search(engine, fen, 4)
            with UCIClient(args.engine, timeout=30) as fresh:
                configure(fresh)
                cold = search(fresh, fen, 4)
            assert warm == cold, ('root-color TT context', fen, warm, cold)
            assert int(re.search(r'score cp (-?\d+)', warm[1]).group(1)) < 0, warm
        checks.append({'case': 'root-color TT context and draw-score signs', 'positions': 4})
        configure(engine, 0)
        _, zero = search(engine, white, 4)
        assert int(re.search(r'score cp (-?\d+)', zero).group(1)) == 0, zero
        configure(engine, 16)
        engine.send('setoption name SyzygyPath value /workspace/scratch/nonexistent-tablebases')
        engine.ready()
        _, exact = search(engine, white, 4)
        assert int(re.search(r'score cp (-?\d+)', exact).group(1)) == 0, exact
        engine.send('setoption name SyzygyPath value <empty>'); engine.ready()
        _, biased = search(engine, white, 4)
        assert int(re.search(r'score cp (-?\d+)', biased).group(1)) < 0, biased
        checks.append({'case': 'option and tablebase context changes'})
        engine.send('setoption name Threads value 2'); engine.ready()
        engine.send('position startpos moves g1f3 g8f6 f3g1 f6g8 g1f3 g8f6 f3g1 f6g8')
        best, _ = engine.search('go nodes 20000')
        assert chess.Move.from_uci(best) in chess.Board().legal_moves
        engine.send('position startpos'); engine.send('go infinite nodes 2000')
        engine.wait('info depth 2')
        engine.send('stop')
        best = engine.wait('bestmove ')[-1].split()[1]
        assert chess.Move.from_uci(best) in chess.Board().legal_moves
        checks.append({'case': 'two-thread repetition and infinite-stop'})
    report = {'status': 'passed', 'binary_sha256': hashlib.sha256(args.engine.read_bytes()).hexdigest(),
              'draw_aversion': 16, 'checks': checks,
              'limitations': 'Correctness and elementary tactics; no strength estimate.'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
