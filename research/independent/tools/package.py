"""Package an independently written, verified build. SPDX-License-Identifier: GPL-3.0-or-later."""
import hashlib
import json
import zipfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    sha = hashlib.sha256((root / 'bin/wetmeat').read_bytes()).hexdigest()
    for name in ['verification.json', 'protocol.json', 'tactics.json']:
        report = json.loads((root / 'results' / name).read_text())
        assert report['status'] == 'passed' and report['engine_sha256'] == sha, name
    files = [p for p in root.rglob('*') if p.is_file() and
             '__pycache__' not in p.parts and 'overnight' not in p.parts and
             p.name != 'wetmeat-sanitize' and
             p.suffix not in ('.tmp', '.lock', '.log')]
    contents = {p.relative_to(root).as_posix(): p.read_bytes() for p in files}
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    contents['SHA256SUMS.txt'] = ''.join(f'{sha}  {name}\n' for name, sha in sorted(hashes.items())).encode()
    target = root.parent / 'wetmeat-independent.zip'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(contents.items()):
            entry = zipfile.ZipInfo('wetmeat-independent/' + name)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = ((root / name).stat().st_mode if (root / name).exists() else 0o100644) << 16
            archive.writestr(entry, data)
    with zipfile.ZipFile(target) as archive:
        for name, data in contents.items():
            assert archive.read('wetmeat-independent/' + name) == data
        assert archive.getinfo('wetmeat-independent/bin/wetmeat').external_attr >> 16 & 0o111
    manifest = {'file': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                'bytes': target.stat().st_size, 'files': len(contents), 'engine_sha256': sha,
                'complete_corresponding_source_included': True, 'Stockfish_code_or_weights_in_engine': False,
                'limitations': 'Initial independent prototype, not proven comparable to Stockfish.'}
    (root.parent / 'wetmeat-independent-package.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
