"""Exact-identity job guard without a fixed user stop time. GPL-3.0-or-later."""
import argparse
import datetime as dt
import fcntl
import json
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, '/workspace/aurora-stockfish/tools/night-study')
import cutoff_watch_multi as cleanup
from continue_original import digest, write


def identity_matches(row, launch):
    return bool(row and row['birth'] == launch['birth'] and row['args'] == launch['command'])


def observe(table, launch, state, commands, known):
    roots = set()
    expected = [launch]
    child = state.get('child')
    if child and child['command'] in commands:
        expected.append(child)
    for item in expected:
        if identity_matches(table.get(item['pid']), item):
            roots.add(item['pid'])
    for pid in cleanup.descendants(table, roots):
        if pid in table:
            known[pid] = table[pid]
    return {pid for pid, old in known.items()
            if pid in table and table[pid]['birth'] == old['birth']
            and table[pid]['args'] == old['args']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    root = parser.parse_args().output
    lock = (root / 'checkpoint-watch.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    ready = json.loads((root / 'ready.json').read_text())
    if digest(root / 'plan.json') != ready['plan_sha256']:
        raise RuntimeError('Frozen queue plan changed')
    own_ready = json.loads((root / 'watch-ready.json').read_text())
    if own_ready['plan_sha256'] != ready['plan_sha256']:
        raise RuntimeError('Guard and queue plans differ')
    for path, expected in own_ready['source_sha256'].items():
        if digest(path) != expected:
            raise RuntimeError('Guard source changed: ' + path)
    plan = json.loads((root / 'plan.json').read_text())
    if plan['deadline_utc'] is not None or not plan['no_fixed_user_cutoff']:
        raise RuntimeError('The cancelled deadline was reintroduced')
    cancelled = False

    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    while not (root / 'launch.json').exists():
        if cancelled:
            return
        time.sleep(.1)
    launch = json.loads((root / 'launch.json').read_text())
    commands = [stage['command'] for stage in plan['stages']]
    known = {}
    record = {'status': 'watching_exact_jobs', 'pid': os.getpid(),
              'deadline_utc': None, 'scope': str(root),
              'source': 'Matching command/PID/birth trees and observed descendants only.',
              'stop_policy': 'No wall-clock cutoff. Preserve evidence and clean exact orphans on controller exit or explicit stop.'}
    while True:
        state = json.loads((root / 'state.json').read_text()) if (root / 'state.json').exists() else {}
        table = cleanup.processes()
        selected = observe(table, launch, state, commands, known)
        controller_live = identity_matches(table.get(launch['pid']), launch)
        stop_requested = cancelled or (root / 'stop_now').exists()
        record.update(updated_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                      controller_live=controller_live,
                      observed_live_pids=sorted(selected), observed_identities=known)
        write(root / 'checkpoint-watch.json', record)
        if stop_requested or not controller_live:
            record['reason'] = 'explicit_stop' if stop_requested else 'controller_exited'
            if selected:
                (root / 'pause_at_boundary').touch()

                def exact_roots(current):
                    return observe(current, launch, state, commands, known)

                cleanup.owned_roots = exact_roots
                record['status'] = 'stopping_exact_owned_jobs'
                write(root / 'checkpoint-watch.json', record)
                record.update(cleanup.stop_jobs())
            record.update(status='stopped_with_evidence_preserved',
                          stopped_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                          note='Workers freeze before engines stop; interrupted games are unscored and clocks never resume.')
            write(root / 'checkpoint-watch.json', record)
            return
        time.sleep(5)


if __name__ == '__main__':
    main()
