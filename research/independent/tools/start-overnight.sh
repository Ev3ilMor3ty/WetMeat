#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
wetmeat_project="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
wetmeat_python="${WETMEAT_PYTHON:-/workspace/aurora-chess/.venv/bin/python}"
wetmeat_opponent="${WETMEAT_OPPONENT:-/workspace/scratch/stockfish-19-source/src/stockfish-19-native}"
exec "$wetmeat_python" "$wetmeat_project/tools/overnight.py" \
  --engine "$wetmeat_project/releases/initial/wetmeat" \
  --candidate "$wetmeat_project/releases/candidate/wetmeat" \
  --opponent "$wetmeat_opponent" \
  --clock-runner "$wetmeat_project/tools/study/clock_match.py" \
  --audit-runner "$wetmeat_project/tools/study/analyse_games.py" \
  --pairs 48 --hours 10 --output "$wetmeat_project/results/overnight"
