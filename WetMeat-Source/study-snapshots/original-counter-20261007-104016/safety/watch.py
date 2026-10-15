"""Exact-identity checkpoint guard for this frozen queue. GPL-3.0-or-later."""
import argparse
import datetime as dt
import fcntl
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, '/workspace/aurora-stockfish/tools/night-study')
import cutoff_watch_multi as cleanup
from continue_original import digest, write


def observe(table, launch, state, commands, known):
    roots = set()
    expected = [(launch['pid'], launch['birth'], launch['command'])]
    child = state.get('child')
    if child and child['command'] in commands:
        expected.append((child['pid'], child['birth'], child['command']))
    for pid, birth, command in expected:
        row = table.get(pid)
        if row and row['birth'] == birth and row['args'] == command:
            roots.add(pid)
    for pid in cleanup.descendants(table, roots):
        if pid in table:
            known[pid] = table[pid]
    return {pid for pid, old in known.items()
            if pid in table and table[pid]['birth'] == old['birth'] and table[pid]['args'] == old['args']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(); root = args.output
    lock = (root/'checkpoint-watch.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    ready = json.loads((root/'ready.json').read_text())
    if digest(root/'plan.json') != ready['plan_sha256']:
        raise RuntimeError('Queue plan changed')
    plan = json.loads((root/'plan.json').read_text())
    deadline = dt.datetime.fromisoformat(plan['deadline_utc']).timestamp()
    while not (root/'launch.json').exists():
        if time.time() >= deadline:
            return
        time.sleep(.1)
    launch = json.loads((root/'launch.json').read_text())
    commands = [stage['command'] for stage in plan['stages']]
    known = {}
    record = {'status': 'waiting_for_checkpoint', 'pid': __import__('os').getpid(),
              'deadline_utc': plan['deadline_utc'], 'scope': str(root),
              'source': 'Only matching command/PID/birth trees, including previously observed orphan descendants.'}
    while time.time() < deadline:
        state = json.loads((root/'state.json').read_text()) if (root/'state.json').exists() else {}
        selected = observe(cleanup.processes(), launch, state, commands, known)
        record.update(updated_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                      observed_live_pids=sorted(selected), observed_identities=known)
        write(root/'checkpoint-watch.json', record)
        time.sleep(min(30, max(0, deadline-time.time())))
    (root/'pause_at_boundary').touch()
    state = json.loads((root/'state.json').read_text()) if (root/'state.json').exists() else {}

    def exact_roots(table):
        return observe(table, launch, state, commands, known)

    cleanup.owned_roots = exact_roots
    record.update(status='stopping_exact_owned_jobs', checkpoint_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    write(root/'checkpoint-watch.json', record)
    record.update(cleanup.stop_jobs())
    record.update(status='stopped_at_checkpoint',
                  note='Workers frozen before engines stopped. Completed games preserved; incomplete games excluded, never cutoff forfeits or resumed clocks.')
    write(root/'checkpoint-watch.json', record)


if __name__ == '__main__':
    main()
