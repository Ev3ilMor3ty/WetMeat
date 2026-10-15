#!/usr/bin/env python3
"""Export one recorded, legally validated game as a self-contained replay."""
import hashlib
import json
from pathlib import Path

import chess
import chess.pgn
import chess.svg

ROOT = Path('/workspace')
SOURCE = ROOT / 'aurora-stockfish/docs/stockfish19-longer-match.pgn'
REPORT = ROOT / 'aurora-stockfish/docs/stockfish19-longer-match.json'
ROUND = 14

with SOURCE.open() as stream:
    for _ in range(ROUND):
        game = chess.pgn.read_game(stream)
assert game is not None and not game.errors
game.headers['OriginalBlack'] = game.headers['Black']
game.headers['Black'] = game.headers['Black'].replace('Aurora SF', 'WetMeat')
report = json.loads(REPORT.read_text())
record = report['games'][ROUND - 1]
opening_plies = len(record['opening'].split())
board = game.board()
frames = []
translation = str.maketrans('QRBN', 'DTLS')

def snapshot(move=None, san=None):
    frames.append({
        'fen': board.fen(),
        'pieces': {chess.square_name(s): p.symbol() for s, p in board.piece_map().items()},
        'uci': move.uci() if move else None,
        'san': san,
        'sanDe': san.translate(translation) if san else None,
        'check': chess.square_name(board.king(board.turn)) if board.is_check() else None,
        'mate': board.is_checkmate(),
        'turn': 'white' if board.turn else 'black',
    })

snapshot()
for ply, move in enumerate(game.mainline_moves()):
    assert move in board.legal_moves, f'Illegal move at ply {ply + 1}'
    san = board.san(move)
    board.push(move)
    snapshot(move, san)

assert board.is_checkmate() and board.result() == game.headers['Result'] == '0-1'
assert len(frames) - 1 == record['plies'] == 186
pgn = str(game) + '\n'
out_pgn = ROOT / 'wetmeat-vs-stockfish.pgn'
out_pgn.write_text(pgn)
with out_pgn.open() as stream:
    replayed = chess.pgn.read_game(stream)
assert replayed is not None and not replayed.errors
assert replayed.end().board().fen() == board.fen()

pieces = {s: chess.svg.piece(chess.Piece.from_symbol(s)) for s in 'KQRBNPkqrbnp'}
data = {
    'headers': dict(game.headers),
    'frames': frames,
    'pieces': pieces,
    'pgn': pgn,
    'openingPlies': opening_plies,
    'source': str(SOURCE),
    'sourceSha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    'conditions': {k: report[k] for k in ('seconds_per_move', 'threads_each', 'hash_mb_each')},
    'series': report['statistics'],
}
(ROOT / 'wetmeat-vs-stockfish.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
template = Path(__file__).with_name('replay.template.html').read_text()
embedded = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
(ROOT / 'wetmeat-vs-stockfish.html').write_text(template.replace('__GAME_DATA__', embedded))
print(json.dumps({
    'game': ROUND,
    'plies': len(frames) - 1,
    'result': board.result(),
    'last_move': frames[-1]['san'],
    'checkmate': board.is_checkmate(),
    'opening_plies': opening_plies,
    'html': str(ROOT / 'wetmeat-vs-stockfish.html'),
}))
