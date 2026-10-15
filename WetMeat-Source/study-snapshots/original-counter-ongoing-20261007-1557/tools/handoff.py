"""Cancel a fixed deadline through a verified audited handoff. GPL-3.0-or-later."""
import datetime as dt
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, '/workspace/aurora-stockfish/tools/night-study')
from cutoff_watch_multi import processes
from continue_original import digest, write
from verify_records import require
sys.path.insert(0, str(Path(__file__).resolve().parent))
import counter_queue

PYTHON = '/workspace/aurora-chess/.venv/bin/python'
ROOT = Path(__file__).resolve().parents[1]


def matches(row, launch):
    return bool(row and row['birth'] == launch['birth'] and row['args'] == launch['command'])


def locks_available(paths):
    acquired = []
    try:
        for path in paths:
            lock = Path(path).open('a')
            acquired.append(lock)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    finally:
        for lock in acquired:
            lock.close()


def boundary_evidence(old, plan):
    state = json.loads((old / 'state.json').read_text())
    require(state['phase'] == 'paused_at_boundary' and state['child'] is None,
            'Old controller did not stop at the requested audited boundary')
    expected = [stage['name'] for stage in plan['stages'][:5]]
    require(state['completed_stages'] == expected, 'Unexpected old stage coverage; do not skip or replay jobs')
    require((old / 'pause_at_boundary').exists(), 'Old pause marker was removed')
    evidence = counter_queue.progress(plan)
    for bias in (32, 64):
        rows = evidence['by_study'].get(str(old / f'training-{bias}'), {})
        require(set(rows) == {'baseline', 'candidate'}, 'Missing first training batch')
        for row in rows.values():
            require(sum(row[k] for k in ('wins', 'draws', 'losses')) == 2,
                    'First training batch must have both colors completed')
            require(row['audit_complete'] and row['checked_moves'] == row['own_moves'],
                    'First training batch audit is incomplete')
            require(not row['mistakes'] and not row['blunders'], 'Detected training failure requires review')
        summary = json.loads((old / f'training-{bias}/pair-001/audit/summary.json').read_text())
        require(summary['status'] == 'completed' and summary['judge_binary_sha256'] == plan['judge_sha256'],
                'Audit summary identity is incomplete or changed')
    require(not evidence['unscored_games'], 'An unfinished game cannot be handed off as completed')
    studies = {str(old / f'training-{bias}') for bias in (32, 64)}
    require(not any(game['study'] in studies and game['termination'] in
                    ('TIME_FORFEIT', 'ENGINE_ERROR', 'ILLEGAL_MOVE_FORFEIT')
                    for game in evidence['games']), 'A training fault requires review before handoff')
    return evidence


def native_engines(table):
    names = {'wetmeat-linux-avx512', 'wetmeat-draw-aversion', 'stockfish-19-native'}
    return {pid: row for pid, row in table.items()
            if row['args'] and Path(row['args'][0]).name in names}


def old_observed_jobs(table, old):
    watch = json.loads((old / 'checkpoint-watch.json').read_text())
    known = watch.get('observed_identities', {})
    return {int(pid): table[int(pid)] for pid, identity in known.items()
            if int(pid) in table and table[int(pid)]['birth'] == identity['birth']
            and table[int(pid)]['args'] == identity['args']}


def retire_old_guard(old, record):
    launch = json.loads((old / 'watch-launch.json').read_text())
    table = processes()
    if matches(table.get(launch['pid']), launch):
        require(not native_engines(table), 'Engine still running; do not retire its guard')
        os.kill(launch['pid'], signal.SIGTERM)
        for _ in range(50):
            if not matches(processes().get(launch['pid']), launch):
                break
            time.sleep(.1)
        else:
            raise RuntimeError('Old guard did not exit; do not bypass its lock')
        record['old_guard_retired'] = {'pid': launch['pid'], 'birth': launch['birth'],
                                       'command': launch['command'], 'signal': 'SIGTERM',
                                       'engine_jobs_running': False}
    else:
        record['old_guard_retired'] = {'already_exited': True, 'signal_sent': False}
    require(locks_available([str(old / 'checkpoint-watch.lock')]), 'Old guard lock remains owned')


def freeze_plan(draft, old, old_plan):
    plan = json.loads(json.dumps(draft))
    require(plan['deadline_utc'] is None and plan['no_fixed_user_cutoff'], 'User deadline must remain cancelled')
    plan['inherited_symlinks'] = {}
    for bias in (32, 64):
        target = old / f'training-{bias}/pair-001'
        alias = ROOT / f'training-{bias}/pair-001'
        require(alias.is_symlink() and alias.resolve() == target.resolve(), 'Imported training alias changed')
        plan['inherited_symlinks'][str(alias)] = str(target.resolve())
        write(ROOT / f'training-{bias}/state.json', json.loads((old / f'training-{bias}/state.json').read_text()))
        for path in sorted(target.glob('game-*')):
            if path.suffix in ('.json', '.pgn'):
                plan['frozen_sha256'][str(path)] = digest(path)
        for path in sorted((target / 'audit').glob('*.json')):
            plan['frozen_sha256'][str(path)] = digest(path)
        plan['frozen_sha256'][str(ROOT / f'training-{bias}/state.json')] = digest(ROOT / f'training-{bias}/state.json')
    for path in [*ROOT.rglob('*.py'), ROOT / 'fresh-training-openings.json', ROOT / 'metadata-checks.json']:
        plan['frozen_sha256'][str(path)] = digest(path)
    plan['created_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    counter_queue.bounded.verify_inputs(plan)
    before = counter_queue.progress(old_plan)
    after = counter_queue.progress(plan)
    require(before['by_phase'] == after['by_phase'], 'Imported coverage/configuration totals changed')
    require(len(before['games']) == len(after['games']), 'Imported games were lost or duplicated')
    write(ROOT / 'plan.json', plan)
    source = {str(path): digest(path) for path in ROOT.rglob('*.py')}
    checks = json.loads((ROOT / 'metadata-checks.json').read_text())
    ready = {'status': 'frozen_experimental', 'frozen_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
             'plan_sha256': digest(ROOT / 'plan.json'), 'source_sha256': source,
             'settings_checked': old_plan['trial_settings'],
             'existing_setting_checks_preserved': [str(old / f'check-setting{bias}.json') for bias in (32, 64)],
             'metadata_checks': checks, 'no_fixed_user_cutoff': True,
             'no_engine_strength_gain': True, 'no_binary_source_weight_changes': True,
             'corresponding_source_weights_GPL_package': '/workspace/wetmeat-original-draw-aversion-experimental.tar'}
    write(ROOT / 'ready.json', ready)
    write(ROOT / 'watch-ready.json', {'frozen_utc': ready['frozen_utc'], 'plan_sha256': ready['plan_sha256'],
                                    'source_sha256': {str(ROOT / 'safety/watch.py'): digest(ROOT / 'safety/watch.py'),
                                                      '/workspace/aurora-stockfish/tools/night-study/cutoff_watch_multi.py': digest('/workspace/aurora-stockfish/tools/night-study/cutoff_watch_multi.py')},
                                    'no_fixed_user_cutoff': True, 'checks': checks})
    write(ROOT / 'imported-training-verified.json', {'created_utc': ready['frozen_utc'],
                                                   'old_root': str(old), 'source_plan_sha256': digest(old / 'plan.json'),
                                                   'coverage_before_after_matches': True,
                                                   'complete_game_count': len(after['games']),
                                                   'evidence': after})
    return plan


def launch_child(command, log_name):
    log = (ROOT / log_name).open('a')
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    log.close()
    row = processes().get(process.pid)
    require(row is not None and row['args'] == command, 'Could not capture exact child launch identity')
    return process, {'pid': process.pid, 'birth': row['birth'], 'pgid': row['pgid'], 'command': command}


def publish_active(record, plan):
    scratch = Path('/workspace/scratch/wetmeat-study-state.json')
    lock = Path('/workspace/scratch/wetmeat-study-state.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX)
    state = json.loads(scratch.read_text())
    state['historical_counter_before_deadline_handoff'] = state['active_continuation']
    state['active_continuation'] = {
        'root': str(ROOT), 'state': str(ROOT / 'state.json'), 'plan': str(ROOT / 'plan.json'),
        'plan_sha256': digest(ROOT / 'plan.json'), 'ready': str(ROOT / 'ready.json'),
        'launch': str(ROOT / 'launch.json'), 'guard': str(ROOT / 'checkpoint-watch.json'),
        'guard_ready': str(ROOT / 'watch-ready.json'), 'progress_report': str(ROOT / 'progress.json'),
        'deadline_utc': None, 'no_fixed_user_stop_time': True,
        'checkpoint': str(ROOT / 'checkpoint-latest.json'),
        'checkpoint_tool': str(ROOT / 'observations/checkpoint_counter.py'),
        'current_measured_results': str(ROOT / 'observations/measured-results.json'),
        'inherited_training_verified': str(ROOT / 'imported-training-verified.json'),
        'engine_source_changes': 0, 'parameter_trials': plan['trial_settings'], 'candidate_promoted': False,
        'handoff': str(ROOT / 'handoff.json')}
    state['cutoff_cancellation'].update(handoff_status='running_followon', handoff_record=str(ROOT / 'handoff.json'),
                                         old_guard_retirement_pending_full_audited_boundary=False,
                                         no_fixed_user_cutoff=True)
    state['active_original_state'] = str(ROOT / 'state.json')
    state['live_state'] = str(ROOT / 'state.json')
    state['running_sessions'] = [record['controller']]
    state['original_experiment']['active_results'] = str(ROOT)
    state['last_live_confirmation'] = str(ROOT / 'handoff.json')
    state['next_steps'] = [
        'There is no fixed user cutoff. Read the active root state/launch/plan/readiness/progress/guard/handoff and actual commands, PID births, groups, affinities and lock owners; never trust saved PIDs alone or duplicate queues.',
        'Continue the existing finite frozen queue: first64 training export, second32/64 training opening and audits, training-only checksummed selection, then every predeclared fresh heldout opening. Preserve verified read-only first-batch imports, exact identities/options/resources, all losses/draws and old paused markers.',
        'Use actual600+5,Threads1,Hash128,30ms overhead,Skill20,no Elo limit,ponder or tablebases,reached draw rules and matched rotating CPUs0/1. Two-core quota; no heavy extra work beside clocked games or audits. Request ACTIVE pause_at_boundary and wait for a full audited/no-engine boundary before justified heavy work.',
        'Detected training failures require exact histories, clocks, nodes and common-depth evidence before isolated C++ fixes. Zero cases do not support an invented tweak. Never tune or reselect on heldout data; later heldout-informed changes need fresh validation.',
        'After the queue finishes, checkpoint a same-configuration sample lead only after completing the predeclared validation. Report all games, finite audit limits and exploratory/repeated-look uncertainty; no superiority,Elo,perfect play or automatic adoption claim. If the goal is unmet, prepare a separately frozen guarded fresh-data follow-on only after all old engines/locks exit.',
        'Preserve all prior finite samples, the old247 mixed-version study, releases and corresponding source/actualNNUE/GPL/AUTHORS archives. Independent rewrite losses and partial audits stay separate and paused. No deployments,messages or subagents; future model/workspace/quota/reset availability is unknown.'
    ]
    state['cutoff_watch'] = str(ROOT / 'checkpoint-watch.json')
    state['cutoff_watch_details'] = {**record['guard'], 'script': str(ROOT / 'safety/watch.py'),
                                    'record': str(ROOT / 'checkpoint-watch.json'), 'deadline_utc': None}
    state['updated_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    write(scratch, state)
    lock.close()
    status = Path('/workspace/aurora-stockfish/results/overnight-fallback/STATE.md')
    old_status = status.read_text()
    (ROOT / 'observations/STATE-before-handoff.md').write_text(old_status)
    prefix = '# Active ORIGINAL WetMeat continuation — no fixed cutoff\n\n' + \
        'The user cancelled the07:20 stop. The old frozen queue completed a full audited boundary and exited. Its guard was retired only with no engines running. No game was interrupted.\n\n' + \
        'Active root: ' + str(ROOT) + '\nRead state.json, plan.json, ready.json, launch.json, progress.json, checkpoint-watch.json and handoff.json. Verify current commands/PID births/groups/affinities/locks; do not trust saved PIDs alone or duplicate jobs.\n\n' + \
        'The remaining original32/64 trials retain unchanged binaries/options/openings/resources and training-only selection. Completed first training batches are verified read-only imports, counted once. No fixed user stop time; each predeclared test queue remains finite and checkpointed. Finish validation before reporting any lead. Stable stays released; hypotheses remain experimental.\n\n' + \
        'Preserve all old pause markers/releases/source/actualNNUE/GPL/AUTHORS packages and finite247 study. No heavy added work during clocked games/audits. Any failure halts for evidence review. No deployment/messages/subagents. Future model/workspace execution and quota/reset status are unknown.\n\n## Earlier checkpoints (historical cutoff superseded)\n\n'
    temporary = status.with_suffix('.md.handoff.tmp')
    temporary.write_text(prefix + old_status)
    temporary.replace(status)


def main():
    lock = (ROOT / 'handoff.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    ready = json.loads((ROOT / 'handoff-ready.json').read_text())
    for path, expected in ready['frozen_sha256'].items():
        require(digest(path) == expected, 'Handoff input changed: ' + path)
    draft = json.loads((ROOT / 'plan-draft.json').read_text())
    old = Path(draft['handoff_from'])
    old_plan = json.loads((old / 'plan.json').read_text())
    require(digest(old / 'plan.json') == ready['old_plan_sha256'], 'Old frozen plan changed')
    launch = json.loads((old / 'launch.json').read_text())
    record = {'status': 'waiting_for_full_audited_boundary', 'pid': os.getpid(),
              'birth': processes()[os.getpid()]['birth'], 'old_root': str(old), 'next_root': str(ROOT),
              'deadline_utc': None, 'requested_utc': dt.datetime.now(dt.timezone.utc).isoformat()}
    write(ROOT / 'handoff.json', record)
    try:
        while matches(processes().get(launch['pid']), launch):
            require((old / 'pause_at_boundary').exists(), 'Do not bypass the old safe-pause request')
            require(digest(old / 'plan.json') == ready['old_plan_sha256'], 'Old plan changed while waiting')
            record.update(updated_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                          old_phase=json.loads((old / 'state.json').read_text())['phase'])
            write(ROOT / 'handoff.json', record)
            time.sleep(15)
    except Exception as error:
        record.update(status='blocked_preserved_for_review', error=f'{type(error).__name__}: {error}',
                      updated_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        write(ROOT / 'handoff.json', record)
        raise
    try:
        boundary_evidence(old, old_plan)
        require(not old_observed_jobs(processes(), old), 'Old observed worker/controller still runs')
        require(not native_engines(processes()), 'Native engine remains live; do not freeze or launch a duplicate')
        require(locks_available(old_plan['lock_paths']), 'Old queue locks remain owned')
        retire_old_guard(old, record)
        plan = freeze_plan(draft, old, old_plan)
        require(not (ROOT / 'launch.json').exists(), 'New controller was already launched')
        guard_process, guard = launch_child([PYTHON, str(ROOT / 'safety/watch.py'), '--output', str(ROOT)], 'watch.log')
        write(ROOT / 'watch-launch.json', guard)
        time.sleep(.2)
        require(guard_process.poll() is None, 'New guard failed before controller launch')
        process, controller = launch_child([PYTHON, str(ROOT / 'tools/counter_queue.py'), '--plan', str(ROOT / 'plan.json')], 'controller.log')
        controller.update(started_utc=dt.datetime.now(dt.timezone.utc).isoformat(), plan_sha256=digest(ROOT / 'plan.json'),
                          watcher_pid=guard['pid'], watcher_birth=guard['birth'], no_fixed_user_cutoff=True,
                          quota_monitoring=False, automatic_engine_tuning=False, candidate_adoption=False)
        write(ROOT / 'launch.json', controller)
        record.update(status='running_followon', controller=controller, guard=guard,
                      started_utc=controller['started_utc'], imported_training=str(ROOT / 'imported-training-verified.json'))
        write(ROOT / 'handoff.json', record)
        publish_active(record, plan)
        code = process.wait()
        record.update(status='followon_exited', controller_exit_code=code,
                      finished_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        write(ROOT / 'handoff.json', record)
    except Exception as error:
        record.update(status='blocked_preserved_for_review', error=f'{type(error).__name__}: {error}',
                      updated_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        write(ROOT / 'handoff.json', record)
        raise


if __name__ == '__main__':
    main()
