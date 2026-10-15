"""Check optional deadlines and safe handoff without chess searches. GPL-3.0-or-later."""
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from deadline_policy import deadline_timestamp
import queue_runtime
import handoff

spec = importlib.util.spec_from_file_location('new_exact_guard', ROOT / 'safety/watch.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class DeadlineAndHandoffChecks(unittest.TestCase):
    def test_cancelled_deadline_has_no_wall_clock_expiry(self):
        self.assertTrue(math.isinf(deadline_timestamp(None)))
        self.assertGreater(deadline_timestamp(None), deadline_timestamp('2026-10-08T05:20:00+00:00'))

    def test_legacy_deadline_timezone_is_preserved(self):
        self.assertEqual(deadline_timestamp('2026-10-08T07:20:00+02:00'),
                         deadline_timestamp('2026-10-08T05:20:00+00:00'))
        for value in ('2026-10-08T07:20:00', 'bad', 0, False):
            with self.assertRaises(ValueError):
                deadline_timestamp(value)

    def test_no_deadline_queue_runs_finite_stages_and_keeps_pause_boundary(self):
        for pause in (False, True):
            with self.subTest(pause=pause), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                stages = [{'name': 'clock-fixture', 'safe_boundary_after': False,
                           'minimum_remaining_seconds': 2400,
                           'command': [sys.executable, '-c', 'import time; time.sleep(.15)']},
                          {'name': 'audit-fixture', 'safe_boundary_after': True,
                           'command': [sys.executable, '-c', 'import time; time.sleep(.15)']},
                          {'name': 'later-fixture', 'safe_boundary_after': True,
                           'command': [sys.executable, '-c', 'import time; time.sleep(.15)']}]
                if pause:
                    stages[0]['command'] = [sys.executable, '-c',
                        'import pathlib,time;pathlib.Path(' + repr(str(root / 'pause_at_boundary')) + ').touch();time.sleep(.15)']
                plan = {'output': str(root), 'lock_paths': [str(root / 'runner.lock')],
                        'deadline_utc': None, 'authorization': 'fixture', 'frozen_sha256': {},
                        'stages': stages, 'poll_seconds': .1}
                path = root / 'plan.json'; path.write_text(json.dumps(plan))
                with patch.object(sys, 'argv', ['fixture', '--plan', str(path)]), \
                        patch.object(queue_runtime, 'progress', return_value={'by_phase': {}, 'games': []}):
                    queue_runtime.main()
                state = json.loads((root / 'state.json').read_text())
                self.assertEqual(state['phase'], 'paused_at_boundary' if pause else 'completed')
                self.assertEqual(state['completed_stages'], [stage['name'] for stage in stages[:2 if pause else 3]])
                self.assertIsNone(state['child'])
                self.assertIsNone(state['deadline_utc'])

    def test_import_alias_cannot_be_repointed_even_with_identical_bytes(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            first, second = root / 'first', root / 'second'
            first.mkdir(); second.mkdir()
            for target in (first, second):
                (target / 'game.json').write_text('same bytes')
            alias = root / 'import'; alias.symlink_to(first, target_is_directory=True)
            plan = {'inherited_symlinks': {str(alias): str(first)},
                    'frozen_sha256': {str(first / 'game.json'): hashlib.sha256(b'same bytes').hexdigest()}}
            queue_runtime.verify_inputs(plan)
            alias.unlink(); alias.symlink_to(second, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, 'alias changed'):
                queue_runtime.verify_inputs(plan)

    def test_guard_tracks_exact_orphans_and_rejects_unrelated_or_reused_pids(self):
        launch = {'pid': 10, 'birth': '100', 'command': ['python', 'queue']}
        child = {'pid': 11, 'birth': '101', 'command': ['python', 'clock']}
        table = {10: {'birth': '100', 'args': launch['command'], 'ppid': 1},
                 11: {'birth': '101', 'args': child['command'], 'ppid': 10},
                 12: {'birth': '102', 'args': ['stockfish'], 'ppid': 11},
                 99: {'birth': '200', 'args': ['stockfish'], 'ppid': 1}}
        known = {}
        self.assertEqual(guard.observe(table, launch, {'child': child}, [child['command']], known), {10, 11, 12})
        self.assertNotIn(99, known)
        orphan = {12: dict(table[12], ppid=1), 99: table[99]}
        self.assertEqual(guard.observe(orphan, launch, {}, [], known), {12})
        orphan[12]['birth'] = 'reused'
        self.assertEqual(guard.observe(orphan, launch, {}, [], known), set())
        self.assertEqual(guard.observe(table, dict(launch, command=['unrelated']), {}, [], {}), set())

    def test_boundary_rejects_incomplete_audits_or_faults(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            plan = {'stages': [{'name': str(n)} for n in range(5)], 'judge_sha256': 'judge'}
            state = {'phase': 'paused_at_boundary', 'child': None, 'completed_stages': [str(n) for n in range(5)]}
            (root / 'state.json').write_text(json.dumps(state)); (root / 'pause_at_boundary').touch()
            row = {'wins': 0, 'draws': 2, 'losses': 0, 'own_moves': 5, 'checked_moves': 5,
                   'audit_complete': True, 'mistakes': 0, 'blunders': 0}
            evidence = {'by_study': {}, 'games': [], 'unscored_games': []}
            for bias in (32, 64):
                study = root / f'training-{bias}'
                target = study / 'pair-001/audit'; target.mkdir(parents=True)
                (target / 'summary.json').write_text(json.dumps({'status': 'completed', 'judge_binary_sha256': 'judge'}))
                evidence['by_study'][str(study)] = {'baseline': dict(row), 'candidate': dict(row)}
            with patch.object(handoff.counter_queue, 'progress', return_value=evidence):
                handoff.boundary_evidence(root, plan)
                evidence['by_study'][str(root / 'training-64')]['candidate']['audit_complete'] = False
                with self.assertRaisesRegex(ValueError, 'incomplete'):
                    handoff.boundary_evidence(root, plan)
                evidence['by_study'][str(root / 'training-64')]['candidate']['audit_complete'] = True
                evidence['games'].append({'study': str(root / 'training-64'), 'termination': 'TIME_FORFEIT'})
                with self.assertRaisesRegex(ValueError, 'fault'):
                    handoff.boundary_evidence(root, plan)

    def test_handoff_lock_probes_never_bypass_a_live_owner(self):
        import fcntl
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'runner.lock'
            self.assertTrue(handoff.locks_available([str(path)]))
            with path.open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertFalse(handoff.locks_available([str(path)]))
            self.assertTrue(handoff.locks_available([str(path)]))


if __name__ == '__main__':
    unittest.main(verbosity=2)
