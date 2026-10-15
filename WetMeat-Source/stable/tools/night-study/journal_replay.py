"""Validate and reconstruct a live game's recorded moves, without resuming clocks. GPL-3.0-or-later."""
import argparse
import json
from pathlib import Path

import chess
import chess.pgn


def reconstruct(path):
    data = path.read_bytes()
    lines = data.splitlines(keepends=True)
    records = []
    truncated = False
    for index, line in enumerate(lines):
        if not line.endswith(b'\n') and index == len(lines) - 1:
            truncated = True
            break
        records.append(json.loads(line))
    if not records or records[0].get('kind') != 'start':
        raise ValueError('Missing complete journal start record')
    start = records[0]
    board = chess.Board()
    game = chess.pgn.Game()
    game.headers.update(start['headers'])
    node = game
    for text in start['opening'].split():
        move = board.parse_uci(text)
        board.push(move)
        node = node.add_variation(move)
    clocks = dict(start['clocks_s'])
    played = []
    finished = None
    last_thinking = None
    for record in records[1:]:
        if finished is not None:
            raise ValueError('Unexpected record after finished game')
        kind = record['kind']
        if kind == 'thinking':
            assert record['fen'] == board.fen() and record['ply'] == board.ply() + 1
            assert record['color'] == ('white' if board.turn else 'black')
            assert abs(record['clock_before_s'] - clocks[record['color']]) < 1e-6
            last_thinking = record
        elif kind == 'move':
            assert last_thinking and record['ply'] == board.ply() + 1
            assert record['fen_before'] == board.fen()
            color = 'white' if board.turn else 'black'
            assert record['color'] == color
            assert abs(record['clock_before_s'] - clocks[color]) < 1e-6
            assert 0 <= record['elapsed_s'] < clocks[color]
            expected = clocks[color] - record['elapsed_s'] + start['increment_seconds']
            assert abs(record['clock_after_s'] - expected) < 1e-6
            move = board.parse_uci(record['uci'])
            assert record['san'] == board.san(move)
            board.push(move)
            assert record['fen_after'] == board.fen()
            node = node.add_variation(move)
            node.set_clock(record['clock_after_s'])
            node.set_emt(record['elapsed_s'])
            clocks[color] = record['clock_after_s']
            assert all(abs(clocks[c] - record['clocks_s'][c]) < 1e-6 for c in clocks)
            played.append(record)
            last_thinking = None
        elif kind == 'finished':
            assert record['final_fen'] == board.fen() and record['plies'] == board.ply()
            assert record['result'] in ('1-0', '0-1', '1/2-1/2', '*')
            game.headers['Result'] = record['result']
            game.headers['Termination'] = record['termination']
            clocks = record['clocks_s']
            finished = record
        else:
            raise ValueError('Unknown journal record: ' + kind)
    if finished is None:
        game.headers['Result'] = '*'
        game.headers['Termination'] = 'UNFINISHED_JOURNAL_SNAPSHOT'
    summary = {'source': str(path), 'variant': start['variant'], 'phase': start.get('phase', 'pilot'),
               'played_moves': len(played), 'final_fen': board.fen(), 'last_recorded_clocks_s': clocks,
               'thinking': last_thinking, 'complete_recorded_result': finished,
               'ignored_partial_last_line': truncated,
               'limitations': 'Diagnostic snapshot only. Live or interrupted clocks are never resumed; unfinished snapshots do not count as scored games.'}
    return game, summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--journal', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    game, summary = reconstruct(args.journal)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix('.pgn').write_text(str(game) + '\n\n')
    args.output.with_suffix('.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
