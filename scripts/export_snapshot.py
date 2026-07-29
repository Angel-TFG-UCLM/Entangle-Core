"""Export an authorized Mongo dataset as a versioned Entangle snapshot."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pymongo import MongoClient
from src.core.snapshot import write_bundle


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export Entangle application documents; credentials are never exported."
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Directory or .tar.gz bundle outside source control",
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.getenv("MONGO_URI"),
        help="Authorized Mongo URI (or MONGO_URI)",
    )
    parser.add_argument(
        "--database", default=os.getenv("MONGO_DB_NAME", "quantum_github")
    )
    parser.add_argument(
        "--redact-field",
        action="append",
        default=[],
        help="Additional case-insensitive field name to redact",
    )
    args = parser.parse_args()
    if not args.mongo_uri:
        parser.error("--mongo-uri or MONGO_URI is required")
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=10_000)
    try:
        client.admin.command("ping")
        database = client[args.database]
        names = sorted(
            name
            for name in database.list_collection_names()
            if not name.startswith("system.")
        )
        collections = {
            name: database[name].find({}, sort=[("_id", 1)]) for name in names
        }
        indexes = {
            name: [
                dict(index)
                for index in database[name].list_indexes()
                if index.get("name") != "_id_"
            ]
            for name in names
        }
        manifest = write_bundle(
            args.output,
            collections,
            database_name=args.database,
            redact_fields=args.redact_field,
            indexes=indexes,
        )
        print(
            f"Exported {len(manifest['collections'])} collections; verify with scripts/verify_snapshot.py"
        )
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
