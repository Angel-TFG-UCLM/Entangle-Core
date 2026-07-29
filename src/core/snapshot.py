"""Versioned, checksummed Entangle snapshot bundles.

Bundles contain only application documents.  Credentials are never read by this
module and field-name redaction is applied before a bundle is written.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from bson import json_util

FORMAT = "entangle-snapshot"
VERSION = 1
DEFAULT_REDACT_FIELDS = {
    "password",
    "password_hash",
    "token",
    "secret",
    "api_key",
    "authorization",
}
EXCLUDED_COLLECTIONS = {"admin_config", "auth", "authentication", "chat_sessions"}


class SnapshotError(ValueError):
    """Raised when a snapshot cannot be safely used."""


def _is_excluded_collection(name: str) -> bool:
    normalized = name.lower()
    return normalized in EXCLUDED_COLLECTIONS or normalized.startswith(
        ("admin", "auth")
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _redact(value: Any, fields: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in fields else _redact(item, fields)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, fields) for item in value]
    return value


def _collection_payload(
    documents: Iterable[Mapping[str, Any]], redact_fields: set[str]
) -> bytes:
    # BSON Extended JSON keeps ObjectId and datetimes restorable.
    lines = [
        json_util.dumps(_redact(dict(document), redact_fields), sort_keys=True)
        for document in documents
    ]
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _index_definition(index: Mapping[str, Any]) -> Dict[str, Any]:
    definition = dict(index)
    key = definition.get("key")
    if isinstance(key, Mapping):
        definition["key"] = [[name, direction] for name, direction in key.items()]
    return json_util.loads(json_util.dumps(definition))


def write_bundle(
    output: Path,
    collections: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    database_name: str,
    redact_fields: Sequence[str] = (),
    extra_files: Mapping[str, bytes] | None = None,
    indexes: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> Dict[str, Any]:
    """Write a directory or ``.tar.gz`` snapshot and return its manifest."""
    fields = DEFAULT_REDACT_FIELDS | {field.lower() for field in redact_fields}
    files: Dict[str, bytes] = {}
    collection_manifest: Dict[str, Dict[str, Any]] = {}
    indexes = indexes or {}
    excluded = sorted(name for name in collections if _is_excluded_collection(name))
    for name in sorted(collections):
        if _is_excluded_collection(name):
            continue
        payload = _collection_payload(collections[name], fields)
        relative_path = f"collections/{name}.jsonl"
        files[relative_path] = payload
        collection_manifest[name] = {
            "path": relative_path,
            "document_count": 0 if not payload else payload.count(b"\n"),
            "sha256": _sha256(payload),
            "indexes": [
                _index_definition(index)
                for index in indexes.get(name, [])
                if index.get("name") != "_id_"
            ],
        }
    extra_files = extra_files or {}
    for relative_path in extra_files:
        if (
            relative_path == "manifest.json"
            or relative_path.startswith("/")
            or ".." in Path(relative_path).parts
        ):
            raise SnapshotError(
                f"Nombre de archivo auxiliar no seguro: {relative_path}"
            )
    files.update(extra_files)
    manifest: Dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database_name": database_name,
        "collections": collection_manifest,
        "files": {
            name: {"sha256": _sha256(payload)}
            for name, payload in sorted(extra_files.items())
        },
        "redacted_fields": sorted(fields),
        "excluded_collections": excluded,
        "restore_notes": [
            "Administrative and authentication data are excluded; establish a new admin after restore."
        ],
    }
    manifest_payload = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    output = Path(output)
    if output.exists() and (output.is_file() or any(output.iterdir())):
        raise SnapshotError("El destino del snapshot debe ser nuevo o un directorio vacío")
    if output.suffixes[-2:] == [".tar", ".gz"] or output.suffix == ".tgz":
        output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output, "w:gz") as archive:
            for name, payload in {**files, "manifest.json": manifest_payload}.items():
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
    else:
        output.mkdir(parents=True, exist_ok=True)
        for name, payload in files.items():
            destination = output / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        (output / "manifest.json").write_bytes(manifest_payload)
    return manifest


def _read_files(path: Path) -> Dict[str, bytes]:
    if not str(path).strip():
        raise SnapshotError("La ruta del snapshot no puede estar vacía")
    if path.is_dir():
        return {
            str(item.relative_to(path)).replace("\\", "/"): item.read_bytes()
            for item in path.rglob("*")
            if item.is_file()
        }
    if not tarfile.is_tarfile(path):
        raise SnapshotError("El snapshot debe ser un directorio o archivo tar.gz")
    with tarfile.open(path, "r:*") as archive:
        files = {}
        for member in archive.getmembers():
            if (
                not member.isfile()
                or member.name.startswith("/")
                or ".." in Path(member.name).parts
            ):
                raise SnapshotError("El snapshot contiene una ruta no segura")
            extracted = archive.extractfile(member)
            if extracted is not None:
                files[member.name] = extracted.read()
        return files


def load_bundle(
    path: str | Path,
) -> tuple[Dict[str, Any], Dict[str, list[Dict[str, Any]]]]:
    """Verify and load a snapshot without connecting to any external service."""
    if not str(path).strip():
        raise SnapshotError("La ruta del snapshot no puede estar vacía")
    return _load_bundle_files(_read_files(Path(path)))


def _load_bundle_files(
    files: Dict[str, bytes],
) -> tuple[Dict[str, Any], Dict[str, list[Dict[str, Any]]]]:
    try:
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError("manifest.json no válido") from exc
    if manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
        raise SnapshotError("Formato o versión de snapshot no compatible")
    forbidden = {
        name
        for name in manifest.get("collections", {})
        if _is_excluded_collection(name)
    }
    if forbidden:
        raise SnapshotError(
            f"El snapshot contiene colecciones administrativas prohibidas: {sorted(forbidden)}"
        )
    expected_files = {"manifest.json"}
    expected_files.update(
        metadata.get("path", "")
        for metadata in manifest.get("collections", {}).values()
    )
    expected_files.update(manifest.get("files", {}).keys())
    if set(files) != expected_files or "" in expected_files:
        raise SnapshotError("El snapshot contiene archivos inesperados o faltantes")
    collections: Dict[str, list[Dict[str, Any]]] = {}
    for name, metadata in manifest.get("collections", {}).items():
        relative_path = metadata.get("path", "")
        payload = files.get(relative_path)
        if payload is None or _sha256(payload) != metadata.get("sha256"):
            raise SnapshotError(f"Checksum inválido para la colección {name}")
        rows = [
            json_util.loads(line)
            for line in payload.decode("utf-8").splitlines()
            if line.strip()
        ]
        if len(rows) != metadata.get("document_count"):
            raise SnapshotError(f"Conteo inválido para la colección {name}")
        collections[name] = rows
    for name, metadata in manifest.get("files", {}).items():
        payload = files.get(name)
        if payload is None or _sha256(payload) != metadata.get("sha256"):
            raise SnapshotError(f"Checksum inválido para el archivo {name}")
    return manifest, collections


def load_offline_replies(path: str | Path) -> Dict[str, str]:
    """Load verified captured chat replies required by the offline provider."""
    if not str(path).strip():
        raise SnapshotError("La ruta del snapshot no puede estar vacía")
    files = _read_files(Path(path))
    manifest, _ = _load_bundle_files(files)
    if "offline_chat.json" not in manifest.get("files", {}):
        raise SnapshotError(
            "offline_chat.json verificado es obligatorio para el proveedor offline"
        )
    payload = files["offline_chat.json"]
    try:
        replies = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError("offline_chat.json no válido") from exc
    if not isinstance(replies, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in replies.items()
    ):
        raise SnapshotError(
            "offline_chat.json debe ser un mapa de preguntas y respuestas"
        )
    return {key.strip().lower(): value for key, value in replies.items()}
