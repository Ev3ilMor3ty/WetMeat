"""Alternate identical-core builds at fixed work. SPDX-License-Identifier: GPL-3.0-or-later."""

import argparse
import hashlib
import json
import re
import statistics
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engines", type=Path, nargs="+", required=True)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--signature", type=int, default=1714434)
    parser.add_argument("--output", type=Path, default=Path("docs/cpu-benchmark.json"))
    args = parser.parse_args()
    results = {engine.name: [] for engine in args.engines}
    for index in range(args.runs):
        for engine in (args.engines if index % 2 == 0 else args.engines[::-1]):
            output = subprocess.run([str(engine.resolve()), "bench"], capture_output=True,
                                    text=True, check=True, timeout=60).stderr
            nodes = int(re.search(r"Nodes searched\s*:\s*(\d+)", output).group(1))
            elapsed = int(re.search(r"Total time \(ms\)\s*:\s*(\d+)", output).group(1))
            if nodes != args.signature:
                raise AssertionError(f"Different work: {engine}: {nodes}")
            results[engine.name].append(elapsed)
    report = {"signature": args.signature, "timings_ms": results,
              "median_ms": {name: statistics.median(values) for name, values in results.items()},
              "binary_sha256": {engine.name: hashlib.file_digest(engine.open("rb"), "sha256").hexdigest()
                                for engine in args.engines},
              "method": "Alternating binaries, identical fixed-depth bench and nodes. Run on an otherwise idle machine; this measures speed, not Elo."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
