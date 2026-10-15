"""Independent move, FEN, perft and PV checks. SPDX-License-Identifier: GPL-3.0-or-later."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.uci_client import UCIClient


def reference_perft(board, depth):
    if depth == 0:
        return 1
    nodes = 0
    for move in list(board.legal_moves):
        board.push(move)
        nodes += reference_perft(board, depth - 1)
        board.pop()
    return nodes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=Path("bin/wetmeat-linux-avx512"))
    parser.add_argument("--positions", type=int, default=10000)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20261006)
    parser.add_argument("--chess960", action="store_true")
    parser.add_argument("--perft-every", type=int, default=50)
    parser.add_argument("--search-every", type=int, default=50)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if min(args.positions, args.threads, args.perft_every, args.search_every) < 1:
        parser.error("Counts must be positive")
    rng = random.Random(args.seed)
    board = chess.Board.from_chess960_pos(rng.randrange(960)) if args.chess960 else chess.Board()
    initial_fen = board.fen(shredder=args.chess960, en_passant="legal")
    searches = perfts = checked_pv_moves = 0
    with UCIClient(args.engine, timeout=30) as engine:
        engine.send(f"setoption name Threads value {args.threads}")
        engine.send("setoption name Hash value 32")
        engine.send(f"setoption name UCI_Chess960 value {'true' if args.chess960 else 'false'}")
        engine.ready()
        for index in range(args.positions):
            if board.is_game_over(claim_draw=True) or len(board.move_stack) >= 220:
                board = chess.Board.from_chess960_pos(rng.randrange(960)) if args.chess960 else chess.Board()
                initial_fen = board.fen(shredder=args.chess960, en_passant="legal")
                engine.send("ucinewgame")
            if index % 2:
                moves = " ".join(move.uci() for move in board.move_stack)
                engine.send("position fen " + initial_fen + (" moves " + moves if moves else ""))
            else:
                engine.send("position fen " + board.fen(shredder=args.chess960, en_passant="legal"))
            actual_fen, actual = engine.inspect()
            expected = {move.uci() for move in board.legal_moves}
            if actual != expected:
                raise AssertionError(f"Move mismatch {index}: {board.fen()} / missing {expected - actual}; extra {actual - expected}")
            expected_fen = board.fen(shredder=args.chess960, en_passant="legal")
            if actual_fen != expected_fen:
                raise AssertionError(f"FEN mismatch {index}: {actual_fen} != {expected_fen}")
            if index % args.perft_every == 0:
                engine.send("go perft 2")
                actual_nodes = int(engine.wait("Nodes searched: ")[-1].split(":", 1)[1])
                expected_nodes = reference_perft(board, 2)
                if actual_nodes != expected_nodes:
                    raise AssertionError(f"Perft mismatch {index}: {actual_nodes} != {expected_nodes}")
                perfts += 1
            if index % args.search_every == 0:
                best, lines = engine.search("go depth 7")
                if expected and best not in expected:
                    raise AssertionError(f"Illegal bestmove {best} at {index}")
                if not expected and best not in {"0000", "(none)"}:
                    raise AssertionError("Terminal position returned a move")
                for line in lines:
                    if " pv " not in line:
                        continue
                    pv = board.copy()
                    for text in line.split(" pv ", 1)[1].split():
                        move = chess.Move.from_uci(text)
                        if move not in pv.legal_moves:
                            raise AssertionError(f"Illegal PV {line} at {index}")
                        pv.push(move)
                        checked_pv_moves += 1
                searches += 1
            if expected:
                board.push(rng.choice(sorted(board.legal_moves, key=lambda move: move.uci())))
            if (index + 1) % 1000 == 0:
                print(f"PASS {index + 1} positions / {perfts} perft / {searches} searches", flush=True)
    report = {"status": "passed", "positions": args.positions, "reference_perfts": perfts,
              "searches": searches, "pv_moves_checked": checked_pv_moves, "threads": args.threads,
              "seed": args.seed, "chess960": args.chess960,
              "binary_sha256": hashlib.file_digest(args.engine.open("rb"), "sha256").hexdigest()}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
