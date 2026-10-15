#!/usr/bin/env bash
set -euo pipefail
part_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
archive="$part_dir/WetMeat-Windows.zip"
expected='9970fac79458cac93ddc8974d58571606a0d0f7419c9cbf1136a98e8efd6ce53'
if [[ -e $archive ]]; then
    printf '%s  %s\n' "$expected" "$archive" | sha256sum --strict --check -
    echo "Ready: $archive"
    exit 0
fi
for ((number=1; number<=10; number++)); do
    printf -v name 'WetMeat-Windows.zip.part%03d' "$number"
    if [[ ! -f "$part_dir/$name" ]]; then
        echo "Missing part: $name" >&2
        exit 1
    fi
done
temporary="$(mktemp "$part_dir/.wetmeat-join.XXXXXX")"
trap 'rm -f -- "$temporary"' EXIT
for ((number=1; number<=10; number++)); do
    printf -v name 'WetMeat-Windows.zip.part%03d' "$number"
    cat -- "$part_dir/$name" >> "$temporary"
done
printf '%s  %s\n' "$expected" "$temporary" | sha256sum --strict --check -
ln -- "$temporary" "$archive"
echo "Ready: $archive"
echo 'Extract this ZIP and read README.txt inside it.'
