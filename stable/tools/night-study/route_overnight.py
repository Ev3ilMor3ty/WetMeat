"""Checkpointed independent-to-original routing. SPDX-License-Identifier: GPL-3.0-or-later."""
import argparse
import datetime as dt
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def save(path, value):
    value['updated_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def alive(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except FileNotFoundError:
        return False


def route(state):
    candidate = state.get('score_by_variant', {}).get('candidate', {})
    count = sum(candidate.get(k, 0) for k in ('wins', 'draws', 'losses'))
    if count < 2 or state.get('audited_pairs') != [0]:
        raise RuntimeError('Need the complete first rapid batch and all its audits before routing')
    score = (candidate.get('wins', 0) + .5 * candidate.get('draws', 0)) / count
    return ('original' if score < .5 else 'independent'), score


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--independent', type=Path, required=True)
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--opponent', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--force-original', action='store_true', help='Latest user priority: original WetMeat irrespective of rewrite score')
    p.add_argument('--prepare', type=Path, help='Original candidate build/check pipeline, only after the safe boundary')
    p.add_argument('--allow-checkpoint-handoff', action='store_true', help='Latest priority: completed rewrite games, unfinished audit explicitly saved and paused')
    args = p.parse_args()
    if args.allow_checkpoint_handoff and not args.force_original:
        p.error('Checkpoint handoff requires explicit original-engine priority')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    lock = (output / 'queue.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('Routing job already active; no duplicate study started.', flush=True)
        return
    checkpoint = output / 'route.json'
    if checkpoint.exists():
        previous = json.loads(checkpoint.read_text())
        if previous.get('child_pid') and alive(previous['child_pid']):
            print('Previously launched study remains active.', flush=True)
            return
    launch = json.loads((args.independent / 'results/overnight/launch.json').read_text())
    began = dt.datetime.fromisoformat(launch['started_utc']).timestamp()
    deadline = began + launch['max_hours_this_invocation'] * 3600
    cutoff_file = output / 'cutoff.json'
    if cutoff_file.exists():
        deadline = min(deadline, dt.datetime.fromisoformat(json.loads(cutoff_file.read_text())['utc']).timestamp())
    state = {'status': 'waiting_for_independent_boundary', 'pid': os.getpid(),
             'independent_runner_pid': launch['pid'], 'deadline_utc': dt.datetime.fromtimestamp(deadline, dt.timezone.utc).isoformat(),
             'condition': 'After the independent rapid comparison and audits, prioritize original WetMeat as explicitly requested.' if args.force_original else 'After the first independent rapid comparison and audits, switch to original if revised independent score is below 50%.',
             'limitations': 'Routing from a two-game candidate pilot is an operational choice, not certified strength. No original-engine code improvement is claimed yet.'}
    save(checkpoint, state)
    print('Waiting for the independent rapid comparison and audit to finish safely.', flush=True)
    source = args.independent / 'results/overnight/state.json'
    while time.time() < deadline:
        snapshot = json.loads(source.read_text()) if source.exists() else {}
        running = alive(launch['pid'])
        if not running:
            allowed = {'paused_at_pair_boundary'}
            if args.allow_checkpoint_handoff:
                allowed.add('paused_audit_checkpoint')
            if snapshot.get('status') not in allowed:
                state.update(status='blocked_incomplete_dependency', dependency_status=snapshot.get('status'))
                save(checkpoint, state)
                return
            break
        time.sleep(3)
    else:
        state['status'] = 'night_budget_exhausted_waiting'
        save(checkpoint, state)
        return
    if args.force_original:
        audited = snapshot.get('audited_pairs') == [0]
        saved_audit = args.allow_checkpoint_handoff and snapshot.get('status') == 'paused_audit_checkpoint'
        if snapshot.get('completed_pairs') != [0] or not (audited or saved_audit):
            raise RuntimeError('Need completed independent games plus complete or explicitly checkpointed audits')
        state['independent_audit_complete'] = audited
        state['independent_audit_checkpoint_note'] = snapshot.get('audit_pause_reason')
        selected = 'original'
        pilot = snapshot.get('score_by_variant', {}).get('candidate', {})
        count = sum(pilot.get(k, 0) for k in ('wins', 'draws', 'losses'))
        score = (pilot.get('wins', 0) + .5 * pilot.get('draws', 0)) / count if count else None
    else:
        selected, score = route(snapshot)
    candidate_ready = None
    if selected == 'original' and args.prepare and deadline - time.time() > 3600:
        state.update(status='preparing_original_experiment', prepare_script=str(args.prepare.resolve()))
        save(checkpoint, state)
        with (output / 'prepare.log').open('a') as log:
            try:
                prepared = subprocess.Popen([sys.executable, str(args.prepare.resolve())],
                                            stdout=log, stderr=subprocess.STDOUT,
                                            start_new_session=True)
                code = prepared.wait(timeout=min(1800, max(1, deadline - time.time() - 2400)))
                if code == 0:
                    candidate_ready = json.loads((output / 'candidate-ready.json').read_text())
                else:
                    state['prepare_failure_exit_code'] = code
            except subprocess.TimeoutExpired:
                os.killpg(prepared.pid, signal.SIGTERM)
                try:
                    prepared.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(prepared.pid, signal.SIGKILL)
                    prepared.wait()
                state['prepare_failure'] = 'Timed out; no experimental candidate selected'
            save(checkpoint, state)
    remaining = max(0, (deadline - time.time()) / 3600)
    state.update(selected_engine=selected, independent_candidate_score=score,
                 independent_candidate_result=snapshot['score_by_variant']['candidate'])
    if selected == 'original':
        study = output / 'original-study'
        command = [sys.executable, str(Path(__file__).with_name('overnight.py')),
                   '--engine', str(args.original.resolve()), '--opponent', str(args.opponent.resolve()),
                   '--clock-runner', str(Path(__file__).with_name('clock_match.py')),
                   '--audit-runner', str(Path(__file__).with_name('analyse_games.py')),
                   '--pairs', '48', '--hours', str(remaining), '--output', str(study)]
        if candidate_ready:
            command += ['--candidate', candidate_ready['binary'],
                        '--candidate-draw-aversion', str(candidate_ready['draw_aversion'])]
            state['candidate'] = candidate_ready
    else:
        study = args.independent / 'results/overnight'
        command = [sys.executable, str(args.independent / 'tools/overnight.py'),
                   '--engine', str(args.independent / 'releases/initial/wetmeat'),
                   '--candidate', str(args.independent / 'releases/candidate/wetmeat'),
                   '--opponent', str(args.opponent.resolve()),
                   '--clock-runner', str(args.independent / 'tools/study/clock_match.py'),
                   '--audit-runner', str(args.independent / 'tools/study/analyse_games.py'),
                   '--pairs', '48', '--hours', str(remaining), '--output', str(study)]
    state.update(command=command, study=str(study), remaining_hours=remaining)
    if args.dry_run:
        state['status'] = 'dry_run_route_verified'
        save(checkpoint, state)
        print(json.dumps({'selected': selected, 'score': score, 'dry_run': True}))
        return
    if remaining < .75:
        state['status'] = 'insufficient_remaining_night_budget'
        save(checkpoint, state)
        return
    if selected == 'independent':
        (study / 'pause_at_boundary').unlink(missing_ok=True)
    with (output / 'selected-study.log').open('a') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        state.update(status='running_selected_study', child_pid=process.pid)
        save(checkpoint, state)
        print(f'Started {selected} WetMeat study, PID {process.pid}', flush=True)
        code = process.wait()
    state.update(status='completed' if code == 0 else 'selected_study_failed', child_exit_code=code)
    save(checkpoint, state)


if __name__ == '__main__':
    main()
