#!/usr/bin/env bash
# Local Wine verification helper, not required to run the Windows executable.
set -euo pipefail
wetmeat_project="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec /workspace/scratch/run-aurora-wine "$wetmeat_project/bin/wetmeat-windows.exe" "$@"
