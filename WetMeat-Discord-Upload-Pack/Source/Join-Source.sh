#!/usr/bin/env bash
set -euo pipefail
part_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
archive="$part_dir/WetMeat-Source.zip"
expected='d2c58b9aea067f9ddf9a57393c369cceea2d22f365bedd8035efe6039edcb603'
if [[ -e $archive ]]; then
    printf '%s  %s\n' "$expected" "$archive" | sha256sum --strict --check -
    echo "Ready: $archive"
    exit 0
fi
for ((number=1; number<=10; number++)); do
    printf -v name 'WetMeat-Source.zip.part%03d' "$number"
    if [[ ! -f "$part_dir/$name" ]]; then
        echo "Missing part: $name" >&2
        exit 1
    fi
done
temporary="$(mktemp "$part_dir/.wetmeat-join.XXXXXX")"
trap 'rm -f -- "$temporary"' EXIT
for ((number=1; number<=10; number++)); do
    printf -v name 'WetMeat-Source.zip.part%03d' "$number"
    cat -- "$part_dir/$name" >> "$temporary"
done
printf '%s  %s\n' "$expected" "$temporary" | sha256sum --strict --check -
ln -- "$temporary" "$archive"
echo "Ready: $archive"
echo 'Extract this ZIP and read README.txt inside it.'
