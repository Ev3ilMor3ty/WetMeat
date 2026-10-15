"""Check CPU queue ordering and frozen-output protection; no engines. GPL-3.0-or-later."""
import copy
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import chess.engine
import chess.pgn

import pipelined_clock_match as pipeline
from check_match_failures import Engine, configuration
from verify_records import verify_game


def probe_play(job):
    start = time.monotonic()
    time.sleep(job['simulated_seconds'])
    return {'round': job['round'], 'cpu': job['cpu'], 'variant': job['variant'],
            'tested_color': job['tested_color'], 'start': start, 'end': time.monotonic(),
            'affinity': sorted(os.sched_getaffinity(0)), 'pid': os.getpid(),
            'base': job['base'], 'increment': job['increment'], 'hash_mb': job['hash_mb']}


def main():
    cases = []
    cpus = [0, 1]
    jobs = [dict(round=index + 1, cpu=cpus[cpu], variant=variant, tested_color=color,
                 simulated_seconds=seconds, base=600, increment=5, hash_mb=128)
            for index, (cpu, variant, color, seconds) in enumerate([
                (0, 'baseline', True, .02), (1, 'candidate', True, .20),
                (1, 'baseline', False, .02), (0, 'candidate', False, .20)])]
    results = pipeline.run_pipelined(jobs, 2, probe_play)
    by_round = {result['round']: result for result in results}
    assert by_round[4]['start'] >= by_round[1]['end'] and by_round[4]['start'] < by_round[2]['end']
    assert by_round[3]['start'] >= by_round[2]['end']
    assert by_round[1]['pid'] == by_round[4]['pid'] and by_round[2]['pid'] == by_round[3]['pid']
    assert all(result['affinity'] == [result['cpu']] for result in results)
    assert all((result['base'], result['increment'], result['hash_mb']) == (600, 5, 128) for result in results)
    assert [result['round'] for result in results] == [1, 2, 3, 4]
    cases.append('freed CPU starts its next game with fixed resources and original color rotation')
    cases.append('one sequential queue per CPU, with no same-CPU overlap')
    for label, action in [
        ('mixed CPU queue rejected', lambda: pipeline.run_cpu_queue(jobs[:2], probe_play)),
        ('duplicate round rejected', lambda: pipeline.run_pipelined([jobs[0], jobs[0]], 2, probe_play)),
        ('insufficient worker capacity rejected', lambda: pipeline.run_pipelined(jobs, 1, probe_play))]:
        try:
            action()
        except ValueError:
            cases.append(label)
        else:
            raise AssertionError(label)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        output = root / 'pair-001'
        (root / 'state.json').write_text(json.dumps({'fingerprints': {'clock_runner': 'other'}}))
        try:
            pipeline.check_output_frozen(output)
        except RuntimeError:
            assert not output.exists()
            cases.append('different frozen study rejected before creating output')
        else:
            raise AssertionError('Existing frozen study accepted')
        (root / 'state.json').unlink()
        output.mkdir()
        (output / 'settings.json').write_text(json.dumps({'jobs': []}))
        try:
            pipeline.check_output_frozen(output)
        except RuntimeError:
            cases.append('legacy batch rejected before reuse')
        else:
            raise AssertionError('Legacy scheduling accepted')
        config = configuration(output, 1)
        config['max_plies'] = 1
        with patch.object(chess.engine.SimpleEngine, 'popen_uci', side_effect=[Engine('e2e4'), Engine('e7e5')]):
            report = pipeline.run_game(config)
        assert report['scheduling'] == pipeline.SCHEDULING and report['headers']['Scheduling'] == pipeline.SCHEDULING
        with Path(config['output']).with_suffix('.pgn').open() as stream:
            game = chess.pgn.read_game(stream)
        evidence = {key: value for key, value in report.items() if key not in ('tested_uci_settings', 'opponent_uci_settings')}
        verify_game(evidence, game)
        cases.append('game evidence records queue method and preserves clock/referee semantics')
        legacy = copy.deepcopy(report)
        legacy.pop('scheduling')
        Path(config['output']).with_suffix('.json').write_text(json.dumps(legacy))
        with patch.object(chess.engine.SimpleEngine, 'popen_uci', side_effect=AssertionError('Unexpected engine launch')):
            try:
                pipeline.run_game(config)
            except RuntimeError:
                cases.append('missing scheduling provenance rejects cached game before engine launch')
            else:
                raise AssertionError('Old scheduling cache accepted')
    print(json.dumps({'status': 'passed', 'cases': cases, 'engine_searches': 0,
                      'probe_game_intervals': results,
                      'limitations': 'Sleeping probes and mocked UCI only; throughput and strength need actual validation.'}))


if __name__ == '__main__':
    main()
