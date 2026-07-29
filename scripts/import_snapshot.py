"""Restore a verified Entangle snapshot into an explicitly authorized Mongo target."""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pymongo import MongoClient
from src.core.snapshot import load_bundle


def recreate_indexes(collection, definitions: list[dict]) -> None:
    expected = {}
    for definition in definitions:
        key = definition.get("key")
        if isinstance(key, dict):
            key_pairs = list(key.items())
        elif isinstance(key, list):
            key_pairs = [tuple(item) for item in key]
        else:
            key_pairs = []
        if not key_pairs:
            raise RuntimeError(f"Invalid index key for {collection.name}")
        options = {
            name: value
            for name, value in definition.items()
            if name not in {"key", "ns", "v"}
        }
        index_name = options.get("name")
        if index_name:
            expected[index_name] = {
                "key": key_pairs,
                "options": {
                    name: value
                    for name, value in options.items()
                    if name != "name"
                },
            }
        collection.create_index(key_pairs, **options)

    actual = {
        index.get("name"): index
        for index in collection.list_indexes()
        if index.get("name") != "_id_"
    }
    for name, metadata in expected.items():
        if name not in actual:
            raise RuntimeError(f"Index verification failed for {collection.name}: {name}")
        actual_key = actual[name].get("key", {})
        actual_pairs = (
            list(actual_key.items())
            if isinstance(actual_key, dict)
            else [tuple(item) for item in actual_key]
        )
        if actual_pairs != metadata["key"]:
            raise RuntimeError(
                f"Index key mismatch for {collection.name}.{name}: {actual_pairs}"
            )
        for option, value in metadata["options"].items():
            if actual[name].get(option) != value:
                raise RuntimeError(
                    f"Index option mismatch for {collection.name}.{name}: {option}"
                )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore a verified snapshot; it never reads source credentials."
    )
    parser.add_argument("snapshot", type=Path)
    parser.add_argument(
        "--mongo-uri",
        default=os.getenv("MONGO_URI"),
        help="Authorized target URI (or MONGO_URI)",
    )
    parser.add_argument(
        "--database", default=None, help="Override target database name"
    )
    args = parser.parse_args()
    if not args.mongo_uri:
        parser.error("--mongo-uri or MONGO_URI is required")
    manifest, collections = load_bundle(args.snapshot)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=10_000)
    try:
        client.admin.command("ping")
        target_name = args.database or manifest["database_name"]
        # Restore into a wholly new database. Cutover is an explicit
        # configuration change (MONGO_DB_NAME), never a mixed collection rename.
        restored_name = f"{target_name}__restore_{uuid.uuid4().hex[:12]}"
        database = client[restored_name]
        for name, documents in collections.items():
            if documents:
                database[name].insert_many(documents, ordered=True)
            else:
                # Explicitly create empty collections so schema completeness is
                # verified before the future application cutover.
                database.create_collection(name)
            if database[name].count_documents({}) != len(documents):
                raise RuntimeError(f"Preflight count mismatch for {name}")
            recreate_indexes(
                database[name],
                manifest["collections"].get(name, {}).get("indexes", []),
            )
        print(
            f"Restored {len(collections)} verified collections into {database.name}. "
            f"Cut over by setting MONGO_DB_NAME={database.name}; the existing database was untouched."
        )
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
