"""Reproduce a torn final write and check checkpoint recovery without searches. GPL-3.0-or-later."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import chess
import chess.engine
import chess.pgn

import analyse_games as legacy
import pipelined_analyse_games as atomic


class Judge:
    id = {'name': 'mock checkpoint judge'}

    def configure(self, settings):
        pass

    def quit(self):
        pass

    def analyse(self, *args, **kwargs):
        raise AssertionError('Forced-only-move fixture must not launch a search')


def main():
    cases = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        board = chess.Board('8/8/8/8/8/1k6/r7/K7 w - - 0 1')
        assert board.is_valid() and list(board.legal_moves) == [chess.Move.from_uci('a1b1')]
        game = chess.pgn.Game()
        game.setup(board)
        before = board.fen()
        move = next(iter(board.legal_moves))
        game.add_variation(move)
        board.push(move)
        source = root / 'game-001.json'
        source.write_text(json.dumps({'moves': [{'ply': 1, 'tested': True, 'engine': 'fixture',
            'fen_before': before, 'uci': move.uci(), 'san': 'Kb1', 'depth': 8, 'nodes': 1000,
            'elapsed_s': .01, 'clock_before_s': 600}], 'final_fen': board.fen()}))
        source.with_suffix('.pgn').write_text(str(game) + '\n')
        config = {'source': str(source), 'judge': 'mock', 'judge_sha': 'fixture', 'cpu': None,
                  'tested_only': True, 'min_nodes': 1000000, 'multiplier': 2,
                  'refine_multiplier': 4, 'mistake_cp': 50, 'blunder_cp': 200, 'hash_mb': 512}
        write_text = Path.write_text
        for module, name in [(legacy, 'legacy'), (atomic, 'atomic')]:
            folder = root / name
            folder.mkdir()
            destination = folder / 'game-001.json'
            interrupt_target = destination if module is legacy else destination.with_suffix('.complete.tmp')
            def interrupted_write(path, contents, *args, **kwargs):
                if path == interrupt_target:
                    write_text(path, contents[:16], *args, **kwargs)
                    raise OSError('Simulated storage interruption during final write')
                return write_text(path, contents, *args, **kwargs)
            config['output'] = str(destination)
            with patch.object(chess.engine.SimpleEngine, 'popen_uci', return_value=Judge()), \
                 patch.object(Path, 'write_text', interrupted_write):
                try:
                    module.analyse_game(config)
                except OSError:
                    pass
                else:
                    raise AssertionError('Final write was not interrupted')
            if module is legacy:
                try:
                    json.loads(destination.read_text())
                except json.JSONDecodeError:
                    cases.append('legacy torn-final-write failure reproduced on a fixture')
                else:
                    raise AssertionError('Legacy failure did not reproduce')
            else:
                checkpoint = json.loads(destination.read_text())
                assert checkpoint['status'] == 'running' and len(checkpoint['moves']) == 1
                cases.append('atomic finalization preserves last valid checkpoint on write failure')
                with patch.object(chess.engine.SimpleEngine, 'popen_uci', return_value=Judge()):
                    resumed = module.analyse_game(config)
                assert resumed['status'] == 'completed' and resumed['moves'] == checkpoint['moves']
                assert json.loads(destination.read_text())['status'] == 'completed'
                cases.append('resume reuses checked rows without rerunning searches')
    print(json.dumps({'status': 'passed', 'cases': cases, 'engine_searches': 0,
                      'limitations': 'Controlled I/O fault on mock data, not damage to saved studies.'}))


if __name__ == '__main__':
    main()
