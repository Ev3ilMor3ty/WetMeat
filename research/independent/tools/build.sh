#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
wetmeat_project="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$wetmeat_project/bin"
"${CXX:-g++}" -std=c++17 -O3 -DNDEBUG -pthread -Wall -Wextra -Wpedantic \
  "$wetmeat_project/src/wetmeat.cpp" -o "$wetmeat_project/bin/wetmeat"
