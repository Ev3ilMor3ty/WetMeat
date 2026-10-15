"""Utilities for the isolated fixed-time study. GPL-3.0-or-later."""
import hashlib
import json
import os
import sys
from pathlib import Path

NIGHT = '/workspace/aurora-stockfish/tools/night-study'
sys.path.insert(0, NIGHT)
from clock_match import DRAW_RULE, adjudicated_outcome
from verify_records import require, verify_audit


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = data if isinstance(data, str) else json.dumps(data, indent=2) + '\n'
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(raw)
    temporary.replace(path)


def load(path):
    return json.loads(Path(path).read_text())


def position_key(board):
    return ' '.join(board.fen(en_passant='legal').split()[:4])


def game_config(plan, pair):
    book = load(plan['training_openings'])['pairs'][pair - 1]
    assert book['pair'] == pair
    return {'pair': pair, 'opening': book['opening'], 'engine': plan['engine'],
            'opponent': plan['opponent'], 'tested_sha': plan['stable_sha256'],
            'opponent_sha': plan['opponent_sha256'], 'options': {},
            'movetime_ms': plan['movetime_ms'], 'common_uci': plan['common_uci'],
            'max_plies': plan['max_plies'], 'phase': 'training', 'variant': 'baseline'}
