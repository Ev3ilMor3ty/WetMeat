"""Check bounded continuation ownership and checkpoint safety. GPL-3.0-or-later."""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from continue_original import digest, processes, progress, stop_child, verify_inputs

SCRIPT = Path(__file__).with_name('continue_original.py')


def await_file(path):
    end = time.monotonic() + 5
    while not path.exists() and time.monotonic() < end:
        time.sleep(.02)
    if not path.exists():
        raise AssertionError(f'Missing fixture checkpoint: {path}')


def make_plan(root, stages):
    plan = {'output': str(root), 'authorization': 'test fixture only',
            'deadline_utc': (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=2)).isoformat(),
            'frozen_sha256': {}, 'binary_sha256': {}, 'judge_sha256': 'test',
            'studies': [], 'lock_paths': [str(root / 'runner.lock')],
            'game_settings': {}, 'common_uci_settings': {}, 'audit_settings': {},
            'poll_seconds': .05, 'stages': stages}
    path = root / 'plan.json'
    path.write_text(json.dumps(plan))
    return plan, path


class ContinuationChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='wetmeat-continuation-check-')
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def run_controller(self, plan):
        return subprocess.run([sys.executable, str(SCRIPT), '--plan', str(plan)],
                              capture_output=True, text=True, timeout=8)

    def test_changed_input_rejected_before_launch(self):
        frozen = self.root / 'frozen'
        frozen.write_text('original')
        plan, path = make_plan(self.root, [])
        plan['frozen_sha256'] = {str(frozen): digest(frozen)}
        frozen.write_text('changed')
        path.write_text(json.dumps(plan))
        result = self.run_controller(path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Frozen input changed', result.stderr)
        self.assertFalse((self.root / 'state.json').exists())

    def test_expired_window_cannot_start_stage(self):
        marker = self.root / 'launched'
        plan, path = make_plan(self.root, [{'name': 'never', 'command':
            [sys.executable, '-c', f'from pathlib import Path; Path({str(marker)!r}).touch()']}])
        plan['deadline_utc'] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)).isoformat()
        path.write_text(json.dumps(plan))
        self.assertNotEqual(self.run_controller(path).returncode, 0)
        self.assertFalse(marker.exists())

    def test_lock_blocks_duplicate_controller(self):
        marker = self.root / 'started'
        _, path = make_plan(self.root, [{'name': 'fixture', 'command': [sys.executable, '-c',
            f'from pathlib import Path; import time; Path({str(marker)!r}).touch(); time.sleep(30)']}])
        owner = subprocess.Popen([sys.executable, str(SCRIPT), '--plan', str(path)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            await_file(marker)
            state_before = json.loads((self.root / 'state.json').read_text())
            result = self.run_controller(path)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads((self.root / 'state.json').read_text())['pid'], state_before['pid'])
        finally:
            owner.terminate()
            owner.wait(timeout=8)
        self.assertEqual(json.loads((self.root / 'state.json').read_text())['phase'], 'cancelled_checkpoint_saved')

    def test_shutdown_is_scoped_and_prevents_false_forfeit(self):
        marker = self.root / 'child.pid'
        false_forfeit = self.root / 'false-forfeit'
        worker_code = ('import subprocess,sys; from pathlib import Path; '
            'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
            f'Path({str(marker)!r}).write_text(str(child.pid)); '
            'child.wait(); '
            f'Path({str(false_forfeit)!r}).write_text("engine error scored")')
        worker = subprocess.Popen([sys.executable, '-c', worker_code], start_new_session=True)
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
        try:
            await_file(marker)
            birth = processes()[worker.pid]['birth']
            self.assertEqual(stop_child(worker, 'different-birth')['selected'], [])
            self.assertIsNone(worker.poll())
            stopped = stop_child(worker, birth)
            self.assertIn(worker.pid, stopped['selected'])
            self.assertIn(int(marker.read_text()), stopped['selected'])
            self.assertFalse(false_forfeit.exists())
            self.assertIsNone(unrelated.poll())
        finally:
            if worker.poll() is None:
                stop_child(worker, processes()[worker.pid]['birth'])
            unrelated.terminate()
            unrelated.wait(timeout=5)

    def test_exception_after_launch_stops_owned_tree(self):
        study = self.root / 'study'
        pair = study / 'pair-001'
        pair.mkdir(parents=True)
        checkpoint = pair / 'game-001.json'
        code = ('from pathlib import Path; import time; '
                f'Path({str(checkpoint)!r}).write_text("{{\\\"tested_points\\\":0.5}}"); '
                f'Path({str(checkpoint.with_suffix(".pgn"))!r}).touch(); time.sleep(30)')
        plan, path = make_plan(self.root, [{'name': 'broken-fixture', 'command': [sys.executable, '-c', code]}])
        plan['studies'] = [str(study)]
        path.write_text(json.dumps(plan))
        result = self.run_controller(path)
        state = json.loads((self.root / 'state.json').read_text())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state['phase'], 'controller_error_checkpoint_saved')
        self.assertTrue(state['cleanup']['selected'])
        self.assertTrue(all(pid not in processes() for pid in state['cleanup']['selected']))

    def test_pause_waits_for_corresponding_audit(self):
        pause = self.root / 'pause_at_boundary'
        audit_done = self.root / 'audit-done'
        forbidden = self.root / 'should-not-start'
        stages = [
            {'name': 'clock', 'safe_boundary_after': False,
             'command': [sys.executable, '-c', f'from pathlib import Path; Path({str(pause)!r}).touch()']},
            {'name': 'audit', 'safe_boundary_after': True,
             'command': [sys.executable, '-c', f'from pathlib import Path; Path({str(audit_done)!r}).touch()']},
            {'name': 'next-batch', 'command': [sys.executable, '-c',
             f'from pathlib import Path; Path({str(forbidden)!r}).touch()']},
        ]
        _, path = make_plan(self.root, stages)
        self.assertEqual(self.run_controller(path).returncode, 0)
        self.assertTrue(audit_done.exists())
        self.assertFalse(forbidden.exists())
        self.assertEqual(json.loads((self.root / 'state.json').read_text())['completed_stages'], ['clock', 'audit'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
