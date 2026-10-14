"""Local first-100-game report; no searches, messages or queue changes. GPL-3.0-or-later."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import time


def load(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n' if isinstance(data, dict) else data)
    os.replace(temporary, path)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(pid):
    try:
        path = Path('/proc') / str(pid)
        stat = (path / 'stat').read_text().split(') ', 1)[1].split()
        args = (path / 'cmdline').read_bytes().decode().rstrip('\0').split('\0')
        return {'pid': pid, 'birth': stat[19], 'command': args, 'state': stat[0]}
    except (FileNotFoundError, ProcessLookupError):
        return None


def matches(row, expected):
    return bool(row and row['state'] != 'Z' and row['birth'] == expected['birth']
                and row['command'] == expected['command'])


def collect(root, plan):
    """Read only post-audit checksummed batch exports; keep the scope at games 1..100."""
    totals = {side: {'moves': 0, 'checked_moves': 0, 'mistakes': 0, 'blunders': 0,
                     'shallow_judge_moves': 0} for side in ('wetmeat', 'stockfish')}
    sources = []
    seen = set()
    scores = {'wins': 0, 'draws': 0, 'losses': 0}
    for index in range(1, 6):
        directory = root / 'training' / f'batch-{index:03d}'
        path = directory / 'batch-evidence.json'
        ready = directory / 'batch-evidence-ready.json'
        if not path.exists() or not ready.exists():
            break
        checksum = digest(path)
        require(checksum == load(ready)['sha256'], 'Batch evidence checksum differs')
        data = load(path)
        require(data['schema'] == 'both-engine-batch-v1' and data['phase'] == 'training',
                'Different study scope')
        require(data['requested_movetime_ms'] == 100, 'Different move time')
        for key in ('stable_sha256', 'opponent_sha256', 'common_uci', 'audit_settings'):
            require(data[key] == plan[key], 'Different frozen engines/resources/judge: ' + key)
        require(data['audit_complete'] and data['completed_games'] == 20
                and data['engine_faults'] == data['incomplete_games_excluded'] == 0,
                'Incomplete/faulted batch cannot give full-sample rates')
        require(len(data['files']) == 20, 'Missing/duplicate game evidence')
        expected = {str(directory / f'game-{number:04d}.json')
                    for number in range(20 * (index - 1) + 1, 20 * index + 1)}
        actual = {entry['game'] for entry in data['files']}
        require(actual == expected and not seen.intersection(actual), 'Wrong or duplicate rounds')
        seen.update(actual)
        require(all(entry['audit_complete'] and all(isinstance(entry.get(key), str)
                    and len(entry[key]) == 64 for key in ('game_sha256', 'pgn_sha256', 'audit_sha256'))
                    for entry in data['files']), 'Missing completed game/audit identities')
        require(set(data['by_pair']) == {str(pair) for pair in range(10 * (index - 1) + 1, 10 * index + 1)}
                and all(row['games'] == 2 for row in data['by_pair'].values()), 'Unpaired evidence')
        require(sum(data[key] for key in scores) == 20, 'Inconsistent scores')
        for key in scores:
            require(isinstance(data[key], int) and data[key] >= 0, 'Invalid score count')
            scores[key] += data[key]
        for side, stats in totals.items():
            source = data['by_engine'][side]
            require(all(isinstance(source[key], int) and source[key] >= 0 for key in stats),
                    'Invalid move/error counts')
            require(source['moves'] == source['checked_moves'] and source['moves'] > 0,
                    'Incomplete engine move coverage')
            require(source['mistakes'] + source['blunders'] <= source['moves']
                    and source['shallow_judge_moves'] <= source['moves'], 'Impossible error counts')
            for key in stats:
                stats[key] += source[key]
        sources.append({'batch': index, 'file': str(path), 'sha256': checksum,
                        'readiness_file': str(ready), 'game_identities': data['files']})
    complete = len(sources) == 5
    for stats in totals.values():
        stats['mistake_rate'] = stats['mistakes'] / stats['moves'] if complete else None
        stats['blunder_rate'] = stats['blunders'] / stats['moves'] if complete else None
    return {'status': 'complete' if complete else 'waiting_for_full_audits',
            'target_games': 100, 'fully_audited_games': len(sources) * 20,
            'fully_audited_batches': len(sources), 'scope': 'first100-baseline-training-fixed100ms',
            'complete_100_game_comparison': complete, 'scores_of_fully_audited_games': scores,
            'by_engine': totals, 'evidence_sources': sources, 'candidate_adopted': False,
            'engine_changes': 0, 'automatic_messages_enabled': False,
            'limits': 'This is a subset of the predeclared1000-game baseline TRAINING study. '
                      'Finite Stockfish-family judge, shallower depths and correlated openings limit conclusions. '
                      'Point estimates do not establish superiority, Elo or perfect play. '
                      'Corrections require supported isolated candidates and fresh matched-control validation.'}


def render(report):
    lines = ['# First100games: WetMeat versus Stockfish19', '',
             f"Completed games: {report['completed_games_toward_100']}/100. "
             f"Fully audited and exported: {report['fully_audited_games']}/100.", '']
    if report['complete_100_game_comparison']:
        scores = report['scores_of_fully_audited_games']
        lines += [f"WetMeat: {scores['wins']}wins, {scores['draws']}draws, {scores['losses']}losses.", '',
                  '| Engine | Moves checked/total | Mistakes | Blunders | Mistake rate | Blunder rate | Shallower judge depths |',
                  '|---|---|---|---|---|---|---|']
        for side, stats in report['by_engine'].items():
            lines.append(f"| {side} | {stats['checked_moves']}/{stats['moves']} | {stats['mistakes']} | "
                         f"{stats['blunders']} | {stats['mistake_rate']:.3%} | {stats['blunder_rate']:.3%} | "
                         f"{stats['shallow_judge_moves']} |")
    else:
        lines += ['Both-engine error rates are unavailable until all first100games are fully audited.', '']
    lines += ['', 'Both engines:100ms per move, Threads1, Hash128, Skill20, no Elo limit/ponder/tablebases. '
              'Mistake50..199cp, blunder>=200cp. Book plies excluded. All first100completed wins/draws/losses retained.', '',
              report['limits'], '', 'The existing frozen queue continues toward1000games. '
              'This report sends no automatic messages and does not stop or modify the queue.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    observation = root / 'observations'
    lock = (observation / 'milestone100.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    ready = load(observation / 'milestone100-ready.json')
    require(digest(__file__) == ready['source_sha256'], 'Observer source changed')
    require(digest(root / 'plan.json') == ready['plan_sha256'] == load(root / 'ready.json')['plan_sha256'],
            'Observer and frozen study plans differ')
    plan = load(root / 'plan.json')
    require(plan['games'] == 1000 and plan['pairs_per_batch'] == 10 and plan['deadline_utc'] is None,
            'Different queue or cancelled cutoff restored')
    launch = load(root / 'launch.json')
    cancelled = False

    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    watch = {'observer': identity(os.getpid()), 'root': str(root), 'deadline_utc': None,
             'queue_control': False, 'engine_searches': False, 'automatic_messages_enabled': False}
    try:
        while not cancelled:
            require(digest(root / 'plan.json') == ready['plan_sha256'], 'Frozen plan changed')
            report = collect(root, plan)
            progress = load(root / 'progress.json')
            report.update(snapshot_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                          plan_sha256=ready['plan_sha256'],
                          completed_games_toward_100=min(100, progress['completed_games']),
                          full_queue_completed_games=progress['completed_games'])
            write(observation / 'milestone-100.json', report)
            write(observation / 'milestone-100.md', render(report))
            live = matches(identity(launch['pid']), launch)
            watch.update(status=report['status'], updated_utc=report['snapshot_utc'],
                         controller_live=live, fully_audited_games=report['fully_audited_games'])
            if report['complete_100_game_comparison']:
                watch['status'] = 'finished_first100_report_queue_continues'
            elif not live:
                watch['status'] = 'stopped_before100_preserving_partial_evidence'
            write(observation / 'milestone100-watch.json', watch)
            if report['complete_100_game_comparison'] or not live:
                return
            for _ in range(60):
                if cancelled:
                    break
                time.sleep(1)
        watch.update(status='observer_stopped_queue_untouched', updated_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        write(observation / 'milestone100-watch.json', watch)
    except Exception as error:
        watch.update(status='blocked_queue_untouched', error=str(error), updated_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        write(observation / 'milestone100-watch.json', watch)
        raise


if __name__ == '__main__':
    main()
