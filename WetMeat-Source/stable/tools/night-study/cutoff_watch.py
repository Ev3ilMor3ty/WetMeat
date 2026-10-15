"""Stop only identified WetMeat job trees at the user's deadline. GPL-3.0-or-later."""
import datetime as dt
import fcntl
import json
import os
import signal
import time
from pathlib import Path

ROOT = Path('/workspace/aurora-stockfish/results/overnight-fallback')
INDEPENDENT = Path('/workspace/wetmeat-independent/results/overnight')


def save(path, value):
    temporary = path.with_suffix('.watch.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def processes():
    result = {}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if fields[0] == 'Z':
                continue
            result[int(entry.name)] = {'ppid': int(fields[1]), 'pgid': int(fields[2]),
                                      'birth': fields[19],
                                      'args': (entry / 'cmdline').read_bytes().decode().split('\0')[:-1]}
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    return result


def owned_roots(table):
    # Exact Python script and output directory, never a substring PID match.
    scripts = {
        '/workspace/wetmeat-independent/tools/overnight.py': str(INDEPENDENT),
        '/workspace/aurora-stockfish/tools/night-study/route_overnight.py': str(ROOT),
        '/workspace/aurora-stockfish/tools/night-study/overnight.py': str(ROOT / 'original-study'),
    }
    selected = set()
    for pid, record in table.items():
        args = record['args']
        # The preparation script has fixed project paths and no output argument.
        # Include a standalone staged compile as well as a queued child compile.
        if len(args) >= 2 and args[1] == '/workspace/aurora-stockfish/tools/night-study/prepare_original.py':
            selected.add(pid)
            continue
        if len(args) < 4 or args[1] not in scripts or '--output' not in args:
            continue
        if args[args.index('--output') + 1] == scripts[args[1]]:
            selected.add(pid)
    return selected


def descendants(table, roots):
    selected = set(roots)
    while True:
        more = {pid for pid, record in table.items() if record['ppid'] in selected}
        if more <= selected:
            return selected
        selected |= more


def stop_jobs():
    table = processes()
    roots = owned_roots(table)
    selected = descendants(table, roots)
    # Freeze controllers first so they cannot spawn a new phase during cleanup.
    for pid in roots:
        try:
            os.kill(pid, signal.SIGSTOP)
        except ProcessLookupError:
            pass
    current = processes()
    selected |= descendants(current, roots)
    table.update({pid: current[pid] for pid in selected if pid in current})
    # Process groups only if every member belongs to the selected trees.
    groups = {table[pid]['pgid'] for pid in selected if pid in table}
    safe_groups = {group for group in groups if group != os.getpgrp()
                   and all(pid in selected for pid, rec in current.items() if rec['pgid'] == group)}
    for group in safe_groups:
        try:
            os.killpg(group, signal.SIGTERM)
            os.killpg(group, signal.SIGCONT)
        except ProcessLookupError:
            pass
    for pid in selected:
        if table[pid]['pgid'] in safe_groups:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            os.kill(pid, signal.SIGCONT)
        except ProcessLookupError:
            pass
    time.sleep(5)
    survivors = processes()
    killed = []
    for pid in selected:
        # Birth ticks prevent signaling a reused PID.
        if pid in survivors and survivors[pid]['birth'] == table[pid]['birth']:
            try:
                os.kill(pid, signal.SIGKILL)
                killed.append(pid)
            except ProcessLookupError:
                pass
    return {'identified_roots': sorted(roots), 'identified_job_pids': sorted(selected),
            'forced_kill_pids': killed}


def main():
    lock = (ROOT / 'cutoff-watch.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    cutoff = json.loads((ROOT / 'cutoff.json').read_text())
    deadline = dt.datetime.fromisoformat(cutoff['utc']).timestamp()
    record = {'status': 'waiting', 'pid': os.getpid(), 'cutoff': cutoff}
    save(ROOT / 'cutoff-watch.json', record)
    while time.time() < deadline:
        time.sleep(min(30, max(0, deadline - time.time())))
    for directory in (INDEPENDENT, ROOT / 'original-study'):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'pause_at_boundary').touch()
    record.update(status='stopping_owned_jobs', stopped_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    save(ROOT / 'cutoff-watch.json', record)
    record.update(stop_jobs())
    record.update(status='stopped_at_user_cutoff',
                  note='Completed game JSON/PGN and audit checkpoints preserved. Any interrupted live game is incomplete, never counted as a loss or resumed with paused clocks.')
    save(ROOT / 'cutoff-watch.json', record)
    for directory in (INDEPENDENT, ROOT / 'original-study'):
        path = directory / 'state.json'
        if path.exists():
            state = json.loads(path.read_text())
            if state.get('pid') in record['identified_roots']:
                state['status_before_cutoff'] = state.get('status')
                state['status'] = 'stopped_at_user_cutoff'
            state['cutoff_utc'] = cutoff['utc']
            # A batch may be interrupted after some individual games finished.
            # Preserve their totals separately from fully completed batches.
            games = []
            for game_path in sorted(directory.glob('pair-*/game-*.json')):
                game = json.loads(game_path.read_text())
                if game.get('tested_points') is not None and game_path.with_suffix('.pgn').exists():
                    games.append({'file': str(game_path), 'variant': game.get('variant', 'baseline'),
                                  'tested_points': game['tested_points'], 'result': game['result']})
            state['completed_game_results_at_cutoff'] = games
            state['score_by_variant_at_cutoff'] = {}
            for name in sorted({game['variant'] for game in games}):
                points = [game['tested_points'] for game in games if game['variant'] == name]
                state['score_by_variant_at_cutoff'][name] = {
                    'wins': points.count(1), 'draws': points.count(.5), 'losses': points.count(0)}
            save(path, state)


if __name__ == '__main__':
    main()
