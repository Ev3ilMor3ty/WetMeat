"""Generate original positions and label quiet evaluations with a separate UCI teacher."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import random
import sys
import threading
import time

import chess
import chess.engine
import chess.pgn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.match import OPENINGS
from tools.uci_client import UCIClient


def normalize(board):
    copy = board.copy(stack=False)
    copy.halfmove_clock = 0
    copy.fullmove_number = 1
    return copy.fen(en_passant="legal")


def pgn_positions(directory):
    for path in sorted(directory.glob("*.pgn")):
        with path.open() as stream:
            game_number = 0
            while game := chess.pgn.read_game(stream):
                game_number += 1
                board = game.board()
                for ply, move in enumerate(game.mainline_moves()):
                    board.push(move)
                    if ply >= 8:
                        yield board, f"pgn/{path.stem}/{game_number}"


def rollout_positions(executable, rng, max_games, nodes):
    with chess.engine.SimpleEngine.popen_uci(str(executable.resolve()), timeout=30) as engine:
        engine.configure({"Threads": 1, "Hash": 16, "Move Overhead": 0})
        for game in range(max_games):
            board = chess.Board()
            group = f"rollout/{game}"
            for text in rng.choice(OPENINGS).split():
                board.push_uci(text)
            while len(board.move_stack) < 220 and not board.is_game_over(claim_draw=True):
                quiet = [move for move in board.legal_moves if not board.is_capture(move) and not board.gives_check(move)]
                if quiet and not board.is_check() and rng.random() < 0.10:
                    move = rng.choice(quiet)
                else:
                    result = engine.play(board, chess.engine.Limit(nodes=nodes), game=group)
                    move = result.move
                if move is None or move not in board.legal_moves:
                    raise RuntimeError("Illegal rollout move")
                board.push(move)
                if len(board.move_stack) >= 10 and rng.random() < 0.65:
                    yield board, group


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True, help="Immutable classical baseline")
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--pgn-dir", type=Path, default=Path("docs"))
    parser.add_argument("--positions", type=int, default=20000)
    parser.add_argument("--nodes", type=int, default=8192)
    parser.add_argument("--rollout-nodes", type=int, default=1024)
    parser.add_argument("--max-games", type=int, default=1500)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261007)
    parser.add_argument("--output", type=Path, default=Path("data/training.jsonl"))
    args = parser.parse_args()
    if min(args.positions, args.nodes, args.workers, args.rollout_nodes, args.max_games) < 1:
        parser.error("Counts must be positive")
    rng = random.Random(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        parser.error("Output already exists; preserve datasets and choose a new output")
    resources = []
    resources_lock = threading.Lock()
    local = threading.local()

    def label(sample):
        fen, group = sample
        if not hasattr(local, "teacher"):
            local.teacher = chess.engine.SimpleEngine.popen_uci(str(args.teacher.resolve()), timeout=30)
            local.teacher.configure({"Threads": 1, "Hash": 32, "Move Overhead": 0})
            local.baseline = UCIClient(args.engine)
            local.baseline.__enter__()
            with resources_lock:
                resources.append((local.teacher, local.baseline))
        board = chess.Board(fen)
        info = local.teacher.analyse(board, chess.engine.Limit(nodes=args.nodes))
        if not info.get("pv") or info.get("depth", 0) < 6:
            return None
        if board.is_capture(info["pv"][0]) or board.gives_check(info["pv"][0]):
            return None
        teacher_cp = info["score"].pov(chess.WHITE).score(mate_score=2000)
        teacher_cp = max(-2000, min(2000, teacher_cp))
        local.baseline.send("position fen " + fen)
        local.baseline.send("eval")
        line = local.baseline.wait("info string evaluation cp ")[-1]
        baseline_cp = int(line.split()[-1])
        sign = 1 if board.turn == chess.WHITE else -1
        return {"fen": fen, "group": group, "baseline_white": sign * (baseline_cp - 12),
                "target_white": teacher_cp - sign * 12, "teacher_depth": info.get("depth", 0)}

    seen = set()
    accepted = candidates = 0
    started = time.monotonic()
    batch = []
    depths = []
    try:
        with args.output.open("w") as stream, ThreadPoolExecutor(max_workers=args.workers) as pool:
            def flush():
                nonlocal accepted, candidates
                for result in pool.map(label, batch):
                    candidates += 1
                    if result is not None and accepted < args.positions:
                        stream.write(json.dumps(result) + "\n")
                        depths.append(result["teacher_depth"])
                        accepted += 1
                stream.flush()
                batch.clear()
                if accepted:
                    print(f"Labelled {accepted}/{args.positions} quiet positions, {candidates} candidates, {time.monotonic() - started:.1f}s", flush=True)

            for generator in [pgn_positions(args.pgn_dir), rollout_positions(args.engine, rng, args.max_games, args.rollout_nodes)]:
                for board, group in generator:
                    if board.is_check() or board.is_game_over(claim_draw=True):
                        continue
                    if sum(len(board.pieces(kind, color)) for color in chess.COLORS for kind in chess.PIECE_TYPES) < 6:
                        continue
                    fen = normalize(board)
                    if fen in seen:
                        continue
                    seen.add(fen)
                    batch.append((fen, group))
                    if len(batch) >= 256:
                        flush()
                    if accepted >= args.positions:
                        break
                if accepted >= args.positions:
                    break
            if batch and accepted < args.positions:
                flush()
        metadata = {"positions": accepted, "candidates": candidates, "teacher_nodes": args.nodes,
                    "teacher_minimum_depth": min(depths) if depths else None, "teacher_average_depth": sum(depths) / len(depths) if depths else None,
                    "seed": args.seed, "workers": args.workers, "elapsed_seconds": round(time.monotonic() - started, 2),
                    "baseline_sha256": hashlib.file_digest(args.engine.open("rb"), "sha256").hexdigest(),
                    "teacher_sha256": hashlib.file_digest(args.teacher.open("rb"), "sha256").hexdigest(),
                    "dataset_sha256": hashlib.file_digest(args.output.open("rb"), "sha256").hexdigest(),
                    "notes": ["Original local positions; separate teacher process supplies numeric targets.",
                              "No teacher code or network weights are imported.", "Game groups allow held-out validation without neighboring positions crossing the split."]}
        args.output.with_suffix(".metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(json.dumps(metadata, indent=2))
        if accepted < args.positions:
            raise SystemExit("Requested position count not reached")
    finally:
        for teacher, baseline in resources:
            teacher.quit()
            baseline.close()


if __name__ == "__main__":
    main()
