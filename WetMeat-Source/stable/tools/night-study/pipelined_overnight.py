"""Restartable bounded follow-on study with per-CPU queues. SPDX-License-Identifier: GPL-3.0-or-later."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

OPENING_SCHEDULE = [4, 5, 3, 6, 7, 8, 9, 10, 11, 2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def bounded_run(command, log, timeout):
    """Terminate the whole owned process group, including engine grandchildren."""
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                               start_new_session=True)
    try:
        code = process.wait(timeout=timeout)
        if code:
            raise subprocess.CalledProcessError(code, command)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine', type=Path, required=True)
    p.add_argument('--candidate', type=Path)
    p.add_argument('--candidate-draw-aversion', type=int, default=0)
    p.add_argument('--opponent', type=Path, required=True)
    p.add_argument('--clock-runner', type=Path, required=True)
    p.add_argument('--audit-runner', type=Path)
    p.add_argument('--python', default=sys.executable)
    p.add_argument('--pairs', type=int, default=48)
    p.add_argument('--hours', type=float, default=10)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if not 0 <= args.candidate_draw_aversion <= 64 or (args.candidate_draw_aversion and not args.candidate):
        p.error('Draw aversion requires a candidate and must be in 0..64')
    if args.hours <= 0 or args.pairs <= 0:
        p.error('Positive limits are required')
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = (root / 'runner.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('Another overnight runner already owns this study.', flush=True)
        return
    fingerprints = {'engine': digest(args.engine), 'opponent': digest(args.opponent),
                    'runner': digest(Path(__file__)),
                    'opening_definitions': digest(args.clock_runner.with_name('match.py')),
                    'candidate': digest(args.candidate) if args.candidate else None,
                    'clock_runner': digest(args.clock_runner),
                    'audit_runner': digest(args.audit_runner) if args.audit_runner else None,
                    'candidate_draw_aversion': args.candidate_draw_aversion}
    state_path = root / 'state.json'
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state['fingerprints'] != fingerprints:
            raise RuntimeError('A frozen input changed; use a new output directory.')
    else:
        state = {'fingerprints': fingerprints, 'completed_pairs': [], 'audited_pairs': [],
                 'games': [], 'clock': '600+5', 'threads_each': 1, 'hash_mb_each': 128,
                 'status': 'created', 'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                 'training_opening_indices': [2, 3], 'heldout_opening_indices': list(range(4, 12)),
                 'opening_schedule': OPENING_SCHEDULE,
                 'limitations': 'Original Stockfish-derived WetMeat versus full-strength Stockfish. Candidate draw aversion is an unproven hypothesis, frozen before validation; no promotion or superiority is implied.'}
    state['pid'] = os.getpid()
    deadline = time.monotonic() + args.hours * 3600

    def verify_inputs():
        current = {'engine': digest(args.engine), 'candidate': digest(args.candidate) if args.candidate else None,
                   'runner': digest(Path(__file__)),
                   'opening_definitions': digest(args.clock_runner.with_name('match.py')),
                   'opponent': digest(args.opponent), 'clock_runner': digest(args.clock_runner),
                   'audit_runner': digest(args.audit_runner) if args.audit_runner else None,
                   'candidate_draw_aversion': args.candidate_draw_aversion}
        if current != fingerprints:
            raise RuntimeError('Frozen input changed during the study; stopping at a safe boundary.')

    def save(status):
        state['status'] = status
        state['updated_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        points = [g['tested_points'] for g in state['games'] if g['tested_points'] is not None]
        state['score'] = {'wins': points.count(1), 'draws': points.count(0.5),
                          'losses': points.count(0), 'unfinished': len(state['games']) - len(points)}
        state['score_by_variant'] = {}
        for name in sorted({g.get('variant', 'baseline') for g in state['games']}):
            selected = [g['tested_points'] for g in state['games'] if g.get('variant', 'baseline') == name]
            state['score_by_variant'][name] = {'wins': selected.count(1), 'draws': selected.count(.5),
                                              'losses': selected.count(0), 'unfinished': selected.count(None)}
        write_json(state_path, state)

    def audit_pair(pair):
        verify_inputs()
        if not args.audit_runner or pair in state['audited_pairs']:
            return True
        if time.monotonic() + 60 > deadline:
            save('budget_exhausted_audit_checkpoints_saved')
            return False
        directory = root / f'pair-{pair + 1:03d}'
        audit = directory / 'audit'
        save(f'auditing_pair_{pair + 1}')
        print(f'Auditing all WetMeat moves in rapid pair {pair + 1}', flush=True)
        with (directory / 'audit.log').open('a') as log:
            try:
                bounded_run([args.python, str(args.audit_runner), '--games', str(directory),
                             '--judge', str(args.opponent.resolve()), '--tested-only', '--workers', '2',
                             '--min-nodes', '1000000', '--output', str(audit)],
                            log, max(1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                save('budget_exhausted_audit_checkpoints_saved')
                return False
        summary = json.loads((audit / 'summary.json').read_text())
        if summary['status'] != 'completed' or summary['judge_binary_sha256'] != fingerprints['opponent']:
            raise RuntimeError('Invalid audit summary')
        state.setdefault('audits', {})[str(pair + 1)] = summary['by_engine']
        totals = {'moves': 0, 'mistakes': 0, 'blunders': 0, 'loss_cp_sum': 0}
        by_engine = {}
        for statistics in state['audits'].values():
            for name, engine_stats in statistics.items():
                individual = by_engine.setdefault(name, {field: 0 for field in totals})
                for field in totals:
                    totals[field] += engine_stats[field]
                    individual[field] += engine_stats[field]
        if totals['moves']:
            totals['mistake_rate'] = totals['mistakes'] / totals['moves']
            totals['blunder_rate'] = totals['blunders'] / totals['moves']
        state['audited_error_counts'] = totals
        for stats in by_engine.values():
            if stats['moves']:
                stats['mistake_rate'] = stats['mistakes'] / stats['moves']
                stats['blunder_rate'] = stats['blunders'] / stats['moves']
        state['audited_error_counts_by_engine'] = by_engine
        state['audited_pairs'].append(pair)
        save('running_matches')
        return True

    save('running_matches')
    for pair in range(args.pairs):
        verify_inputs()
        if (root / 'pause_at_boundary').exists():
            save('paused_at_pair_boundary')
            print('Paused safely; no clocked games remain running.', flush=True)
            return
        if pair in state['completed_pairs']:
            if not audit_pair(pair):
                return
            continue
        # Do not start a new full rapid pair close to the wall-time budget.
        if time.monotonic() + 2400 > deadline:
            break
        directory = root / f'pair-{pair + 1:03d}'
        summary = directory / 'summary.json'
        if not summary.exists():
            command = [args.python, str(args.clock_runner), '--engine', str(args.engine.resolve()),
                       '--opponent', str(args.opponent.resolve()), '--pairs', '1', '--base', '600',
                       '--increment', '5', '--hash', '128', '--workers', '2',
                       '--opening-offset', str(OPENING_SCHEDULE[pair % len(OPENING_SCHEDULE)]),
                       '--phase', 'training' if OPENING_SCHEDULE[pair % len(OPENING_SCHEDULE)] in (2, 3) else 'heldout',
                       '--output', str(directory)]
            if args.candidate:
                command += ['--candidate', str(args.candidate.resolve()),
                            '--candidate-draw-aversion', str(args.candidate_draw_aversion)]
            directory.mkdir(parents=True, exist_ok=True)
            save(f'running_pair_{pair + 1}')
            print(f'Running rapid pair {pair + 1}/{args.pairs}', flush=True)
            with (directory / 'match.log').open('a') as log:
                try:
                    bounded_run(command, log, max(1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    save('budget_exhausted_incomplete_pair')
                    return
        reports = [json.loads(path.read_text()) for path in sorted(directory.glob('game-*.json'))]
        if len(reports) != (4 if args.candidate else 2):
            raise RuntimeError(f'Incomplete paired study at {directory}')
        for report in reports:
            tested_sha = fingerprints['candidate'] if report.get('variant') == 'candidate' else fingerprints['engine']
            if report['tested_binary_sha256'] != tested_sha or report['opponent_binary_sha256'] != fingerprints['opponent']:
                raise RuntimeError('Game fingerprint mismatch')
        state['games'].extend({'pair': pair + 1, 'result': report['result'],
                               'phase': report['phase'],
                               'tested_points': report['tested_points'], 'termination': report['termination'],
                               'variant': report.get('variant', 'baseline'),
                               'tested_color': report['tested_color'], 'file': str(directory / f"game-{report['round']:03d}.json")}
                              for report in reports)
        state['completed_pairs'].append(pair)
        save('running_matches')
        # Complete each rapid pair before auditing; no judge/build competes
        # with either live game. Feedback becomes available between pairs.
        if not audit_pair(pair):
            return
    save('completed' if len(state['completed_pairs']) == args.pairs else 'budget_exhausted')
    print(json.dumps(state['score']), flush=True)


if __name__ == '__main__':
    main()
