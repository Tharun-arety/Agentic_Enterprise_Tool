"""Binary storage behind one interface.

Two implementations, following the same pattern as the embedding providers and
the model clients: a real one, and a local fallback that keeps the whole system
runnable before the real one is configured.

*   `S3FileStore` — any S3-compatible endpoint, which in this stack means MinIO
    in the compose file.
*   `LocalFileStore` — writes under a directory on disk. The default, so
    `git clone && seed && run` works with no object store at all.

Keys are content-addressed: the SHA-256 of the bytes, sharded two levels deep so
no single directory or prefix accumulates every file in the vault. Two uploads
of identical content collapse onto one object, which for CAD revisions — where
a "new revision" is frequently a re-export of unchanged geometry — is most of
them.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class FileStoreError(Exception):
    """The object could not be stored or retrieved."""


def content_key(data: bytes, filename: str) -> tuple[str, str]:
    """Return `(sha256_hex, storage_key)` for a blob.

    The original filename is kept as the last segment so an operator browsing
    the bucket sees something recognisable rather than a wall of hashes.
    """
    digest = hashlib.sha256(data).hexdigest()
    safe = Path(filename).name.replace("/", "_").replace("\\", "_") or "file"
    return digest, f"{digest[:2]}/{digest[2:4]}/{digest}/{safe}"


class FileStore(ABC):
    name: str = "abstract"
    is_durable: bool = False

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    @abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...


class LocalFileStore(FileStore):
    """Filesystem-backed. Fine for one machine; not shared between replicas."""

    name = "local-filesystem"
    is_durable = False

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Resolve and re-check containment: a key is data, and a crafted one
        # containing `..` would otherwise write outside the vault.
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root.resolve()):
            raise FileStoreError(f"Refusing to use a key that escapes the vault: {key!r}")
        return candidate

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Content-addressed, so an existing object with this key has identical
        # bytes and rewriting it would be pure cost.
        if not path.exists():
            path.write_bytes(data)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise FileStoreError(f"No stored object for key {key!r}.")
        return path.read_bytes()

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()


class S3FileStore(FileStore):
    """S3-compatible object storage (MinIO in the compose stack)."""

    name = "s3"
    is_durable = True

    def __init__(self) -> None:
        # Imported lazily so the dependency is only needed when configured.
        import boto3  # type: ignore[import-untyped]

        settings = get_settings()
        self._bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )

    async def get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001 - botocore's tree is broad
            raise FileStoreError(f"No stored object for key {key!r}: {exc}") from exc
        return response["Body"].read()

    async def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception:  # noqa: BLE001
            return False
        return True


_store: FileStore | None = None


def get_file_store() -> FileStore:
    """The S3 store when one is configured, else the local filesystem."""
    global _store
    if _store is not None:
        return _store

    settings = get_settings()
    if settings.s3_bucket:
        try:
            _store = S3FileStore()
            logger.info("File vault: S3 bucket %r.", settings.s3_bucket)
            return _store
        except ImportError:
            logger.warning(
                "S3_BUCKET is set but boto3 is not installed; falling back to "
                "the local filesystem vault. Install boto3 to use object storage."
            )

    _store = LocalFileStore(Path(settings.file_vault_path))
    logger.info("File vault: local filesystem at %s.", settings.file_vault_path)
    return _store


def reset_file_store() -> None:
    """Drop the cached store (used by tests)."""
    global _store
    _store = None
