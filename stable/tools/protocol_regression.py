"""Reproduce and verify UCI release fixes. SPDX-License-Identifier: GPL-3.0-or-later."""

import argparse
import hashlib
import json
import queue
import sys
import time
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.uci_client import UCIClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("docs/protocol-regression.json"))
    args = parser.parse_args()
    start = chess.STARTING_FEN
    mate_in_one = "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1"
    terminal = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
    cases = [(start, "go infinite nodes 1024", "stop"),
             (start, "go infinite depth 2", "stop"),
             (start, "go infinite movetime 5", "stop"),
             (mate_in_one, "go infinite mate 1", "stop"),
             (start, "go ponder depth 2", "ponderhit"),
             (start, "go ponder depth 2", "stop"),
             (mate_in_one, "go ponder mate 1", "ponderhit"),
             (mate_in_one, "go ponder mate 1", "stop"),
             (terminal, "go infinite", "stop"),
             (terminal, "go ponder", "ponderhit"),
             (terminal, "go ponder", "stop")]
    records = []
    with UCIClient(args.engine, timeout=10) as engine:
        engine.send("setoption name Hash value 16")
        engine.send("setoption name Threads value 1")
        engine.ready()
        for fen, command, release in cases:
            engine.send("ucinewgame")
            engine.ready()
            engine.send("position fen " + fen)
            engine.send(command)
            deadline = time.monotonic() + 0.12
            info_count = 0
            while time.monotonic() < deadline:
                try:
                    line = engine.lines.get(timeout=max(0.001, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if line is None or line.startswith("bestmove "):
                    raise AssertionError(f"Premature result: {command}: {line}")
                engine.transcript.append(line)
                info_count += line.startswith("info depth ")
            if not info_count:
                raise AssertionError(f"No completed search iteration before release: {command}")
            engine.send(release)
            best = engine.wait("bestmove ")[-1].split()[1]
            board = chess.Board(fen)
            if board.is_game_over():
                if best not in {"(none)", "0000"}:
                    raise AssertionError(f"Terminal result: {best}")
            elif best not in {move.uci() for move in board.legal_moves}:
                raise AssertionError(f"Illegal result: {best}")
            engine.ready()
            records.append({"fen": fen, "command": command, "release": release, "bestmove": best})
    # Quitting while a finished infinite search is waiting must also release it.
    with UCIClient(args.engine) as engine:
        engine.send("position startpos")
        engine.send("go infinite depth 1")
        engine.wait("info depth ")
        engine.send("quit")
        engine.process.wait(timeout=3)
    report = {"status": "passed", "cases": len(records) + 1, "quit_releases_waiting_search": True,
              "records": records,
              "binary_sha256": hashlib.file_digest(args.engine.open("rb"), "sha256").hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "records"}, indent=2))


if __name__ == "__main__":
    main()
