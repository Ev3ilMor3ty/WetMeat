"""Referee checks without an engine process. GPL-3.0-or-later."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import chess
import chess.engine
import chess.pgn

import clock_match


def main():
    board = chess.Board()
    sequence = 'g1f3 g8f6 f3g1 f6g8 g1f3 g8f6 f3g1'.split()
    for text in sequence:
        board.push_uci(text)
    assert board.can_claim_threefold_repetition() and not board.is_repetition(3)
    assert clock_match.adjudicated_outcome(board) is None
    reached = board.copy(); reached.push_uci('f6g8')
    assert clock_match.adjudicated_outcome(reached).termination == chess.Termination.THREEFOLD_REPETITION
    continued = board.copy(); continued.push_uci('e7e5')
    assert clock_match.adjudicated_outcome(continued) is None
    fifty = chess.Board('8/8/8/8/8/2k5/8/R1K5 w - - 99 1')
    assert fifty.can_claim_fifty_moves() and clock_match.adjudicated_outcome(fifty) is None
    fifty.push_uci('a1a2')
    assert clock_match.adjudicated_outcome(fifty).termination == chess.Termination.FIFTY_MOVES
    mate = chess.Board('7k/6Q1/5K2/8/8/8/8/8 b - - 100 1')
    assert clock_match.adjudicated_outcome(mate).termination == chess.Termination.CHECKMATE
    stalemate = chess.Board('7k/5Q2/6K1/8/8/8/8/8 b - - 100 1')
    assert clock_match.adjudicated_outcome(stalemate).termination == chess.Termination.STALEMATE

    class FixtureEngine:
        id = {'name': 'draw-policy fixture'}
        options = {}
        configured = None

        def configure(self, values):
            self.configured = values

        def play(self, b, *args, **kwargs):
            return SimpleNamespace(move=b.parse_uci('f6g8'), info={})

        def quit(self):
            pass

    with tempfile.TemporaryDirectory() as directory:
        config = {'cpu': None, 'output': str(Path(directory) / 'game-001'), 'base': 600,
                  'increment': 5, 'max_plies': 500, 'opening': ' '.join(sequence),
                  'variant': 'candidate', 'tested_color': False, 'round': 1, 'pair': 1,
                  'hash_mb': 128, 'engine': 'fixture1', 'opponent': 'fixture2',
                  'tested_sha': 'fixture', 'opponent_sha': 'fixture2',
                  'tested_options': {'Draw Aversion': 16}}
        tested, opponent = FixtureEngine(), FixtureEngine()
        with patch.object(chess.engine.SimpleEngine, 'popen_uci', side_effect=[tested, opponent]):
            result = clock_match.run_game(config)
        assert len(result['moves']) == 1 and result['termination'] == 'THREEFOLD_REPETITION'
        assert tested.configured == {'Draw Aversion': 16} and opponent.configured == {}
        assert result['draw_rule'] == clock_match.DRAW_RULE
        with patch.object(chess.engine.SimpleEngine, 'popen_uci', side_effect=AssertionError('Cached only')):
            assert clock_match.run_game(config) == result
        path = Path(config['output']).with_suffix('.json')
        stale = json.loads(path.read_text()); stale.pop('draw_rule'); path.write_text(json.dumps(stale))
        try:
            clock_match.run_game(config)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Different draw rule reused a saved game')
    print('PASS: prospective/reached repetitions and fifty-move draws, continuation choice, '
          'mate/stalemate precedence, real runner integration, recorded policy and stale-cache rejection. '
          'Mock fixture only, no strength games.')


if __name__ == '__main__':
    main()
