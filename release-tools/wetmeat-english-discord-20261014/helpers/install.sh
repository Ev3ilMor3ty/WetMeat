#!/usr/bin/env bash
set -euo pipefail

package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
install_dir="${XDG_DATA_HOME:-$HOME/.local/share}/wetmeat/1.0-stable"

if [[ $# -gt 0 ]]; then
    if [[ $# -ne 2 || $1 != --prefix ]]; then
        echo 'Usage: bash install.sh [--prefix DIRECTORY]' >&2
        exit 2
    fi
    install_dir=$2
fi

if [[ -z $install_dir ]]; then
    echo 'Choose a non-empty installation directory.' >&2
    exit 2
fi
install_dir="$(realpath -m -- "$install_dir")"
if [[ "$install_dir/" == "$package_dir/"* ]]; then
    echo 'Choose an installation folder outside this extracted package.' >&2
    exit 2
fi

(
    cd -- "$package_dir"
    sha256sum --strict --check SHA256SUMS.txt
)

if [[ -e $install_dir ]]; then
    echo "The destination already exists: $install_dir" >&2
    echo 'Choose a new folder with --prefix to keep your existing installation.' >&2
    exit 1
fi

mkdir -p -- "$(dirname -- "$install_dir")"
cp -R -- "$package_dir" "$install_dir"
chmod +x "$install_dir/bin/wetmeat-linux-avx2" "$install_dir/bin/wetmeat-linux-avx512"

echo
echo 'WetMeat is installed. Add this file as a UCI engine in your chess interface:'
echo "$install_dir/bin/wetmeat-linux-avx2"
echo
echo 'Choose the AVX-512 file only if your CPU meets its requirements.'
echo 'Setup instructions are in README.txt.'
