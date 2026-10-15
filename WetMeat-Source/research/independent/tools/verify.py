"""Independent engine correctness checks. SPDX-License-Identifier: GPL-3.0-or-later."""
import argparse
import hashlib
import json
import random
import subprocess
import time
from pathlib import Path

import chess
import chess.engine


def run(binary, *args):
    return subprocess.check_output([str(binary), *map(str, args)], text=True, timeout=120).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--positions', type=int, default=1200)
    parser.add_argument('--seed', type=int, default=20261006)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    binary = args.engine.resolve()
    started = time.monotonic()
    checks = []
    # Public, independently established chess-rules reference positions/counts.
    perft = [
        (chess.STARTING_FEN, 5, 4865609),
        ('r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1', 4, 4085603),
        ('8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1', 5, 674624),
        ('r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1', 4, 422333),
        ('rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8', 4, 2103487),
    ]
    for fen, depth, expected in perft:
        actual = int(run(binary, '--perft', depth, fen))
        assert actual == expected, (fen, depth, expected, actual)
        checks.append({'type': 'perft', 'fen': fen, 'depth': depth, 'nodes': actual})
    special = [
        '4k3/8/8/r4pPK/8/8/8/8 w - f6 0 1',  # en passant exposes rook check
        '4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1',
        'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1',
        '4kr2/8/8/8/8/8/8/R3K2R w KQ - 0 1',  # attacked castling transit
        '7k/P7/8/8/8/8/7p/7K w - - 0 1',
        '7k/6Q1/5K2/8/8/8/8/8 b - - 100 1',  # mate precedes fifty-move draw
        '7k/5Q2/6K1/8/8/8/8/8 b - - 0 1',
    ]
    rng = random.Random(args.seed)
    boards = [chess.Board(fen) for fen in special]
    board = chess.Board()
    for _ in range(args.positions):
        if board.is_game_over() or len(board.move_stack) > 240:
            board = chess.Board()
        boards.append(board.copy(stack=False))
        board.push(rng.choice(list(board.legal_moves)))
    # A single subprocess accepts many positions; avoid a process per random board.
    payload = '\n'.join(b.fen(en_passant='fen') for b in boards) + '\n'
    output = subprocess.check_output([str(binary), '--legal-batch'], input=payload,
                                     text=True, timeout=120).splitlines()
    assert len(output) == len(boards)
    for b, line in zip(boards, output):
        expected = {m.uci() for m in b.legal_moves}
        assert set(line.split()) == expected, (b.fen(), expected, line)
    checks.append({'type': 'legal_move_differential', 'positions': len(boards), 'seed': args.seed})
    engine = chess.engine.SimpleEngine.popen_uci(str(binary), timeout=10)
    try:
        for b in boards[:40]:
            result = engine.play(b, chess.engine.Limit(depth=3))
            assert result.move in b.legal_moves or (not result.move and not any(b.legal_moves)), (b.fen(), result)
        for fen in special[-2:]:
            result = engine.play(chess.Board(fen), chess.engine.Limit(depth=3))
            assert not result.move
        elapsed = time.monotonic()
        result = engine.play(chess.Board(), chess.engine.Limit(time=0.15))
        elapsed = time.monotonic() - elapsed
        assert result.move in chess.Board().legal_moves and elapsed < 1.0, elapsed
        checks.append({'type': 'uci_depth_terminal_movetime', 'positions': 43, 'movetime_wall_s': elapsed})
        with engine.analysis(chess.Board(), chess.engine.Limit(nodes=20000)) as analysis:
            info = analysis.wait()
        assert info.move in chess.Board().legal_moves
        checks.append({'type': 'uci_analysis_stop', 'passed': True})
    finally:
        engine.quit()
    report = {'status': 'passed', 'engine_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'elapsed_s': time.monotonic() - started, 'checks': checks,
              'limitations': 'Correctness checks do not establish Elo or Stockfish-level strength.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
