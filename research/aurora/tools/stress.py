"""Seeded UCI input and search-lifecycle stress tests; no external packages."""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.uci_client import UCIClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=Path("build/aurora"))
    parser.add_argument("--cycles", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261006)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.cycles < 1:
        parser.error("cycles must be positive")
    rng = random.Random(args.seed)
    invalid = [
        "position startpos moves a1a8", "position fen invalid", "position banana",
        "position fen 8/8/8/8/8/8/8/8 w - - 0 1", "go depth", "go depth -2",
        "go nodes 0", "go nodes 99999999999999999999999999999999999999",
        "go searchmoves a1a8", "setoption name Hash value -1", "setoption name Threads value 0",
        "setoption name Unknown value 3", "go movetime word", "go movestogo 0", "go nonsense",
        "position fen QQQQQQQQ/QQQQQQQK/8/8/8/8/8/7k w - - 0 1",
    ]
    openings = ["", "e2e4 e7e5 g1f3 b8c6", "d2d4 g8f6 c2c4 e7e6", "e2e4 c7c5", "c2c4 e7e5 b1c3"]
    checked_commands = 0
    with UCIClient(args.engine) as engine:
        for cycle in range(args.cycles):
            if cycle % 20 == 0:
                engine.send(f"setoption name Threads value {rng.randint(1, 3)}")
                engine.send(f"setoption name Hash value {rng.choice([1, 2, 4, 16])}")
                engine.send("setoption name Clear Hash")
            if cycle % 13 == 0:
                engine.send("ucinewgame")
            opening = rng.choice(openings)
            engine.send("position startpos" + (" moves " + opening if opening else ""))
            original, legal = engine.inspect()
            for _ in range(8):
                engine.send(rng.choice(invalid))
                engine.wait("info string Fehler:")
                checked_commands += 1
            fen, after = engine.inspect()
            if fen != original or after != legal:
                raise AssertionError("Invalid input mutated a valid position")
            kind = cycle % 4
            if kind == 0:
                best, _ = engine.search("go nodes 512")
            elif kind == 1:
                engine.send("go infinite")
                engine.wait("info depth 2 ")
                engine.ready()
                engine.send("stop")
                best = engine.wait("bestmove ")[-1].split()[1]
            elif kind == 2:
                engine.send("go ponder depth 2 wtime 1000 btime 1000")
                engine.wait("info depth 2 ")
                engine.ready()
                engine.send(rng.choice(["stop", "ponderhit"]))
                best = engine.wait("bestmove ")[-1].split()[1]
            else:
                restricted = rng.choice(sorted(legal))
                best, _ = engine.search("go depth 3 searchmoves " + restricted)
                if best != restricted:
                    raise AssertionError("searchmoves restriction violated")
            if best not in legal:
                raise AssertionError(f"Illegal result during stress test: {best}")
            engine.ready()
            if (cycle + 1) % 100 == 0:
                print(f"PASS {cycle + 1} search cycles / {checked_commands} malformed commands", flush=True)
    report = {"seed": args.seed, "search_cycles": args.cycles, "malformed_commands": checked_commands, "threads": [1, 2, 3], "status": "passed"}
    print(json.dumps(report, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
