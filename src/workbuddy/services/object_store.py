from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from workbuddy.settings import settings


class ObjectStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredObject:
    ref: str
    sha256: str
    size: int
    content_type: str


def _safe_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-.")
    return name[:180] or "artifact.bin"


class ObjectStore:
    def put(self, *, tenant_id: str, namespace: str, filename: str, data: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        digest = hashlib.sha256(data).hexdigest()
        key = f"{tenant_id}/{_safe_name(namespace)}/{digest[:16]}-{_safe_name(filename)}"
        provider = settings.object_store_provider.lower()
        if provider == "filesystem":
            root = Path(settings.object_store_dir).resolve()
            path = (root / key).resolve()
            if root not in path.parents:
                raise ObjectStoreError("invalid object path")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return StoredObject(ref=f"file://{path}", sha256=digest, size=len(data), content_type=content_type)
        if provider == "s3":
            if not settings.object_store_bucket:
                raise ObjectStoreError("S3 object store requires WORKBUDDY_OBJECT_STORE_BUCKET")
            import boto3
            client = boto3.client(
                "s3", region_name=settings.object_store_region or None,
                endpoint_url=settings.object_store_endpoint or None,
            )
            kwargs = {
                "Bucket": settings.object_store_bucket, "Key": key, "Body": data,
                "ContentType": content_type, "Metadata": {"sha256": digest, "tenant-id": tenant_id},
            }
            # Prefer SSE-KMS when a KMS key ARN is configured; fall back to SSE-AES256.
            if settings.object_store_kms_key_arn:
                kwargs["ServerSideEncryption"] = "aws:kms"
                kwargs["SSEKMSKeyId"] = settings.object_store_kms_key_arn
            else:
                kwargs["ServerSideEncryption"] = "AES256"
            client.put_object(**kwargs)
            return StoredObject(ref=f"s3://{settings.object_store_bucket}/{key}", sha256=digest, size=len(data), content_type=content_type)
        if provider == "gcs":
            if not settings.object_store_bucket:
                raise ObjectStoreError("GCS object store requires WORKBUDDY_OBJECT_STORE_BUCKET")
            # GCS supports CMEK via the KMS key name in the request header.
            # This is a thin wrapper; the actual upload uses google-cloud-storage.
            try:
                from google.cloud import storage
            except ImportError as exc:
                raise ObjectStoreError("google-cloud-storage is required for GCS provider") from exc
            client = storage.Client(project=settings.gcp_project_id or None)
            bucket = client.bucket(settings.object_store_bucket)
            blob = bucket.blob(key)
            if settings.object_store_kms_key_arn:
                blob.kms_key_name = settings.object_store_kms_key_arn
            blob.upload_from_string(data, content_type=content_type)
            blob.metadata = {"sha256": digest, "tenant-id": tenant_id}
            blob.patch()
            return StoredObject(ref=f"gs://{settings.object_store_bucket}/{key}", sha256=digest, size=len(data), content_type=content_type)
        raise ObjectStoreError(f"unsupported object store provider: {provider}")


object_store = ObjectStore()
