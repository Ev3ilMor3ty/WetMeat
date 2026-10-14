#!/usr/bin/env python3
"""Save verified trial evidence and actual job identities; no searches. GPL-3.0-or-later.

Separate from the frozen queue: this only reads its evidence and writes checkpoint
metadata. It never launches, stops, resumes, selects or changes an engine.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def table():
    rows = {}
    for directory in Path('/proc').glob('[0-9]*'):
        try:
            fields = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
            args = [part.decode(errors='replace') for part in
                    (directory / 'cmdline').read_bytes().split(b'\0') if part]
            pid = int(directory.name)
            rows[pid] = {'args': args, 'state': fields[0], 'ppid': int(fields[1]),
                         'pgid': int(fields[2]), 'birth': fields[19],
                         'affinity': sorted(os.sched_getaffinity(pid))}
        except (OSError, ValueError):
            continue
    return rows


def matches(row, launch):
    return bool(row and row['state'] != 'Z' and row['args'] == launch['command']
                and row['birth'] == launch['birth'])


def capture(plan_path):
    plan = json.loads(plan_path.read_text())
    root = Path(plan['output'])
    plan_sha = digest(plan_path)
    source_checks = {}
    for name in ('ready.json', 'watch-ready.json'):
        manifest = json.loads((root / name).read_text())
        if manifest['plan_sha256'] != plan_sha:
            raise ValueError('Readiness manifest belongs to another plan')
        for path, sha in manifest['source_sha256'].items():
            source_checks[path] = digest(path) == sha
    if not all(source_checks.values()):
        raise ValueError('A frozen small source file changed')
    spec = importlib.util.spec_from_file_location('counter_readonly', root / 'tools/counter_queue.py')
    counter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(counter)
    evidence = counter.progress(plan)
    totals = {}
    for variants in evidence['by_phase'].values():
        for name, row in variants.items():
            target = totals.setdefault(name, {**dict.fromkeys(counter.FIELDS, 0), 'audit_complete': True})
            for field in counter.FIELDS:
                target[field] += row[field]
            target['audit_complete'] &= row['audit_complete']
    for row in totals.values():
        row['more_wins_than_losses_observed'] = row['wins'] > row['losses']
        for name in ('mistake', 'blunder'):
            row[name + '_rate'] = row[name + 's'] / row['own_moves'] if row['audit_complete'] and row['own_moves'] else None
    processes = table()
    launch = json.loads((root / 'launch.json').read_text())
    watch = json.loads((root / 'watch-launch.json').read_text())
    controller_live = matches(processes.get(launch['pid']), launch)
    guard_live = matches(processes.get(watch['pid']), watch)
    owned = {record['pid'] for record in (launch, watch) if matches(processes.get(record['pid']), record)}
    while True:
        added = {pid for pid, row in processes.items() if row['ppid'] in owned and pid not in owned}
        if not added:
            break
        owned |= added
    live = {str(pid): processes[pid] for pid in sorted(owned) if processes[pid]['state'] != 'Z'}
    locks = []
    lines = Path('/proc/locks').read_text().splitlines()
    for path in [*plan['lock_paths'], str(root / 'checkpoint-watch.lock')]:
        info = Path(path).stat()
        inode = f'{os.major(info.st_dev):02x}:{os.minor(info.st_dev):02x}:{info.st_ino}'
        owners = [int(line.split()[4]) for line in lines if inode in line.split()]
        expected = watch['pid'] if path.endswith('checkpoint-watch.lock') else launch['pid']
        locks.append({'path': path, 'owner_pids': owners, 'expected_owner_if_live': expected})
    native_names = {'wetmeat-linux-avx512', 'wetmeat-draw-aversion', 'stockfish-19-native'}
    outside = {str(pid): row for pid, row in processes.items()
               if row['args'] and Path(row['args'][0]).name in native_names
               and pid not in owned and row['state'] != 'Z'}
    state = json.loads((root / 'state.json').read_text())
    clocked_games = sum(bool(row['args']) and Path(row['args'][0]).name in
                        {'wetmeat-linux-avx512', 'wetmeat-draw-aversion'} for row in live.values())
    native_sf = sum(bool(row['args']) and Path(row['args'][0]).name == 'stockfish-19-native' for row in live.values())
    return {'snapshot_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'plan_sha256': plan_sha,
            'phase': state['phase'], 'controller_live': controller_live, 'guard_live': guard_live,
            'controller_pid': launch['pid'], 'controller_birth': launch['birth'],
            'guard_pid': watch['pid'], 'guard_birth': watch['birth'],
            'clocked_games': clocked_games, 'judge_workers_active': native_sf if not clocked_games else 0,
            'live_processes': live, 'unowned_engine_processes': outside, 'lock_owners': locks,
            'small_frozen_source_checks': source_checks,
            'large_binary_package_verification': 'Not repeated during active searches; the frozen controller verifies inputs at every stage boundary.',
            'deadline_utc': plan['deadline_utc'], 'by_configuration': totals,
            'by_phase': evidence['by_phase'], 'completed_games': len(evidence['games']),
            'checked_moves': sum(row['checked_moves'] for row in totals.values()),
            'own_moves': sum(row['own_moves'] for row in totals.values()),
            'paired_comparisons': evidence['paired_comparisons'], 'unscored_games': evidence['unscored_games'],
            'more_wins_than_losses_observed': any(row['more_wins_than_losses_observed'] for row in totals.values()),
            'source_progress': str(root / 'progress.json'), 'engine_source_changes': 0,
            'new_engine_searches_or_test_jobs': 0, 'candidate_adoption': False, 'limits': evidence['limits']}


def save(path, value, plan):
    if str(path) in plan['frozen_sha256']:
        raise ValueError('Checkpoint would overwrite a frozen input')
    temporary = path.with_suffix(path.suffix + '.checkpoint.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def report(data):
    active = 'active' if data['controller_live'] else 'not active'
    lines = ['# WetMeat measured results', '', 'Snapshot: ' + data['snapshot_utc'], '',
             f"The verified controller is {active}. Saved phase: {data['phase']}. "
             f"Live clocked games: {data['clocked_games']}; judge processes: {data['judge_workers_active']}.", '',
             '| Configuration | Wins | Draws | Losses | Own moves checked/total | Detected mistakes/blunders |',
             '|---|---:|---:|---:|---:|---:|']
    for name, row in data['by_configuration'].items():
        lines.append(f"| {name} | {row['wins']} | {row['draws']} | {row['losses']} | "
                     f"{row['checked_moves']}/{row['own_moves']} | {row['mistakes']}/{row['blunders']} |")
    lines += ['', 'Scope: completed matched original-engine games from the October6–8 studies. '
              'Configurations and training/heldout phases remain separate in the JSON. Live and interrupted '
              'games are excluded; independent-rewrite results and older short-clock games are separate.', '',
              'Stockfish19 used full skill20 with no Elo limit. Both sides used actual10+5, one thread, '
              '128MB hash and30ms overhead, no ponder or tablebases, identical reached-draw rules and rotating CPUs. '
              'No candidate is adopted. A sample lead, if one appears, still requires completing the predeclared validation.', '',
              'Earlier complete audit samples remain valid. Pending moves withhold the full rate for that configuration. '
              'The preserved247-move sample contains155stable and92older timing-candidate moves; new settings inherit none of it.', '',
              data['limits'], '', 'The user cancelled the fixed stop time. The current frozen queue remains finite and checkpointed. '
              'Future model/workspace availability is not guaranteed.', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    root = Path(plan['output'])
    with (root / 'observations/checkpoint.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        data = capture(args.plan)
        save(root / 'observations/measured-results.json', data, plan)
        save(root / 'checkpoint-latest.json', data, plan)
        target = root / 'observations/measured-results.md'
        if str(target) in plan['frozen_sha256']:
            raise ValueError('Report path is frozen')
        temporary = target.with_suffix('.md.checkpoint.tmp')
        temporary.write_text(report(data))
        temporary.replace(target)
        print(json.dumps({k: data[k] for k in ('snapshot_utc', 'phase', 'controller_live', 'guard_live',
                                             'clocked_games', 'judge_workers_active', 'completed_games',
                                             'checked_moves', 'own_moves', 'by_configuration')}))
