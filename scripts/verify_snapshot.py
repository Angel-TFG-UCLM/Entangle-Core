"""Verify an Entangle snapshot without a database or network connection."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.snapshot import SnapshotError, load_bundle


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify manifest version, checksums, and row counts."
    )
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        manifest, collections = load_bundle(args.snapshot)
    except SnapshotError as exc:
        print(f"Snapshot verification failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Verified {manifest['format']} v{manifest['version']}: {sum(map(len, collections.values()))} documents"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
