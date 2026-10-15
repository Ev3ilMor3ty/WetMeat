"""Frozen opening/selection adapter for the original clock runner. GPL-3.0-or-later."""
import argparse
import json
import sys
from pathlib import Path

import chess

sys.path.insert(0, '/workspace/aurora-stockfish/tools/night-study')
import pipelined_clock_match as runner
from continue_original import digest


def fresh_openings(path):
    openings = json.loads(path.read_text())['openings']
    if not openings or len(set(openings)) != len(openings):
        raise ValueError('Training openings must be nonempty and distinct')
    for opening in openings:
        if opening in runner.OPENINGS:
            raise ValueError('A new training opening duplicates an earlier opening')
        board = chess.Board()
        for text in opening.split():
            board.push_uci(text)
        if board.outcome(claim_draw=True) is not None:
            raise ValueError('Training opening already ended')
    return openings


def main():
    p = argparse.ArgumentParser(description=__doc__, add_help=False)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--fresh-training', type=Path)
    p.add_argument('--selection', type=Path)
    args, remaining = p.parse_known_args()
    plan = json.loads(args.plan.read_text())
    if args.fresh_training:
        if digest(args.fresh_training) != plan['frozen_sha256'][str(args.fresh_training)]:
            raise RuntimeError('Fresh training opening file changed')
        runner.OPENINGS = list(runner.OPENINGS) + fresh_openings(args.fresh_training)
    if args.selection:
        selected = json.loads(args.selection.read_text())
        identity = json.loads(args.selection.with_name('selection-ready.json').read_text())
        if digest(args.selection) != identity['selection_sha256']:
            raise RuntimeError('Selection changed after being frozen')
        if selected['draw_aversion'] not in [0, *plan['trial_settings']]:
            raise RuntimeError('Selection is outside the predeclared search')
        if selected['candidate_binary_sha256'] != plan['candidate_binary_sha256']:
            raise RuntimeError('Selection binary changed')
        if selected['draw_aversion']:
            remaining += ['--candidate', plan['candidate_binary'], '--candidate-draw-aversion', str(selected['draw_aversion'])]
    sys.argv = [sys.argv[0], *remaining]
    runner.main()


if __name__ == '__main__':
    main()
