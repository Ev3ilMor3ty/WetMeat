"""Build/check/freeze an original-fork experiment at a safe boundary. GPL-3.0-or-later."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path('/workspace/wetmeat-original-experiments/draw-aversion')
OUTPUT = Path('/workspace/aurora-stockfish/results/overnight-fallback')
STABLE = Path('/workspace/aurora-stockfish/bin/wetmeat-linux-avx512')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_digest():
    paths = sorted(p for p in (ROOT / 'src').rglob('*') if p.is_file()
                   and (p.suffix in ('.h', '.cpp', '.mk', '.sh', '.awk')
                        or p.name in ('Makefile', 'UNLICENCE')))
    paths += sorted(p for p in (ROOT / 'scripts').rglob('*') if p.is_file())
    paths += [ROOT / 'check_experiment.py', ROOT / 'README.md', ROOT / 'AUTHORS', ROOT / 'Copying.txt']
    data = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(), data


def save(path, data):
    temporary = path.with_suffix('.prepare.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    stages = parser.add_mutually_exclusive_group()
    stages.add_argument('--build-only', action='store_true', help='Compile during a fixed-node audit; defer all validation and idle speed checks')
    stages.add_argument('--checks-only', action='store_true', help='Run fixed-work correctness checks; defer idle speed checks and matches')
    args = parser.parse_args()
    lock = (OUTPUT / 'prepare.lock').open('w')
    # A staged compile and the queued validation must never overlap.
    fcntl.flock(lock, fcntl.LOCK_EX)
    cutoff = dt.datetime.fromisoformat(json.loads((OUTPUT / 'cutoff.json').read_text())['utc']).timestamp()
    if dt.datetime.now(dt.timezone.utc).timestamp() >= cutoff:
        raise RuntimeError('User cutoff reached; no build started')
    # Never run this pipeline beside a real-clock game, even if invoked manually.
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            process_args = (entry / 'cmdline').read_bytes().decode().split('\0')[:-1]
        except FileNotFoundError:
            continue
        if len(process_args) > 1 and process_args[1].endswith('/clock_match.py'):
            raise RuntimeError('A clocked match is still live; build refused')
    source_sha, sources = source_digest()
    ready = OUTPUT / 'candidate-ready.json'
    if ready.exists():
        previous = json.loads(ready.read_text())
        assert previous['source_manifest_sha256'] == source_sha
        assert digest(Path(previous['binary'])) == previous['binary_sha256']
        print('Existing verified candidate retained.', flush=True)
        return
    results = ROOT / 'results'; results.mkdir(exist_ok=True)
    binary = ROOT / 'src/wetmeat-draw-aversion'
    save(results / 'preparation.json', {'status': 'building', 'source_manifest_sha256': source_sha,
                                     'pid': os.getpid(), 'sources': sources})
    environment = dict(os.environ, LDFLAGS='-static')
    compile_record = results / 'compiled.json'
    compiled = json.loads(compile_record.read_text()) if compile_record.exists() else {}
    reuse = compiled.get('source_manifest_sha256') == source_sha and binary.exists()
    reuse = reuse and digest(binary) == compiled.get('binary_sha256')
    if not reuse:
        process = subprocess.Popen(['make', '-j1', 'profile-build', 'ARCH=x86-64-avx512icl',
                    'EXE=wetmeat-draw-aversion', 'GIT_SHA=49ea5ded', 'GIT_DATE=20260930',
                    'GIT_DIFFINDEX=1'], cwd=ROOT / 'src', env=environment, start_new_session=True)
        try:
            code = process.wait(timeout=900)
            if code:
                raise subprocess.CalledProcessError(code, process.args)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
        assert source_digest()[0] == source_sha, 'Source changed during compilation'
        save(compile_record, {'status': 'compiled_not_verified', 'binary': str(binary),
                             'binary_sha256': digest(binary), 'source_manifest_sha256': source_sha,
                             'created_utc': dt.datetime.now(dt.timezone.utc).isoformat()})
    if args.build_only:
        save(results / 'preparation.json', {'status': 'compiled_validation_queued',
                                           'source_manifest_sha256': source_sha, 'pid': os.getpid()})
        print('Native PGO compilation finished. No candidate selected; validation remains queued.', flush=True)
        return
    tools = Path('/workspace/aurora-stockfish/tools')
    check_fingerprints = {'binary': digest(binary), 'source': source_sha, 'reference': digest(STABLE),
                          'regression': digest(tools / 'regression.py'),
                          'protocol': digest(tools / 'protocol_regression.py'),
                          'client': digest(tools / 'uci_client.py')}
    checked_record = results / 'checked.json'
    checked = json.loads(checked_record.read_text()) if checked_record.exists() else {}
    commands = [
        [sys.executable, str(tools / 'regression.py'), '--engine', str(binary), '--reference', str(STABLE),
         '--positions', '50', '--output', str(results / 'zero-search-regression.json')],
        [sys.executable, str(tools / 'protocol_regression.py'), '--engine', str(binary),
         '--output', str(results / 'protocol.json')],
        [sys.executable, str(ROOT / 'check_experiment.py'), '--engine', str(binary),
         '--output', str(results / 'enabled-checks.json')],
    ]
    if checked.get('fingerprints') != check_fingerprints or checked.get('status') != 'passed':
        bench = subprocess.run([str(binary), 'bench'], capture_output=True, text=True, check=True, timeout=90)
        signature = int(re.search(r'Nodes searched\s*:\s*(\d+)', bench.stderr).group(1))
        assert signature == 1714434, f'Default-zero bench changed: {signature}'
        save(results / 'default-bench-signature.json', {'status': 'passed', 'signature': signature,
                                                     'binary_sha256': check_fingerprints['binary'],
                                                     'note': 'Fixed work only; concurrent node audits invalidate speed comparisons.'})
        for command in commands:
            subprocess.run(command, cwd=ROOT, check=True)
        save(checked_record, {'status': 'passed', 'fingerprints': check_fingerprints,
                              'created_utc': dt.datetime.now(dt.timezone.utc).isoformat()})
    subprocess.run([sys.executable, str(Path(__file__).with_name('check_draw_policy.py'))], check=True)
    subprocess.run([sys.executable, str(Path(__file__).with_name('check_match_failures.py'))], check=True)
    if args.checks_only:
        save(results / 'preparation.json', {'status': 'correctness_checked_speed_and_matches_queued',
                                           'source_manifest_sha256': source_sha, 'pid': os.getpid()})
        print('Correctness checks passed. Speed checks and candidate selection remain queued.', flush=True)
        return
    subprocess.run([sys.executable, str(tools / 'benchmark.py'), '--engines', str(binary), str(STABLE),
                    '--runs', '3', '--output', str(results / 'benchmark.json')], cwd=ROOT, check=True)
    speed = json.loads((results / 'benchmark.json').read_text())
    relative_ms = speed['median_ms'][binary.name] / speed['median_ms'][STABLE.name]
    if relative_ms > 1.05:
        raise RuntimeError(f'Candidate median bench is >5% slower ({relative_ms:.3f}); retain stable')
    assert source_digest()[0] == source_sha, 'Source changed during preparation'
    network = ROOT / 'src/nn-252f33942263.nnue'
    assert digest(network) == '252f33942263bc8b8f740ba8aec3fed5a159ff148113c47a55c18c33d6627ab3'
    data = {'status': 'verified_experimental', 'binary': str(binary), 'binary_sha256': digest(binary),
            'source_manifest_sha256': source_sha, 'draw_aversion': 16,
            'relative_benchmark_time': relative_ms,
            'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'network_sha256': digest(network), 'source': str(ROOT),
            'limitations': 'Unproven draw preference. Stable release unchanged; no match-score improvement established.'}
    save(results / 'frozen.json', data)
    archive = Path('/workspace/wetmeat-original-draw-aversion-experimental.tar')
    # Store the actual weight bytes, never a link to an external workspace path.
    with tarfile.open(archive.with_suffix('.tar.tmp'), 'w', dereference=True) as package:
        for directory in ('src', 'scripts', 'results'):
            for path in sorted((ROOT / directory).rglob('*')):
                if path.is_file() and path.suffix not in ('.o', '.d', '.gcda', '.gcno') and path.name != '.depend':
                    package.add(path, arcname='wetmeat-original-draw-aversion/' + str(path.relative_to(ROOT)), recursive=False)
        for name in ('AUTHORS', 'Copying.txt', 'README.md', 'check_experiment.py'):
            package.add(ROOT / name, arcname='wetmeat-original-draw-aversion/' + name)
        package.add(Path(__file__), arcname='wetmeat-original-draw-aversion/prepare_original.py')
    archive.with_suffix('.tar.tmp').replace(archive)
    data.update(package=str(archive), package_sha256=digest(archive))
    save(ready, data)
    save(results / 'preparation.json', {'status': 'passed', 'candidate': data})
    print(json.dumps(data), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        results = ROOT / 'results'
        results.mkdir(exist_ok=True)
        previous = results / 'preparation.json'
        state = json.loads(previous.read_text()) if previous.exists() else {}
        state.update(status='failed', error=str(error), pid=os.getpid())
        save(previous, state)
        raise
