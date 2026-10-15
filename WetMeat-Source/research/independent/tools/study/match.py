"""Paired UCI matches with equal resources. SPDX-License-Identifier: GPL-3.0-or-later."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import platform
import time
from pathlib import Path

import chess
import chess.engine
import chess.pgn


# Original, short opening sequences. Each is played with both engine colors.
OPENINGS = [
    "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6",
    "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4",
    "d2d4 d7d5 c2c4 e7e6 b1c3 g8f6",
    "d2d4 g8f6 c2c4 e7e6 g1f3 d7d5",
    "e2e4 e7e6 d2d4 d7d5 b1c3",
    "e2e4 c7c6 d2d4 d7d5 b1c3",
    "g1f3 d7d5 g2g3 g8f6 f1g2",
    "c2c4 e7e5 b1c3 g8f6 g1f3 b8c6",
    "d2d4 g8f6 c2c4 g7g6 b1c3 d7d5",
    "e2e4 e7e5 g1f3 b8c6 f1c4 g8f6 d2d3",
    "d2d4 d7d5 g1f3 g8f6 e2e3 e7e6",
    "e2e4 d7d6 d2d4 g8f6 b1c3 g7g6",
]


def configure(engine, threads, hash_mb):
    options = {"Threads": threads, "Hash": hash_mb, "Move Overhead": 0,
               "Skill Level": 20, "UCI_LimitStrength": False, "SyzygyPath": ""}
    engine.configure({key: value for key, value in options.items() if key in engine.options})
    # No Elo limiter or reduced-strength setting is applied to either engine.


def score_statistics(wins, draws, losses):
    total = wins + draws + losses
    if not total:
        return {"completed": 0, "score": None}
    score = (wins + draws / 2) / total
    z = 1.959963984540054
    denominator = 1 + z * z / total
    center = (score + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(score * (1 - score) / total + z * z / (4 * total * total)) / denominator
    lower, upper = max(0, center - radius), min(1, center + radius)
    # Treating draws as half successes is descriptive; paired openings are correlated.
    return {
        "completed": total,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "score": score,
        "approximate_score_interval_95": [lower, upper],
        "interval_note": "Descriptive Wilson interval; does not model opening-pair dependence. Not a certified Elo rating or proof of equal strength.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=Path("bin/wetmeat-linux-avx512"))
    parser.add_argument("--opponent", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=16)
    parser.add_argument("--time", type=float, default=0.1, help="Seconds per move for each engine")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--hash", type=int, default=64)
    parser.add_argument("--max-plies", type=int, default=500)
    parser.add_argument("--openings", type=Path, help="Text file: one legal UCI opening sequence per line")
    parser.add_argument("--output", type=Path, default=Path("results/match"))
    args = parser.parse_args()
    if args.pairs < 1 or args.time <= 0 or args.threads < 1 or args.hash < 1 or args.max_plies < 1:
        parser.error("All resource/count values must be positive")
    openings = OPENINGS
    if args.openings:
        openings = [line.strip() for line in args.openings.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not openings:
        parser.error("No openings")
    for opening in openings:
        board = chess.Board()
        for move in opening.split():
            board.push_uci(move)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    wins = draws = losses = unfinished = 0
    games = []
    started = time.monotonic()
    tested = chess.engine.SimpleEngine.popen_uci(str(args.engine.resolve()), timeout=30)
    opponent = chess.engine.SimpleEngine.popen_uci(str(args.opponent.resolve()), timeout=30)
    try:
        configure(tested, args.threads, args.hash)
        configure(opponent, args.threads, args.hash)
        with args.output.with_suffix(".pgn").open("w") as pgn:
            for pair in range(args.pairs):
                opening = openings[pair % len(openings)]
                for tested_color in [chess.WHITE, chess.BLACK]:
                    board = chess.Board()
                    game = chess.pgn.Game()
                    node = game
                    for text in opening.split():
                        move = board.parse_uci(text)
                        board.push(move)
                        node = node.add_variation(move)
                    token = object()  # Both processes receive ucinewgame for this game.
                    game.headers["Event"] = "WetMeat paired engine validation"
                    game.headers["Site"] = "local"
                    game.headers["Date"] = dt.datetime.now(dt.timezone.utc).strftime("%Y.%m.%d")
                    game.headers["Round"] = str(2 * pair + (1 if tested_color else 2))
                    game.headers["White"] = tested.id.get("name", "tested") if tested_color else opponent.id.get("name", "opponent")
                    game.headers["Black"] = opponent.id.get("name", "opponent") if tested_color else tested.id.get("name", "tested")
                    game.headers["TimeControl"] = f"per-move {args.time:g}s"
                    while not board.is_game_over(claim_draw=True) and len(board.move_stack) < args.max_plies:
                        active = tested if board.turn == tested_color else opponent
                        result = active.play(board, chess.engine.Limit(time=args.time), game=token)
                        if result.move is None or result.move not in board.legal_moves:
                            raise RuntimeError(f"Illegal engine move: {result.move} at {board.fen()}")
                        board.push(result.move)
                        node = node.add_variation(result.move)
                    outcome = board.outcome(claim_draw=True)
                    result_text = outcome.result() if outcome else "*"
                    termination = outcome.termination.name if outcome else "UNFINISHED_PLY_CAP"
                    if outcome is None:
                        unfinished += 1
                    elif outcome.winner is None:
                        draws += 1
                    elif outcome.winner == tested_color:
                        wins += 1
                    else:
                        losses += 1
                    game.headers["Result"] = result_text
                    game.headers["Termination"] = termination
                    pgn.write(str(game) + "\n\n")
                    pgn.flush()
                    record = {"pair": pair + 1, "tested_color": "white" if tested_color else "black", "opening": opening,
                              "result": result_text, "termination": termination, "plies": len(board.move_stack)}
                    games.append(record)
                    print(f"Game {len(games)}/{args.pairs * 2}: WetMeat {'white' if tested_color else 'black'} {result_text} ({termination}, {len(board.move_stack)} plies); W/D/L {wins}/{draws}/{losses}", flush=True)
        report = {
            "date_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "tested_engine": tested.id,
            "opponent": opponent.id,
            "tested_binary_sha256": hashlib.file_digest(args.engine.open("rb"), "sha256").hexdigest(),
            "opponent_binary_sha256": hashlib.file_digest(args.opponent.open("rb"), "sha256").hexdigest(),
            "platform": platform.platform(),
            "seconds_per_move": args.time,
            "threads_each": args.threads,
            "hash_mb_each": args.hash,
            "pairs": args.pairs,
            "unfinished_games": unfinished,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "statistics": score_statistics(wins, draws, losses),
            "games": games,
        }
        args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report["statistics"], indent=2))
    finally:
        tested.quit()
        opponent.quit()


if __name__ == "__main__":
    main()
