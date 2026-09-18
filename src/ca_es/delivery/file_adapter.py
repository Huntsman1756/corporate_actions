"""P10.4 — FILE delivery adapter (referencia determinista).

``<directory>/<delivery_key>.json`` atomic write: tmp -> fsync ->
os.replace. Idempotente: fichero existente con bytes identicos =
entregado; con bytes distintos = DELIVERY_KEY_COLLISION (permanente,
nunca sobrescribe).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ..ops_delivery import (
    AdapterResult, O_FAILED_PERMANENT, O_SUCCEEDED)
from ..semantic_hash import byte_sha256

CONFIG_KEYS = {"directory"}


def deliver(request, dest_config: dict) -> AdapterResult:
    directory = dest_config.get("directory")
    if not directory:
        return AdapterResult(
            O_FAILED_PERMANENT, error_code="DESTINATION_NO_DIRECTORY",
            error_detail_safe="file destination without directory")
    try:
        target_dir = Path(directory)
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return AdapterResult(
            O_FAILED_PERMANENT, error_code="DIRECTORY_UNUSABLE",
            error_detail_safe=f"{exc.__class__.__name__}"[:200])

    target = target_dir / f"{request.delivery_key}.json"
    data = request.payload_bytes
    try:
        if target.is_file():
            existing = target.read_bytes()
            if existing == data:
                return AdapterResult(
                    O_SUCCEEDED,
                    receipt={
                        "path": str(target),
                        "sha256": byte_sha256(data),
                        "idempotent_replay": True})
            return AdapterResult(
                O_FAILED_PERMANENT, error_code="DELIVERY_KEY_COLLISION",
                error_detail_safe=(
                    "same delivery_key, different bytes"))
        fd, tmp = tempfile.mkstemp(
            dir=target_dir, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as exc:
        return AdapterResult(
            O_FAILED_PERMANENT, error_code="FILE_WRITE_FAILED",
            error_detail_safe=f"{exc.__class__.__name__}"[:200])
    return AdapterResult(
        O_SUCCEEDED,
        receipt={"path": str(target), "sha256": byte_sha256(data)})
