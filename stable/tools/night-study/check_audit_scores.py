"""Verify mover orientation and mate handling in audit values. GPL-3.0-or-later."""
import json

import chess
import chess.engine

from analyse_games import score_value


def main():
    info = {'score': chess.engine.PovScore(chess.engine.Cp(180), chess.WHITE),
            'wdl': chess.engine.PovWdl(chess.engine.Wdl(650, 300, 50), chess.WHITE),
            'depth': 20, 'nodes': 1000000, 'pv': [chess.Move.from_uci('e2e4')]}
    white = score_value(info, chess.WHITE)
    black = score_value(info, chess.BLACK)
    assert white['value'] == 180 and black['value'] == -180
    assert white['wdl']['expectation'] == .8 and black['wdl']['expectation'] == .2
    assert white['wdl']['wins'] == black['wdl']['losses'] == 650
    assert white['depth'] == black['depth'] == 20
    for mate in (1, 6, -1, -6):
        raw = {'score': chess.engine.PovScore(chess.engine.Mate(mate), chess.WHITE)}
        first, second = score_value(raw, chess.WHITE), score_value(raw, chess.BLACK)
        assert first['value'] == (10000 if mate > 0 else -10000)
        assert second['value'] == -first['value']
    assert score_value({'score': chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE)}, chess.WHITE)['value'] == 0
    print(json.dumps({'status': 'passed', 'checks': ['mover score and WDL orientation',
          'mate distance does not invent a score loss', 'WDL absent is allowed'],
          'limitations': 'Score parsing checks; no actual strength result.'}))


if __name__ == '__main__':
    main()
