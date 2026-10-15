"""Start the new study only after the old fully audited stop. GPL-3.0-or-later."""
import datetime as dt
import fcntl
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from common import NIGHT, digest, load, require, write
from cutoff_watch_multi import processes
from prepare import OLD, ROOT, PYTHON, prepare, finalize_ready


def matches(table, launch):
    row=table.get(launch['pid'])
    return bool(row and row['birth']==launch['birth'] and row['args']==launch['command'])


def lock_owners_free(paths):
    handles=[]
    try:
        for name in paths:
            handle=Path(name).open('a');handles.append(handle)
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return False
        return True
    finally:
        for handle in handles:handle.close()


def native_engines(table):
    names={'wetmeat-linux-avx512','wetmeat-draw-aversion','stockfish-19-native',
           'wetmeat-independent','wetmeat-v0.1','wetmeat-v0.2'}
    return {pid:row for pid,row in table.items() if row['args'] and
            (Path(row['args'][0]).name in names or
             (Path(row['args'][0]).suffix not in ('.py','.sh') and
              ('stockfish' in Path(row['args'][0]).name.lower() or 'wetmeat' in Path(row['args'][0]).name.lower())))}


def publish_globals(controller, guard):
    path=Path('/workspace/scratch/wetmeat-study-state.json');saved=load(path)
    saved['paused_rapid_continuation']=saved['active_continuation']
    saved['active_continuation']={'root':str(ROOT),'type':'1000game100ms-both-engine-training',
       'state':str(ROOT/'state.json'),'plan':str(ROOT/'plan.json'),'plan_sha256':digest(ROOT/'plan.json'),
       'ready':str(ROOT/'ready.json'),'launch':str(ROOT/'launch.json'),
       'guard':str(ROOT/'checkpoint-watch.json'),'guard_ready':str(ROOT/'watch-ready.json'),
       'progress_report':str(ROOT/'progress.json'),'current_measured_results':str(ROOT/'measured-results.json'),
       'handoff':str(ROOT/'handoff.json'),'deadline_utc':None,'no_fixed_user_stop_time':True,
       'engine_source_changes':0,'candidate_promoted':False,
       'last_verified_controller_pid':controller['pid'],'last_verified_controller_birth':controller['birth'],
       'last_verified_guard_pid':guard['pid'],'last_verified_guard_birth':guard['birth']}
    saved['live_state']=str(ROOT/'state.json');saved['active_original_state']=str(ROOT/'state.json')
    saved['cutoff_watch']=str(ROOT/'checkpoint-watch.json')
    saved['short_time_study_request'].update(root=str(ROOT),status='running_guarded_baseline_training',
             plan_sha256=digest(ROOT/'plan.json'),handoff=str(ROOT/'handoff.json'),automatic_messages_enabled=False)
    saved['running_sessions']=[controller]
    saved['next_steps']=[
      'Automatic WetMeat messages/assistant continuations are disabled by the latest user request; do not re-enable them.',
      'Inspect the active1000game100ms study actual PID commands/births/groups/affinities/locks, plan/readiness/guard and progress. Never duplicate jobs or mutate frozen sources/binaries/options/openings. Old rapid/independent pause markers stay.',
      'Complete the stable baseline1000TRAINING games (500paired fresh openings),20game batches with BOTH-engine node audits between batches and exact evidence exports. Both engines get go movetime100,Threads1,Hash128,full Skill20,no limit/ponder/tablebases. Two-core quota; no extra heavy work alongside matches/audits.',
      'Use ACTIVE pause_at_boundary and wait for full audited/exported boundary/no engines before justified changes. Baseline audit errors are study findings and are retained; protocol/incomplete/identity faults halt for review. Never resume interrupted games or count checkpoint stops as forfeits.',
      'Review exact training histories, actual timing, nodes, PVs and completed common-depth evidence before isolated C++ fixes. New candidates need source/actualNNUE/GPL/AUTHORS packages, legality/protocol/tactics checks, frozen identities and fresh matched-control validation. Reserved250unused opening pairs support1000candidate+control validation games in a separate frozen plan; never tune on heldout.',
      'Keep all versions/phases/configurations and100ms results separate from rapid samples. Report actual W/D/L, both-engine checked/total moves, errors, shallower judge depths and finite shared-family/correlated-opening limits. No promised advantage/Elo/perfect play or automatic adoption. Preserve all old247/1112/1369/1561studies and complete source/weights/releases.',
      'Future model/workspace availability and quota/reset status are unknown; do not claim automatic coding or continued execution without inspecting actual jobs.' ]
    saved['updated_utc']=dt.datetime.now(dt.timezone.utc).isoformat();write(path,saved)
    state_path=Path('/workspace/aurora-stockfish/results/overnight-fallback/STATE.md')
    historical=state_path.read_text()
    prefix=f'''# Active ORIGINAL WetMeat1000-game100ms study

Latest priority:1000completed paired games with both engines receiving100ms per move, then audit BOTH sides and improve only from concrete training failures. Automatic WetMeat messages/assistant continuation task is disabled at user request; do not re-enable it. There is no fixed cutoff.

Active root: {ROOT}
Read plan.json,ready.json,state.json,launch.json,watch-ready.json,checkpoint-watch.json,handoff.json,progress.json and measured-results.json/MD. Inspect actual commands/PID births/groups/affinities and locks, never saved PIDs alone. Controller{controller['pid']} birth{controller['birth']}; guard{guard['pid']} birth{guard['birth']} launched after the old fully audited safe stop and all old engines/locks exited. No interrupted clock or duplicate queue.

The unchanged stable GPL binary is the baseline, SHA53a537c92e0ecf1ba5c1170e1f0724879bad871062ffbcd47dbffa9ff343d2c2; opponent/judge full-strengthStockfish19 SHAbe4c0644cb80dcaf87795284037d002ca9ecfecc7c5a416719523ec2fef61d7b. Both get go movetime100,Threads1,Hash128,overhead30ms,Skill20,no Elo limit/ponder/tablebases,reached draw rules,paired colors and rotating CPU0/1. Actual elapsed/search times and exact outbound UCI histories are recorded. Fixed-movetime is separate from600+5; no artificial overhead flag at100ms. No C++gain or adoption established.

Finite queue: preflight100position legality/protocol/tactics checks for both engines, then50batches of20paired TRAINING games, each followed by BOTH-engine node audits and verified evidence/failure export. Higher-budget fullroot plus fresh common-completed-depth MultiPV2 comparison; min1Mnodes/2xplayed,40cp preliminary triggers4x refinement, mistake50..199cp,blunder>=200cp. Both sides are audited equally. No full error rates until current completed-game move coverage is complete. Finite shared-family bias, shallower judging and paired/correlated moves/openings limit conclusions; no superiority,Elo or perfect-play claim.

The1000initial games are baseline TRAINING data;500fresh named opening endpoints, both colors, selected deterministically without performance/evaluation filtering.250additional novel opening pairs are separately frozen and UNUSED for later1000game candidate+baseline-control validation after supported isolated fixes are frozen. Do not tune on heldout or inherit another configuration's error results. Retain every completed draw/loss/fault; interrupted/capped games are preserved and excluded, never resumed with paused clocks or scored as checkpoint forfeits.

Two-core quota. No heavy extra builds/tests/searches/audits beside clocked games or existing audits. Request ACTIVE pause_at_boundary and wait for a full audited/exported boundary with no engines before justified heavy work. Protocol,identity,source,unfinished-game or lock faults halt/checkpoint; inspect rather than bypassing guards. Baseline chess mistakes are findings, not grounds to hide games or select only wins.

Old rapid root {OLD} remains fully audited/paused with its marker retained; frozen32/64trials and unused predeclared rapid heldout order8,11,6,7,9,10 remain deferred. Earlier original,pipeline,independent pause markers stay; independent four losses/partial audits never restart alongside this study. All earlier247mixed-version/1112/1369/1561finite samples, same-stable subsets, releases and corresponding source/actualNNUE/GPL/AUTHORS packages are preserved. New100ms configurations inherit none of these rates.

Save checkpoints and measured results. Correction candidates require exact failure histories/clocks/nodes/common-depth evidence, isolated code/source packages, meaningful checks and fresh frozen matched-control validation; reject regressions and keep stable released. No deployment,messages to others or subagents. Future model/workspace/quota/reset availability unknown; local jobs are only claimed running after actual inspection.

## Earlier checkpoints (historical status)

'''
    write(state_path,prefix+historical)


def main():
    lock=(ROOT/'handoff.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    bootstrap=load(ROOT/'bootstrap-ready.json')
    for path,expected in bootstrap['source_sha256'].items():require(digest(path)==expected,'Prepared source changed: '+path)
    old_launch=load(OLD/'launch.json');old_plan=load(OLD/'plan.json');old_handoff=load(OLD/'handoff.json')
    cancelled=False
    def cancel(signum,frame):
        nonlocal cancelled
        cancelled=True
    signal.signal(signal.SIGTERM,cancel);signal.signal(signal.SIGINT,cancel)
    record={'status':'waiting_for_full_audited_boundary','pid':os.getpid(),'birth':processes()[os.getpid()]['birth'],
            'old_root':str(OLD),'next_root':str(ROOT),'deadline_utc':None,'automatic_messages_enabled':False,
            'requested_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    try:
        while True:
            require(not cancelled,'Handoff explicitly stopped; no new jobs')
            state=load(OLD/'state.json');table=processes()
            record.update(old_phase=state['phase'],updated_utc=dt.datetime.now(dt.timezone.utc).isoformat())
            write(ROOT/'handoff.json',record)
            if matches(table,old_launch):
                require(state['phase'] in ('training32_opening2_audit','paused_at_boundary'),'Unexpected old phase; review required')
                time.sleep(10);continue
            require(state['phase']=='paused_at_boundary','Old controller did not reach requested clean boundary')
            require((OLD/'pause_at_boundary').exists(),'Old pause marker removed')
            require(state['completed_stages']==['training64_opening1_review','training32_opening2_clock','training32_opening2_audit'],
                    'Old queue advanced beyond the authorized handoff boundary')
            old_guard={'pid':old_launch['watcher_pid'],'birth':old_launch['watcher_birth'],
                       'command':[PYTHON,str(OLD/'safety/watch.py'),'--output',str(OLD)]}
            supervisor={'pid':old_handoff['pid'],'birth':old_handoff['birth'],
                        'command':[PYTHON,str(OLD/'tools/handoff.py')]}
            if matches(table,old_guard) or matches(table,supervisor) or native_engines(table) or not lock_owners_free(old_plan['lock_paths']):
                time.sleep(5);continue
            break
        require(not cancelled,'Handoff stopped before preparation')
        summary=load(OLD/'training-32/pair-002/audit/summary.json')
        require(summary['status']=='completed' and summary['scope']=='tested-engine-only', 'Old audit incomplete/wrong scope')
        require(summary['judge_binary_sha256']==old_plan['judge_sha256'],'Old judge identity differs')
        require(not any(x['mistakes'] or x['blunders'] for x in summary['by_engine'].values()),'Old detected failure needs review')
        subprocess.run([PYTHON,str(OLD/'observations/checkpoint_counter.py'),'--plan',str(OLD/'plan.json')],check=True,
                       stdout=subprocess.DEVNULL)
        evidence=load(OLD/'checkpoint-latest.json')
        require(not evidence['controller_live'] and not evidence['guard_live'] and evidence['clocked_games']==0
                and evidence['judge_workers_active']==0 and not evidence['unowned_engine_processes'],'Old jobs remain')
        require(all(x['audit_complete'] for x in evidence['by_configuration'].values()),'Old complete sample has pending moves')
        write(ROOT/'observations/preserved-rapid-boundary.json',evidence)
        record['status']='preparing_at_safe_idle_boundary';write(ROOT/'handoff.json',record)
        plan=prepare()
        check=subprocess.run([PYTHON,str(ROOT/'tools/preflight.py'),'--plan',str(ROOT/'plan.json'),'--fixtures-only'],check=True,
                             stdout=subprocess.PIPE,text=True)
        write(ROOT/'metadata-checks-at-boundary.json',{'status':'passed','stdout':check.stdout,'engine_searches':0})
        finalize_ready(plan)
        require(not cancelled and not native_engines(processes()) and lock_owners_free(plan['lock_paths']),
                'Resources no longer idle after preparation')
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
        guard_cmd=[PYTHON,str(ROOT/'safety/watch.py'),'--output',str(ROOT)]
        controller_cmd=[PYTHON,str(ROOT/'tools/controller.py'),'--plan',str(ROOT/'plan.json')]
        with (ROOT/'watch.log').open('a') as log:
            guard_process=subprocess.Popen(guard_cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=env)
        guard_row=processes().get(guard_process.pid);require(guard_row is not None,'Guard exited before launch')
        guard={'pid':guard_process.pid,'birth':guard_row['birth'],'pgid':guard_row['pgid'],'command':guard_cmd}
        write(ROOT/'watch-launch.json',guard)
        with (ROOT/'controller.log').open('a') as log:
            controller_process=subprocess.Popen(controller_cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=env)
        row=processes().get(controller_process.pid);require(row is not None,'Controller exited before identity capture')
        controller={'pid':controller_process.pid,'birth':row['birth'],'pgid':row['pgid'],'command':controller_cmd,
                    'watcher_pid':guard['pid'],'watcher_birth':guard['birth'],'plan_sha256':digest(ROOT/'plan.json'),
                    'started_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'no_fixed_user_cutoff':True,
                    'automatic_messages_enabled':False,'candidate_adoption':False}
        write(ROOT/'launch.json',controller)
        record.update(status='running_guarded_followon',controller=controller,guard=guard,started_utc=controller['started_utc'])
        write(ROOT/'handoff.json',record);publish_globals(controller,guard)
        code=controller_process.wait()
        guard_process.wait(timeout=30)
        record.update(status='followon_stopped_check_state',exit_code=code,
                      ended_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        write(ROOT/'handoff.json',record)
    except Exception as error:
        record.update(status='blocked_preserved_for_review',error=f'{type(error).__name__}: {error}',
                      updated_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        write(ROOT/'handoff.json',record)
        raise
    finally:lock.close()


if __name__=='__main__':main()
