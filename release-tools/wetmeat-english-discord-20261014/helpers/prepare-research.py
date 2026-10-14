"""Copy the supplied stable model into the archived research source folders."""
# SPDX-License-Identifier: GPL-3.0-or-later
from hashlib import sha256
from pathlib import Path
import shutil


def file_hash(path):
    checksum = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def main():
    root = Path(__file__).resolve().parent
    model = root / 'stable/src/nn-252f33942263.nnue'
    expected = '252f33942263bc8b8f740ba8aec3fed5a159ff148113c47a55c18c33d6627ab3'
    if file_hash(model) != expected:
        raise SystemExit('The supplied model failed its SHA256 check.')

    for project in ('timing', 'draw-aversion'):
        target = root / 'research' / project / 'src' / model.name
        if not target.exists():
            shutil.copyfile(model, target)
        if file_hash(target) != expected:
            raise SystemExit(f'The existing research model does not match: {target}')
        print(target.relative_to(root))


if __name__ == '__main__':
    main()
