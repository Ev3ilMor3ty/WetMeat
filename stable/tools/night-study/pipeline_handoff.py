"""Switch a completed audited study to frozen CPU queues at a safe boundary. GPL-3.0-or-later."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from cutoff_watch_multi import processes
from summarize_study import summarize


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    temporary = path.with_suffix('.handoff.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def training_gate(report):
    versions = report['by_phase_and_variant']['training']
    baseline, candidate = versions['baseline'], versions['candidate']
    for stats in (baseline, candidate):
        if stats['wins'] + stats['draws'] + stats['losses'] != 2 or not stats['audit_complete']:
            raise ValueError('Training gate needs both complete color games and audits')
    baseline_points = baseline['wins'] + .5 * baseline['draws']
    candidate_points = candidate['wins'] + .5 * candidate['draws']
    candidate_errors = candidate['mistakes_detected'] + candidate['blunders_detected']
    baseline_errors = baseline['mistakes_detected'] + baseline['blunders_detected']
    if candidate_points < baseline_points:
        return False, 'Candidate scored below baseline in the training pair; retain stable for follow-on tests.'
    if candidate_errors and not baseline_errors:
        return False, 'Candidate failed the finite zero-detected-error training gate while baseline passed.'
    return True, 'Continue the frozen experimental comparison; training data does not establish superiority.'


def guard_ready(plan, table, root):
    path = root / 'cutoff-watch.json'
    if not path.exists():
        return False
    record = json.loads(path.read_text())
    process = table.get(record.get('pid'))
    return (record.get('status') == 'waiting' and record.get('script') == plan['guard_script']
            and str(plan['new_study']) in record.get('covered_studies', [])
            and process is not None and len(process['args']) > 1
            and process['args'][1] == plan['guard_script'])


def inputs_unchanged(plan, binaries=False):
    for path, expected in plan['source_sha256'].items():
        if digest(path) != expected:
            raise ValueError('Frozen prepared source changed: ' + path)
    if binaries:
        for path, expected in plan['binary_sha256'].items():
            if digest(path) != expected:
                raise ValueError('Frozen engine changed: ' + path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    lock = (root / 'pipeline-handoff.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('A handoff already owns this queue')
    plan_digest = digest(args.plan)
    plan = json.loads(args.plan.read_text())
    if plan['status'] != 'ready' or root != Path(plan['output']):
        raise ValueError('Prepared plan/output mismatch')
    deadline = dt.datetime.fromisoformat(json.loads(Path(plan['cutoff']).read_text())['utc']).timestamp()
    if time.time() >= deadline:
        raise SystemExit('Cutoff reached; no new jobs started')
    inputs_unchanged(plan)
    old = Path(plan['old_study'])
    record = {'status': 'waiting_original_boundary', 'pid': os.getpid(),
              'plan': str(args.plan.resolve()), 'old_study': str(old), 'new_study': plan['new_study'],
              'cutoff_utc': dt.datetime.fromtimestamp(deadline, dt.timezone.utc).isoformat()}
    if not guard_ready(plan, processes(), root):
        raise ValueError('Multi-study cutoff guard is not live; cannot request a handoff')
    # Marker takes effect only after the current four games AND their audits.
    (old / 'pause_at_boundary').touch()
    save(root / 'pipeline-handoff.json', record)
    last_status = None
    while time.time() < deadline:
        state = json.loads((old / 'state.json').read_text())
        table = processes()
        if state['status'] != last_status:
            record['original_status'] = state['status']
            record['updated_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
            save(root / 'pipeline-handoff.json', record)
            print(json.dumps(record), flush=True)
            last_status = state['status']
        if not guard_ready(plan, table, root):
            record['status'] = 'blocked_cutoff_guard_not_live'
            save(root / 'pipeline-handoff.json', record)
            return
        if state['status'] == 'paused_at_pair_boundary':
            if state['completed_pairs'] != [0] or state['audited_pairs'] != [0]:
                raise ValueError('Unexpected boundary; replan opening sequence instead of replaying validation')
            # No old controller, judge or match engine may remain at the handoff.
            active = [pid for pid, process in table.items() if
                      any(argument in plan['must_be_stopped_programs'] for argument in process['args'])]
            if not active:
                break
        time.sleep(min(20, max(0, deadline - time.time())))
    else:
        record['status'] = 'cutoff_reached_no_followon_started'
        save(root / 'pipeline-handoff.json', record)
        return
    if deadline - time.time() < 2400:
        record['status'] = 'insufficient_clock_budget_no_followon_started'
        save(root / 'pipeline-handoff.json', record)
        return
    if digest(args.plan) != plan_digest:
        raise ValueError('Prepared handoff plan changed; do not launch mixed inputs')
    inputs_unchanged(plan, binaries=True)  # No clocked game is running now.
    report = summarize(old)
    use_candidate, decision = training_gate(report)
    new = Path(plan['new_study'])
    if (new / 'state.json').exists():
        raise ValueError('Follow-on study already exists; do not start a duplicate')
    record.update(status='starting_followon', use_candidate=use_candidate, decision=decision,
                  prior_training=report['by_phase_and_variant']['training'])
    save(root / 'pipeline-handoff.json', record)
    command = [sys.executable, plan['runner'], '--engine', plan['baseline'], '--opponent', plan['opponent'],
               '--clock-runner', plan['clock_runner'], '--audit-runner', plan['audit_runner'],
               '--pairs', '47', '--hours', str(max(0, (deadline - time.time()) / 3600)), '--output', str(new)]
    if use_candidate:
        command += ['--candidate', plan['candidate'], '--candidate-draw-aversion', '16']
    with (root / 'pipelined-study.log').open('ab') as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        record.update(status='running_followon', child_pid=child.pid, command=command,
                      updated_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        save(root / 'pipeline-handoff.json', record)
        code = child.wait()
    record.update(status='followon_runner_finished', returncode=code,
                  updated_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    save(root / 'pipeline-handoff.json', record)


if __name__ == '__main__':
    main()
