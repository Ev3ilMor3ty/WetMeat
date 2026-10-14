"""Original, seeded mate puzzles validated by an exhaustive python-chess solver."""

from __future__ import annotations

import argparse
import functools
import json
import random
from pathlib import Path

import chess
import chess.engine


def mate_moves(board, plies):
    attacker = board.turn

    @functools.lru_cache(maxsize=100000)
    def won(fen, remaining):
        current = chess.Board(fen)
        if current.is_checkmate():
            return current.turn != attacker
        if remaining == 0 or current.is_stalemate() or current.is_insufficient_material():
            return False
        attacker_turn = current.turn == attacker
        for move in current.legal_moves:
            current.push(move)
            result = won(current.fen(), remaining - 1)
            current.pop()
            if attacker_turn and result:
                return True
            if not attacker_turn and not result:
                return False
        return not attacker_turn

    winning = set()
    for move in list(board.legal_moves):
        board.push(move)
        if won(board.fen(), plies - 1):
            winning.add(move.uci())
        board.pop()
    return winning


def puzzles(seed, count):
    rng = random.Random(seed)
    cases = []
    seen = set()
    for kind, major, plies in [("queen-mate-1", chess.QUEEN, 1), ("rook-mate-1", chess.ROOK, 1), ("queen-mate-2", chess.QUEEN, 3)]:
        found = 0
        attempts = 0
        while found < count:
            attempts += 1
            if attempts > 20000:
                raise RuntimeError(f"Could not generate enough {kind} cases")
            board = chess.Board(None)
            defender = rng.choice([chess.WHITE, chess.BLACK])
            attacker = not defender
            edge = rng.choice([*range(8), *range(56, 64), *range(8, 56, 8), *range(15, 56, 8)])
            board.set_piece_at(edge, chess.Piece(chess.KING, defender))
            squares = rng.sample([square for square in chess.SQUARES if square != edge], 2)
            board.set_piece_at(squares[0], chess.Piece(chess.KING, attacker))
            board.set_piece_at(squares[1], chess.Piece(major, attacker))
            board.turn = attacker
            if not board.is_valid() or board.is_game_over() or board.fen() in seen:
                continue
            if plies > 1 and mate_moves(board, 1):
                continue
            expected = mate_moves(board, plies)
            if not expected:
                continue
            seen.add(board.fen())
            cases.append({"kind": kind, "fen": board.fen(), "moves": sorted(expected), "mate": (plies + 1) // 2})
            found += 1
        print(f"Generated {found} {kind} positions with exact reference solutions", flush=True)
    cases.extend([
        {"kind": "rook-underpromotion-avoids-stalemate", "fen": "8/k1P5/2K5/8/8/8/8/8 w - - 0 1", "moves": ["c7c8r"]},
        {"kind": "capture-hanging-queen", "fen": "4k3/8/8/8/4q3/8/4R3/4K3 w - - 0 1", "moves": ["e2e4"]},
        {"kind": "pawn-captures-checking-queen", "fen": "4k3/8/8/2n1q3/3P4/8/8/4K3 w - - 0 1", "moves": ["d4e5"]},
    ])
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=Path("build/aurora"))
    parser.add_argument("--count-per-kind", type=int, default=12)
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--seed", type=int, default=20261006)
    parser.add_argument("--output", type=Path, default=Path("results/tactics.json"))
    args = parser.parse_args()
    if args.count_per_kind < 1 or args.depth < 1:
        parser.error("Counts/depth must be positive")
    cases = puzzles(args.seed, args.count_per_kind)
    failures = []
    with chess.engine.SimpleEngine.popen_uci(str(args.engine.resolve()), timeout=30) as engine:
        engine.configure({"Threads": 1, "Hash": 16})
        for index, case in enumerate(cases):
            board = chess.Board(case["fen"])
            info = engine.analyse(board, chess.engine.Limit(depth=args.depth), game=object())
            best = info["pv"][0].uci() if info.get("pv") else "0000"
            case["actual"] = best
            case["score"] = str(info.get("score"))
            case["passed"] = best in case["moves"]
            if "mate" in case:
                actual_mate = info["score"].pov(board.turn).mate()
                case["passed"] = case["passed"] and actual_mate is not None and 0 < actual_mate <= case["mate"]
            if not case["passed"]:
                failures.append(case)
                print(f"FAIL {index + 1}: {case}", flush=True)
    report = {"seed": args.seed, "depth": args.depth, "total": len(cases), "passed": len(cases) - len(failures), "failed": len(failures), "cases": cases}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Tactics: {report['passed']}/{report['total']} passed; report: {args.output}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
