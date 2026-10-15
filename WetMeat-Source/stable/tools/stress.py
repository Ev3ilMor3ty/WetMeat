"""Exercise UCI stop, ponder and configuration. SPDX-License-Identifier: GPL-3.0-or-later."""

from __future__ import annotations

import argparse
import hashlib
import json
import queue
import random
import sys
import time
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.uci_client import UCIClient


def assert_waiting(engine, seconds=0.025):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            line = engine.lines.get(timeout=max(0.001, deadline - time.monotonic()))
        except queue.Empty:
            break
        if line is None or line.startswith("bestmove "):
            raise AssertionError(f"Engine exited or returned bestmove before stop/ponderhit: {line}")
        engine.transcript.append(line)


def check_move(board, move, lines):
    if move not in {candidate.uci() for candidate in board.legal_moves}:
        raise AssertionError(f"Illegal move {move}: {board.fen()}")
    for line in lines:
        if " pv " not in line:
            continue
        position = board.copy()
        for token in line.split(" pv ", 1)[1].split():
            candidate = chess.Move.from_uci(token)
            if candidate not in position.legal_moves:
                raise AssertionError(f"Illegal principal variation: {line}")
            position.push(candidate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=Path("bin/wetmeat-linux-avx512"))
    parser.add_argument("--cycles", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=Path("docs/stress.json"))
    args = parser.parse_args()
    if args.cycles < 1:
        parser.error("cycles must be positive")
    rng = random.Random(20261006)
    board = chess.Board()
    counts = {"node_searches": 0, "infinite_stops": 0, "ponder_stops": 0, "ponderhits": 0,
              "searchmove_restrictions": 0, "option_changes": 0, "multipv_searches": 0}
    with UCIClient(args.engine, timeout=30) as engine:
        engine.send("setoption name Hash value 64")
        engine.send("setoption name Threads value 3")
        engine.ready()
        for index in range(args.cycles):
            if board.is_game_over(claim_draw=True) or len(board.move_stack) >= 120:
                board.reset()
                engine.send("ucinewgame")
                engine.ready()
            if index % 25 == 0:
                engine.send(f"setoption name Threads value {1 if index % 50 == 0 else 3}")
                engine.send(f"setoption name Hash value {16 if index % 50 == 0 else 64}")
                engine.send("setoption name Clear Hash")
                engine.ready()
                counts["option_changes"] += 1
            engine.send("position startpos moves " + " ".join(move.uci() for move in board.move_stack))
            mode = index % 16
            if mode in (0, 1, 2):
                command = "go infinite nodes 2048" if mode == 0 else "go ponder nodes 2048"
                engine.send(command)
                assert_waiting(engine)
                engine.send("ponderhit" if mode == 2 else "stop")
                lines = engine.wait("bestmove ")
                move = lines[-1].split()[1]
                counts[["infinite_stops", "ponder_stops", "ponderhits"][mode]] += 1
            elif mode == 3:
                restricted = rng.choice(list(board.legal_moves)).uci()
                move, lines = engine.search(f"go nodes 2048 searchmoves {restricted}")
                if move != restricted:
                    raise AssertionError("searchmoves restriction ignored")
                counts["searchmove_restrictions"] += 1
            elif mode == 4:
                engine.send("setoption name MultiPV value 3")
                engine.ready()
                move, lines = engine.search("go depth 5")
                expected = min(3, board.legal_moves.count())
                found = {int(line.split(" multipv ", 1)[1].split()[0]) for line in lines if " multipv " in line}
                if found != set(range(1, expected + 1)):
                    raise AssertionError(f"Missing MultiPV alternatives: {found}")
                engine.send("setoption name MultiPV value 1")
                engine.ready()
                counts["multipv_searches"] += 1
            else:
                move, lines = engine.search("go nodes 1024")
                counts["node_searches"] += 1
            check_move(board, move, lines)
            engine.ready()
            candidates = sorted(board.legal_moves, key=lambda item: item.uci())
            board.push(chess.Move.from_uci(move) if rng.random() < 0.5 else rng.choice(candidates))
            if (index + 1) % 100 == 0:
                print(f"PASS {index + 1} UCI cycles", flush=True)
    report = {"status": "passed", "cycles": args.cycles, "counts": counts,
              "binary_sha256": hashlib.file_digest(args.engine.open("rb"), "sha256").hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
