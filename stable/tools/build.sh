#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
wetmeat_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
wetmeat_arch="${1:-native}"
wetmeat_jobs="${WETMEAT_JOBS:-2}"
cd "$wetmeat_root/src"
make -j "$wetmeat_jobs" profile-build ARCH="$wetmeat_arch" EXE=wetmeat \
    GIT_SHA=49ea5ded GIT_DATE=20260930 GIT_DIFFINDEX=1
mkdir -p "$wetmeat_root/bin"
cp wetmeat "$wetmeat_root/bin/wetmeat-local"
"$wetmeat_root/bin/wetmeat-local" bench > /dev/null 2> "$wetmeat_root/docs/local-bench.log"
printf '%s\n' "Engine: $wetmeat_root/bin/wetmeat-local"
