"""Bounded original-WetMeat continuation; no engine tuning. GPL-3.0-or-later."""
from __future__ import annotations

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

import chess.pgn

from cutoff_watch_multi import descendants, processes
from verify_records import verify_audit, verify_game


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.session.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def verify_inputs(plan):
    for path, expected in plan['frozen_sha256'].items():
        if digest(path) != expected:
            raise RuntimeError(f'Frozen input changed: {path}')


def stop_child(process, birth, observed=None):
    """Freeze the exact child tree before stopping engines; never signal by PID alone."""
    table = processes()
    record = table.get(process.pid)
    roots = {pid for pid, old in (observed or {}).items()
             if pid in table and table[pid]['birth'] == old['birth']}
    if record is not None and record['birth'] == birth:
        roots.add(process.pid)
    if not roots:
        return {'selected': [], 'forced_kills': []}
    selected = descendants(table, roots)
    # Freeze parents first, then rescan for children created during that freeze.
    frozen = {}
    while selected - set(frozen):
        for pid in sorted(selected - set(frozen)):
            row = table.get(pid)
            if row is None:
                continue
            current_row = processes().get(pid)
            if current_row is None or current_row['birth'] != row['birth']:
                continue
            try:
                os.kill(pid, signal.SIGSTOP)
                frozen[pid] = row
            except ProcessLookupError:
                pass
        table = processes()
        selected = descendants(table, set(frozen))
    current = processes()
    selected = {pid for pid, old in frozen.items()
                if pid in current and current[pid]['birth'] == old['birth']}
    groups = {current[pid]['pgid'] for pid in selected if pid in current}
    safe = {group for group in groups if group != os.getpgrp()
            and all(pid in selected for pid, row in current.items() if row['pgid'] == group)}
    for group in safe:
        try:
            os.killpg(group, signal.SIGTERM)
            os.killpg(group, signal.SIGCONT)
        except ProcessLookupError:
            pass
    for pid in selected:
        row = current.get(pid)
        if row is None or row['pgid'] in safe:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            os.kill(pid, signal.SIGCONT)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    survivors = processes()
    killed = []
    for pid in selected:
        row = current.get(pid)
        if row and pid in survivors and survivors[pid]['birth'] == row['birth']:
            try:
                os.kill(pid, signal.SIGKILL)
                killed.append(pid)
            except ProcessLookupError:
                pass
    process.wait(timeout=5)
    return {'selected': sorted(selected), 'forced_kills': killed}


def progress(plan):
    phases = {}
    games = []
    for study in plan['studies']:
        for path in sorted(Path(study).glob('pair-*/game-*.json')):
            if not path.with_suffix('.pgn').exists():
                continue  # A newly completed result is still being written.
            game = json.loads(path.read_text())
            if game.get('tested_points') is None:
                continue
            variant = game['variant']
            if game['tested_binary_sha256'] != plan['binary_sha256'][variant]:
                raise RuntimeError('Game binary identity changed')
            if game['tested_options'] != ({'Draw Aversion': 16} if variant == 'candidate' else {}):
                raise RuntimeError('Game options changed')
            for key, expected in plan['game_settings'].items():
                if game.get(key) != expected:
                    raise RuntimeError(f'Game resource or opponent mismatch: {key}')
            for key, expected in plan['common_uci_settings'].items():
                if any(game[side].get(key) != expected for side in ('tested_uci_settings', 'opponent_uci_settings')):
                    raise RuntimeError(f'Applied UCI setting mismatch: {key}')
            with path.with_suffix('.pgn').open() as stream:
                recorded_moves = verify_game(game, chess.pgn.read_game(stream))
            moves = set(recorded_moves)
            audit_path = path.parent / 'audit' / path.name
            rows = []
            audit_complete = False
            if audit_path.exists():
                audit = json.loads(audit_path.read_text())
                if audit['settings'] != plan['audit_settings']:
                    raise RuntimeError('Audit settings changed')
                rows = verify_audit(audit, path.read_bytes(), game, recorded_moves)
                if len(rows) != len(audit['moves']):
                    raise RuntimeError('Audit includes unrequested opponent moves')
                audit_complete = audit['status'] == 'completed' and len(rows) == len(moves)
            statistics = phases.setdefault(game['phase'], {}).setdefault(variant, {
                'wins': 0, 'draws': 0, 'losses': 0, 'checked_moves': 0, 'own_moves': 0,
                'mistakes': 0, 'blunders': 0, 'shallow_judge_moves': 0, 'audit_complete': True})
            statistics[{1: 'wins', .5: 'draws', 0: 'losses'}[game['tested_points']]] += 1
            statistics['checked_moves'] += len(rows)
            statistics['own_moves'] += len(moves)
            statistics['mistakes'] += sum(row['category'] == 'mistake' for row in rows)
            statistics['blunders'] += sum(row['category'] == 'blunder' for row in rows)
            statistics['shallow_judge_moves'] += sum(row.get('oracle_depth_below_played', False) for row in rows)
            statistics['audit_complete'] &= audit_complete
            games.append({'file': str(path), 'study': str(study), 'phase': game['phase'], 'variant': variant,
                          'points': game['tested_points'], 'checked_moves': len(rows),
                          'own_moves': len(moves), 'audit_complete': audit_complete})
    for variants in phases.values():
        for row in variants.values():
            for name in ('mistake', 'blunder'):
                row[name + '_rate'] = row[name + 's'] / row['own_moves'] if row['audit_complete'] and row['own_moves'] else None
    return {'by_phase': phases, 'games': games,
            'limits': 'Finite common-depth shared-family estimates; correlated moves, tiny paired samples. No Elo or strength gain established.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    root = Path(plan['output'])
    locks = []
    for path in plan['lock_paths']:
        lock = Path(path).open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locks.append(lock)
    deadline = dt.datetime.fromisoformat(plan['deadline_utc']).timestamp()
    if time.time() >= deadline:
        raise RuntimeError('This bounded session expired; no new jobs started')
    verify_inputs(plan)
    state = {'pid': os.getpid(), 'birth': processes()[os.getpid()]['birth'],
             'authorization': plan['authorization'], 'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
             'deadline_utc': plan['deadline_utc'], 'completed_stages': [], 'phase': 'ready',
             'child': None, 'promoted_candidate': False, 'engine_changes': 0}
    cancelled = False

    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)

    def publish():
        state['updated_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        state['status'] = state['phase']
        write(root / 'state.json', state)
        write(root / 'progress.json', {'snapshot_utc': state['updated_utc'], 'phase': state['phase'], **progress(plan)})

    process = None
    identity = None
    observed = {}
    safe_boundary = True
    try:
        publish()
        for stage in plan['stages']:
            if cancelled or (safe_boundary and (root / 'pause_at_boundary').exists()):
                state['phase'] = 'paused_at_boundary'
                publish()
                return
            if deadline - time.time() < stage.get('minimum_remaining_seconds', 0):
                state['phase'] = 'insufficient_budget_at_boundary'
                publish()
                return
            if time.time() >= deadline:
                state['phase'] = 'budget_exhausted_at_boundary'
                publish()
                return
            verify_inputs(plan)
            state['phase'] = stage['name']
            with (root / (stage['name'] + '.log')).open('a') as log:
                process = subprocess.Popen(stage['command'], stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=True)
                identity = processes().get(process.pid)
                if identity is None:
                    code = process.wait()
                    raise RuntimeError(f'Stage failed before identity capture: {code}')
                state['child'] = {'pid': process.pid, 'birth': identity['birth'], 'pgid': identity['pgid'],
                                  'command': stage['command']}
                observed = {process.pid: identity}
                publish()
                while process.poll() is None:
                    table = processes()
                    observed.update({pid: table[pid] for pid in descendants(table, {process.pid}) if pid in table})
                    if cancelled or time.time() >= deadline:
                        state['cleanup'] = stop_child(process, identity['birth'], observed)
                        state['child'] = None
                        state['phase'] = 'cancelled_checkpoint_saved' if cancelled else 'budget_exhausted_checkpoints_saved'
                        publish()
                        return
                    try:
                        process.wait(timeout=min(plan.get('poll_seconds', 30), max(.01, deadline - time.time())))
                    except subprocess.TimeoutExpired:
                        publish()
                state['child'] = None
                if process.returncode:
                    state['cleanup'] = stop_child(process, identity['birth'], observed)
                    state['phase'] = 'stage_failed_checkpoint_saved'
                    state['failed_stage'] = stage['name']
                    state['exit_code'] = process.returncode
                    publish()
                    return
            verify_inputs(plan)
            state['completed_stages'].append(stage['name'])
            safe_boundary = stage.get('safe_boundary_after', True)
            if stage.get('audit_summary'):
                summary = json.loads(Path(stage['audit_summary']).read_text())
                if summary['status'] != 'completed' or summary['judge_binary_sha256'] != plan['judge_sha256']:
                    raise RuntimeError('Invalid final audit identity')
                if any(row['mistakes'] or row['blunders'] for row in summary['by_engine'].values()):
                    state['phase'] = 'detected_failure_requires_review'
                    publish()
                    return
            publish()
        state['phase'] = 'completed'
        publish()
    except Exception as error:
        if process is not None and identity is not None:
            state['cleanup'] = stop_child(process, identity['birth'], observed)
        state['phase'] = 'controller_error_checkpoint_saved'
        state['child'] = None
        state['error'] = f'{type(error).__name__}: {error}'
        state['updated_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        state['status'] = state['phase']
        write(root / 'state.json', state)
        raise


if __name__ == '__main__':
    main()
