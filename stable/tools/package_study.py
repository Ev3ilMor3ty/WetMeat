"""Package the verified rapid study, without distributing engine binaries.

SPDX-License-Identifier: GPL-3.0-or-later.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


def main():
    project = Path(__file__).resolve().parents[1]
    workspace = project.parent
    study = project/'results/rapid-study'
    verification = json.loads((study/'verification.json').read_text())
    browser = json.loads((study/'browser-verification.json').read_text())
    assert verification['status'] == browser['status'] == 'passed'
    assert verification['all_recorded_wetmeat_moves_audited']
    assert sum(row['audited_wetmeat_moves'] for row in verification['checks']) == 247
    files = {path.relative_to(project).as_posix():path for path in study.rglob('*')
             if path.is_file() and path.suffix in ('.json','.pgn','.md','.log','.patch')}
    for name in ['clock_match.py','analyse_games.py','finalize_study.py','package_study.py',
                 'match.py','uci_client.py','protocol_regression.py','regression.py','benchmark.py',
                 'replays/create_study_report.py','replays/study.template.html']:
        files['tools/'+name] = project/'tools'/name
    for name in ['Copying.txt','AUTHORS','requirements-test.txt']:
        files[name] = project/name
    for name in ['wetmeat-rapid-study.html','wetmeat-rapid-study.json','wetmeat-rapid-study.png']:
        files[name] = workspace/name
    files['verification/mobile-preview.png'] = workspace/'scratch/wetmeat-study-mobile.png'
    files['verification/browser-check.cjs'] = workspace/'scratch/verify-wetmeat-study.cjs'
    files['stable-package-manifest.json'] = workspace/'wetmeat-packages.json'
    readme = '''# WetMeat real 10+5 study

Open wetmeat-rapid-study.html for the offline interactive report and all six
game replays. The recorded clocks are actual game clocks; animation speed
does not reproduce the original thinking delays. Detailed results are in
results/rapid-study/REPORT.md and every game is in all-games.pgn.

Both stable WetMeat and the frozen experimental candidate played against
full-strength Stockfish 19 with identical 600+5 clocks, one thread and 256 MB
hash each. All 247 non-book WetMeat moves were audited. Rates are finite-
engine estimates with explicit thresholds, not perfect ground truth or an
Elo certificate. Read METHOD.md, protocol.json and decision.json.

This archive contains reports, original game data, audit data, scripts and
the candidate source patch. It contains no engine executables or neural
networks. The existing wetmeat-linux.zip and wetmeat-windows.zip releases
remain stable WetMeat 1.0 and include their complete corresponding source,
networks, attribution and GPL license. Their manifest is included here.

To reproduce the candidate, extract the complete stable source package and
follow results/rapid-study/EXPERIMENT.md, applying candidate.patch in the
extracted wetmeat project. The candidate remains experimental. Source and
binary hashes frozen before validation are in candidate-frozen.json.

Python tools need python-chess; see requirements-test.txt. The match runner
requires Linux CPU affinity and UCI executables. Its --help describes exact
resource and opening controls. Pass a new --output directory when repeating
experiments to preserve the recorded data. The two opening indices were
0 (training) and 1 (held-out validation). The audit used --tested-only,
--min-nodes 1000000 --multiplier 2 --refine-multiplier 4 --hash 512.

verification.json independently checks legal moves, full audit coverage,
actual clock arithmetic, PGN clock rounding, paired colors, CPU rotation
and frozen binary/source identities. browser-verification.json records
the replay checks; verification/browser-check.cjs is the original browser
harness and uses the original /workspace paths and system Chromium.

SHA256SUMS.txt covers every other file in this archive. Sources retain
Stockfish attribution and GPL-3.0-or-later licensing; see Copying.txt.
'''
    contents = {name:path.read_bytes() for name,path in files.items()}
    contents['README.md'] = readme.encode()
    hashes = {name:hashlib.sha256(data).hexdigest() for name,data in contents.items()}
    contents['SHA256SUMS.txt'] = ''.join(f'{value}  {name}\n' for name,value in sorted(hashes.items())).encode()
    output = workspace/'wetmeat-study.zip'
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,data in sorted(contents.items()):
            archive.writestr('wetmeat-study/'+name,data)
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {'wetmeat-study/'+name for name in contents}
        for name,data in contents.items():
            assert archive.read('wetmeat-study/'+name) == data
    manifest = {'file':output.name,'bytes':output.stat().st_size,'files':len(contents),
                'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
                'all_packaged_files_verified':True,'engine_executables_included':False,
                'verified_games':6,'audited_wetmeat_moves':247}
    (workspace/'wetmeat-study-package.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))


if __name__ == '__main__':
    main()
