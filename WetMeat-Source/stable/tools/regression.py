"""Check normal searches against the unmodified core. SPDX-License-Identifier: GPL-3.0-or-later."""

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.uci_client import UCIClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--positions", type=int, default=300)
    parser.add_argument("--output", type=Path, default=Path("docs/search-regression.json"))
    args = parser.parse_args()
    rng = random.Random(20261006)
    board = chess.Board()
    checked = 0
    with UCIClient(args.engine, timeout=30) as engine, UCIClient(args.reference, timeout=30) as reference:
        for item in (engine, reference):
            item.send("setoption name Threads value 1")
            item.send("setoption name Hash value 16")
            item.ready()
        for index in range(args.positions):
            if board.is_game_over(claim_draw=True) or len(board.move_stack) >= 150:
                board.reset()
            results = []
            for item in (engine, reference):
                item.send("ucinewgame")
                item.ready()
                item.send("position fen " + board.fen(en_passant="legal"))
                best, lines = item.search("go depth 8")
                last = next(line for line in reversed(lines) if line.startswith("info depth "))
                # Ignore machine-dependent time/NPS; compare search, score and PV.
                normalized = re.sub(r" nps \d+", "", last)
                normalized = re.sub(r" time \d+", "", normalized)
                results.append((best, normalized))
            if results[0] != results[1]:
                raise AssertionError(f"Normal search changed at {index}: {board.fen()}\n{results}")
            checked += 1
            board.push(rng.choice(sorted(board.legal_moves, key=lambda move: move.uci())))
            if checked % 50 == 0:
                print(f"PASS {checked} identical normal searches", flush=True)
    report = {"status": "passed", "positions": checked, "depth": 8, "threads": 1,
              "compared": ["bestmove", "depth", "seldepth", "score", "nodes", "hashfull", "tbhits", "pv"],
              "tested_binary_sha256": hashlib.file_digest(args.engine.open("rb"), "sha256").hexdigest(),
              "reference_binary_sha256": hashlib.file_digest(args.reference.open("rb"), "sha256").hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
