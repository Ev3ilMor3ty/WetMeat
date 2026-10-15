"""Check setting provenance, guardrail evidence and training selection. GPL-3.0-or-later."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, '/workspace/aurora-stockfish/tools/night-study')
from check_report_evidence import fixture
from export_failures import extract
from counter_queue import choose_training, empty, progress
from trial_clock import fresh_openings


class QueueChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='wetmeat-setting-check-')
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def data(self, variant='candidate'):
        study = self.root / 'study'; study.mkdir()
        path, game, audit_path, audit = fixture(study, 1, variant, 'white')
        game.update(draw_rule=None, max_plies=500, cpu=int(variant == 'candidate'))
        game['tested_uci_settings'].update({'Skill Level': 20, 'UCI_LimitStrength': False, 'SyzygyPath': ''})
        raw = json.dumps(game).encode(); path.write_bytes(raw)
        audit['source_sha256'] = hashlib.sha256(raw).hexdigest(); audit_path.write_text(json.dumps(audit))
        plan = {'output': str(self.root), 'trial_settings': [32, 64],
                'stable_binary_sha256': 'baseline', 'candidate_binary_sha256': 'candidate',
                'study_contexts': [{'path': str(study), 'phase': game['phase'], 'bias': 16, 'openings': [game['opening']]}],
                'game_settings': {k: game[k] for k in ['opponent_binary_sha256', 'base_seconds', 'increment_seconds', 'hash_mb_each', 'threads_each', 'draw_rule', 'move_overhead_ms_each', 'max_plies']},
                'common_uci_settings': game['opponent_uci_settings'], 'audit_settings': audit['settings']}
        return study, path, game, audit_path, audit, plan

    def test_illegal_or_reused_training_opening_rejected(self):
        path = self.root / 'openings.json'
        for sequence in ['e2e5', 'e2e4 e7e5 g1f3 b8c6 f1b5 a7a6']:
            path.write_text(json.dumps({'openings': [sequence]}))
            with self.assertRaises(ValueError): fresh_openings(path)

    def test_setting64_cannot_inherit_setting16_game(self):
        _, _, _, _, _, plan = self.data()
        plan['study_contexts'][0]['bias'] = 64
        with self.assertRaisesRegex(RuntimeError, 'configuration identity'):
            progress(plan)

    def test_full_strength_guard_and_partial_rates(self):
        _, path, game, audit_path, audit, plan = self.data()
        audit['status'] = 'running'; audit['moves'] = audit['moves'][:1]
        audit_path.write_text(json.dumps(audit))
        stats = progress(plan)['by_phase'][game['phase']]['draw-aversion-16']
        self.assertFalse(stats['audit_complete']); self.assertIsNone(stats['blunder_rate'])
        game['opponent_uci_settings']['UCI_LimitStrength'] = True
        path.write_text(json.dumps(game))
        with self.assertRaisesRegex(RuntimeError, 'UCI resources/strength'):
            progress(plan)

    def test_duplicate_physical_game_is_rejected(self):
        study, _, _, _, _, plan = self.data()
        alias = self.root / 'alias'; alias.symlink_to(study, target_is_directory=True)
        second = dict(plan['study_contexts'][0], path=str(alias))
        plan['study_contexts'].append(second)
        with self.assertRaisesRegex(RuntimeError, 'counted twice'):
            progress(plan)

    def test_exporter_requires_complete_fingerprints(self):
        study, path, game, audit_path, audit, _ = self.data('baseline')
        # Reproduce the completed batch's exact metadata-only failure.
        (study/'state.json').write_text(json.dumps({'fingerprints': {'clock_runner': 'test'}}))
        with self.assertRaises(KeyError): extract(study, include_heldout=True)
        full = {'fingerprints': {'engine': 'baseline', 'candidate': 'candidate', 'opponent': 'fixture-judge',
                                  'candidate_draw_aversion': 32, 'clock_runner': 'test'}}
        (study/'state.json').write_text(json.dumps(full))
        self.assertFalse(extract(study, include_heldout=True)['cases'])

    def test_selection_rejects_regressions_and_heldout_tuning(self):
        plan = {'candidate_binary_sha256': 'candidate', 'study_contexts': [
            {'path': 'training32', 'bias': 32, 'phase': 'training', 'selectable_training': True},
            {'path': 'training64', 'bias': 64, 'phase': 'training', 'selectable_training': True}]}
        drawn = {**empty(), 'draws': 4, 'own_moves': 20, 'checked_moves': 20}
        evidence = {'games': [], 'by_study': {key: {'baseline': dict(drawn), 'candidate': dict(drawn)}
                                               for key in ['training32', 'training64']}}
        self.assertEqual(choose_training(plan, evidence)['draw_aversion'], 32)
        evidence['by_study']['training32']['candidate'].update(losses=1, draws=3)
        self.assertEqual(choose_training(plan, evidence)['draw_aversion'], 64)
        evidence['by_study']['training64']['candidate']['blunders'] = 1
        self.assertEqual(choose_training(plan, evidence)['draw_aversion'], 0)
        plan['study_contexts'][0]['phase'] = 'heldout'
        with self.assertRaisesRegex(RuntimeError, 'training data only'):
            choose_training(plan, evidence)


if __name__ == '__main__':
    unittest.main(verbosity=2)
