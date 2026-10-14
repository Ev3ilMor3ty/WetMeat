"""Compare Aurora with python-chess on reproducible random legal positions."""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.uci_client import UCIClient


def reference_perft(board: chess.Board, depth: int) -> int:
    if depth == 0:
        return 1
    total = 0
    for move in list(board.legal_moves):
        board.push(move)
        total += reference_perft(board, depth - 1)
        board.pop()
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=Path("build/aurora"))
    parser.add_argument("--positions", type=int, default=10000)
    parser.add_argument("--perft-every", type=int, default=100)
    parser.add_argument("--search-every", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20261006)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.positions < 1 or args.perft_every < 1 or args.search_every < 1:
        parser.error("Counts must be positive")
    rng = random.Random(args.seed)
    board = chess.Board()
    perfts = searches = 0
    with UCIClient(args.engine) as engine:
        engine.send(f"setoption name Threads value {args.threads}")
        engine.ready()
        for index in range(args.positions):
            if board.is_game_over(claim_draw=True) or len(board.move_stack) > 250:
                board.reset()
            if index % 2:
                # Alternate independent FEN parsing and a complete move history.
                moves = " ".join(move.uci() for move in board.move_stack)
                engine.send("position startpos" + (" moves " + moves if moves else ""))
            else:
                engine.send("position fen " + board.fen(en_passant="fen"))
            actual_fen, actual = engine.inspect()
            expected = {move.uci() for move in board.legal_moves}
            if actual != expected:
                raise AssertionError(f"Position {index}: {board.fen()}\nMissing {expected - actual}; extra {actual - expected}")
            if actual_fen != board.fen(en_passant="fen"):
                raise AssertionError(f"FEN round trip {index}: {actual_fen} != {board.fen(en_passant='fen')}")
            if index % args.perft_every == 0:
                engine.send("go perft 2")
                line = engine.wait("info string nodes ")[-1]
                actual_nodes = int(re.search(r"nodes (\d+)", line).group(1))
                expected_nodes = reference_perft(board, 2)
                if actual_nodes != expected_nodes:
                    raise AssertionError(f"Perft mismatch {index}: {actual_nodes} != {expected_nodes}; {board.fen()}")
                perfts += 1
            if index % args.search_every == 0:
                best, lines = engine.search("go depth 5")
                if expected and best not in expected:
                    raise AssertionError(f"Illegal search result {best}; {board.fen()}")
                if not expected and best != "0000":
                    raise AssertionError(f"Non-null move in terminal position: {best}")
                for line in lines:
                    if " pv " not in line:
                        continue
                    pv_board = board.copy()
                    for token in line.split(" pv ", 1)[1].split():
                        move = chess.Move.from_uci(token)
                        if move not in pv_board.legal_moves:
                            raise AssertionError(f"Illegal PV at {index}: {line}; {pv_board.fen()}")
                        pv_board.push(move)
                searches += 1
            if expected:
                board.push(rng.choice(sorted(board.legal_moves, key=lambda move: move.uci())))
            if (index + 1) % 1000 == 0:
                print(f"PASS {index + 1} positions / {perfts} reference perfts / {searches} searches", flush=True)
    result = {"positions": args.positions, "reference_perfts": perfts, "searches": searches, "seed": args.seed, "threads": args.threads, "status": "passed"}
    print(json.dumps(result, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
