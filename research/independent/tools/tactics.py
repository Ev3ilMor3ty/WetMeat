"""Small sanity suite, not a strength rating. SPDX-License-Identifier: GPL-3.0-or-later."""
import argparse
import hashlib
import json
from pathlib import Path

import chess
import chess.engine


CASES = [
    ('queen mate', '7k/5Q2/6K1/8/8/8/8/8 w - - 0 1', 'mate', None),
    ('rook mate', '7k/8/6K1/8/8/8/8/R7 w - - 0 1', 'mate', None),
    ('capture loose queen', '6k1/p7/8/3q4/8/8/8/3R2K1 w - - 0 1', 'move', 'd1d5'),
    ('knight royal fork', '8/p1q3k1/8/8/3N4/8/7P/K7 w - - 0 1', 'move', 'd4e6'),
    ('promote without stalemate', '7k/P7/6K1/8/8/8/8/8 w - - 0 1', 'promotion', None),
    ('en passant discovered mate', '8/8/8/R4pPk/8/6K1/3B4/1B6 w - f6 0 1', 'mate', None),
]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    results = []
    with chess.engine.SimpleEngine.popen_uci(str(args.engine.resolve()), timeout=10) as engine:
        for name, fen, kind, expected in CASES:
            board = chess.Board(fen)
            assert board.is_valid(), (name, board.status())
            result = engine.play(board, chess.engine.Limit(time=.5), info=chess.engine.INFO_ALL)
            assert result.move in board.legal_moves
            board.push(result.move)
            passed = board.is_checkmate() if kind == 'mate' else \
                     bool(result.move.promotion) and not board.is_stalemate() if kind == 'promotion' else \
                     result.move.uci() == expected
            results.append({'name': name, 'fen': fen, 'played': result.move.uci(), 'expected': expected,
                            'passed': passed, 'depth': result.info.get('depth'), 'nodes': result.info.get('nodes')})
    report = {'status': 'passed' if all(r['passed'] for r in results) else 'failed',
              'engine_sha256': hashlib.sha256(args.engine.read_bytes()).hexdigest(),
              'cases': results, 'limitations': 'Six elementary tactical checks cannot establish Elo or superiority.'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
