"""Fault injection for clock/referee/checkpoint handling. GPL-3.0-or-later."""
import fcntl
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import chess
import chess.engine

import clock_match
from journal_replay import reconstruct
from verify_records import verify_game


class Engine:
    id = {'name': 'fault-injection fixture'}
    options = {}

    def __init__(self, action, broken_quit=False):
        self.action = action
        self.broken_quit = broken_quit
        self.closed = False

    def configure(self, values):
        pass

    def play(self, board, *args, **kwargs):
        if isinstance(self.action, BaseException):
            raise self.action
        if self.action == 'interrupt':
            raise KeyboardInterrupt('Simulated external cutoff')
        return SimpleNamespace(move=chess.Move.from_uci(self.action), info={})

    def quit(self):
        if self.broken_quit:
            raise chess.engine.EngineTerminatedError('Already dead')

    def close(self):
        self.closed = True


def configuration(directory, number):
    return {'cpu': None, 'output': str(directory / f'game-{number:03d}'), 'base': 600,
            'increment': 5, 'max_plies': 500, 'opening': '', 'variant': 'candidate',
            'tested_color': True, 'round': number, 'pair': 1, 'hash_mb': 128,
            'engine': 'fixture1', 'opponent': 'fixture2', 'tested_sha': 'fixture',
            'opponent_sha': 'fixture2', 'tested_options': {'Draw Aversion': 16}}


def run(config, first, second, times=None):
    with patch.object(chess.engine.SimpleEngine, 'popen_uci', side_effect=[first, second]):
        if times:
            with patch.object(clock_match.time, 'monotonic', side_effect=times):
                report = clock_match.run_game(config)
        else:
            report = clock_match.run_game(config)
    # Mock engines deliberately advertise no supported UCI settings. Verify
    # their played evidence while leaving real-resource checks to real games.
    evidence = {key: value for key, value in report.items() if key not in ('tested_uci_settings', 'opponent_uci_settings')}
    with Path(config['output']).with_suffix('.pgn').open() as stream:
        verify_game(evidence, chess.pgn.read_game(stream))
    return report


def main():
    cases = []
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        dead = Engine(chess.engine.EngineTerminatedError('Crashed'), True)
        report = run(configuration(directory, 1), dead, Engine('e7e5'))
        assert report['termination'] == 'ENGINE_ERROR' and report['tested_points'] == 0
        assert report['engine_error'] and dead.closed
        cases.append('engine crash scored and dead-engine cleanup')
        report = run(configuration(directory, 2), Engine('e2e5'), Engine('e7e5'))
        assert report['termination'] == 'ILLEGAL_MOVE_FORFEIT' and report['tested_points'] == 0
        assert not report['moves']
        cases.append('illegal response is retained as a forfeit')
        report = run(configuration(directory, 3), Engine('e2e4'), Engine('e7e5'), [0, 601])
        assert report['termination'] == 'TIME_FORFEIT' and report['tested_points'] == 0
        assert report['final_clocks_s']['True'] == 0 and not report['moves']
        cases.append('late legal response loses on actual clock')
        report = run(configuration(directory, 4), Engine(TimeoutError('No response')), Engine('e7e5'), [0, 601])
        assert report['termination'] == 'TIME_FORFEIT' and report['engine_error']
        cases.append('protocol timeout after clock expiry')
        config = configuration(directory, 5)
        try:
            run(config, Engine('e2e4'), Engine('interrupt'))
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError('Interruption did not propagate')
        assert not Path(config['output']).with_suffix('.json').exists()
        journal = directory / 'live/game-005.jsonl'
        rows = [json.loads(line) for line in journal.read_text().splitlines()]
        assert [r['kind'] for r in rows] == ['start', 'thinking', 'move', 'thinking']
        assert rows[2]['uci'] == 'e2e4' and rows[2]['clock_after_s'] > 600
        snapshot, details = reconstruct(journal)
        assert snapshot.headers['Result'] == '*' and details['played_moves'] == 1
        assert details['thinking']['color'] == 'black'
        journal.write_bytes(journal.read_bytes() + b'{"kind":"unfinished-write')
        snapshot, details = reconstruct(journal)
        assert details['ignored_partial_last_line'] and details['played_moves'] == 1
        cases.append('last legal position and clocks survive an interrupted game')
        # Retry starts the clocks at600, retaining the first journal as history.
        config['max_plies'] = 1
        report = run(config, Engine('d2d4'), Engine('e7e5'))
        assert report['tested_points'] is None and report['result'] == '*'
        assert report['moves'][0]['clock_before_s'] == 600
        assert len(list((directory / 'live').glob('game-005.interrupted-*.jsonl'))) == 1
        snapshot, details = reconstruct(journal)
        assert details['complete_recorded_result']['result'] == '*' and details['played_moves'] == 1
        cases.append('retry preserves history, resets clocks, incomplete game excluded')
        config = configuration(directory, 6)
        with Path(config['output']).with_suffix('.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                clock_match.run_game(config)
            except RuntimeError as error:
                assert 'already running' in str(error)
            else:
                raise AssertionError('Duplicate game admitted')
        cases.append('duplicate game lock')
    print(json.dumps({'status': 'passed', 'fault_injection_cases': cases,
                      'limitations': 'Mocks only; no playing-strength evidence.'}))


if __name__ == '__main__':
    main()
