"""Exercise handoff gates, report merging and owned-tree stopping without engines. GPL-3.0-or-later."""
import copy
import hashlib
import json
import os
import signal
import tempfile
from pathlib import Path
from unittest.mock import patch

import cutoff_watch_multi as guard
from check_report_evidence import fixture
from combined_report import merge_studies
from pipeline_handoff import training_gate
from summarize_study import summarize


def main():
    cases = []
    stats = {'wins': 0, 'draws': 2, 'losses': 0, 'audit_complete': True,
             'mistakes_detected': 0, 'blunders_detected': 0}
    report = {'by_phase_and_variant': {'training': {'baseline': copy.deepcopy(stats), 'candidate': copy.deepcopy(stats)}}}
    assert training_gate(report)[0]
    cases.append('equal clean training result continues unproven frozen comparison')
    failed = copy.deepcopy(report)
    failed['by_phase_and_variant']['training']['candidate'].update(draws=1, losses=1)
    assert not training_gate(failed)[0]
    cases.append('lower training score excludes candidate from next stage')
    failed = copy.deepcopy(report)
    failed['by_phase_and_variant']['training']['candidate']['blunders_detected'] = 1
    assert not training_gate(failed)[0]
    cases.append('candidate-only detected training error excludes candidate')
    failed['by_phase_and_variant']['training']['candidate']['audit_complete'] = False
    try:
        training_gate(failed)
    except ValueError:
        cases.append('incomplete audits cannot drive rejection or promotion')
    else:
        raise AssertionError('Incomplete gate accepted')
    with tempfile.TemporaryDirectory() as temporary:
        roots = [Path(temporary) / 'initial', Path(temporary) / 'followon']
        for root in roots:
            root.mkdir()
            for index, (variant, color) in enumerate([('baseline', 'white'), ('candidate', 'white'),
                                                    ('baseline', 'black'), ('candidate', 'black')]):
                fixture(root, index + 1, variant, color)
        summaries = [summarize(root) for root in roots]
        merged = merge_studies(summaries)
        assert len(merged['games']) == 8 and len(merged['paired_opening_comparisons']) == 2
        assert merged['by_phase_and_variant']['heldout']['baseline']['checked_moves'] == 8
        cases.append('matching stages merge each game once and retain paired provenance')
        try:
            merge_studies([summaries[0], summaries[0]])
        except ValueError:
            cases.append('duplicated stage rejected')
        else:
            raise AssertionError('Duplicate games counted')
        # A second stage can be internally valid yet use different resources.
        for path in roots[1].glob('pair-*/game-*.json'):
            data = json.loads(path.read_text())
            data.update(hash_mb_each=64)
            data['tested_uci_settings']['Hash'] = data['opponent_uci_settings']['Hash'] = 64
            path.write_text(json.dumps(data))
            audit_path = path.parent / 'audit' / path.name
            audit = json.loads(audit_path.read_text())
            audit['source_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            audit_path.write_text(json.dumps(audit))
        summaries[1] = summarize(roots[1])
        try:
            merge_studies(summaries)
        except ValueError:
            cases.append('different stage resources cannot be pooled')
        else:
            raise AssertionError('Different resources pooled')
    def process(parent, group, arguments):
        return {'ppid': parent, 'pgid': group, 'birth': str(parent + group), 'args': ['python', *arguments]}
    table = {
        501: process(1, 501, ['/workspace/aurora-stockfish/tools/night-study/overnight.py', '--output', str(guard.ROOT / 'original-study')]),
        502: process(501, 502, ['/workspace/aurora-stockfish/tools/night-study/clock_match.py']),
        503: process(502, 502, ['/workspace/aurora-stockfish/tools/night-study/clock_match.py']),
        504: process(503, 502, ['/workspace/scratch/stockfish-19-source/src/stockfish-19-native']),
        601: process(1, 601, ['/workspace/aurora-stockfish/tools/night-study/pipelined_overnight.py', '--output', str(guard.PIPELINED)]),
        602: process(601, 602, ['/workspace/aurora-stockfish/tools/night-study/pipelined_clock_match.py']),
        603: process(602, 602, ['/workspace/aurora-stockfish/bin/wetmeat-linux-avx512']),
        701: process(1, 701, ['/workspace/aurora-stockfish/tools/night-study/pipeline_handoff.py', '--output', str(guard.ROOT)]),
        888: process(1, 502, ['unrelated process sharing a group']),
        800: process(1, 800, ['/workspace/aurora-stockfish/tools/night-study/pipelined_overnight.py', '--output', '/workspace/unrelated']),
    }
    selected = guard.descendants(table, guard.owned_roots(table))
    assert selected == {501, 502, 503, 504, 601, 602, 603, 701}
    cases.append('only exact authorized outputs and their descendants are selected')
    frozen, events = set(), []
    def kill(pid, sig):
        events.append(('pid', pid, sig))
        if sig == signal.SIGSTOP:
            frozen.add(pid)
        if sig == signal.SIGTERM:
            assert selected <= frozen
    def killpg(group, sig):
        events.append(('group', group, sig))
        if sig == signal.SIGTERM:
            assert selected <= frozen
    survivors = {pid: value for pid, value in table.items() if pid not in selected}
    with patch.object(guard, 'processes', side_effect=[table, table, survivors]), \
         patch.object(guard.os, 'kill', side_effect=kill), \
         patch.object(guard.os, 'killpg', side_effect=killpg), \
         patch.object(guard.time, 'sleep'):
        result = guard.stop_jobs()
    assert set(result['identified_job_pids']) == selected
    assert not any(kind == 'pid' and pid in (800, 888) for kind, pid, sig in events)
    assert not any(kind == 'group' and group == 502 for kind, group, sig in events)
    cases.append('all selected workers freeze before any engine is stopped')
    cases.append('unrelated PIDs and mixed process groups are never signaled')
    print(json.dumps({'status': 'passed', 'cases': cases, 'engine_searches': 0,
                      'real_processes_signaled': 0, 'limitations': 'Fixtures only; no engine strength evidence.'}))


if __name__ == '__main__':
    main()
