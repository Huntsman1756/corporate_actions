"""P12.1/P12.2 — SFTPTransport (docs/p12/p122).

Handoff remoto real sobre Paramiko (SSHv2 pure-Python; extra
opcional ``sftp``). No implementa SSH — envuelve la libreria
probada. El servidor de conformidad es OpenSSH real (lab/CI) o un
servidor Paramiko in-process en tests (mismo wire protocol).

Layout remoto (protocolo de adapter, no estandar):

    <remote_outbox>/
        <delivery_id>.msg.tmp     upload parcial (pre-commit)
        <delivery_id>.msg         bytes finales (rename)
        <delivery_id>.meta.json   CA_ES_SEND_META_V1 — commit marker
    <remote_receipts>/
        <delivery_id>.ack.json | .nak.json
        processed/

Commit remoto: put .tmp -> stat + read-back sha -> rename .msg ->
put+rename .meta (COMMIT). Meta sigue siendo el marcador de commit,
igual que FileSpool.

Host verification OBLIGATORIA: ``known_hosts_path`` (RejectPolicy)
o ``host_key_fingerprint`` (SHA-256 de la host key pineada).
AutoAddPolicy no se usa jamas.

Evidencia: REMOTE_PERSISTED con remote_path/size/read-back sha/
banner del servidor — se persiste en transport_metadata_json.
REMOTE_PERSISTED != GATEWAY_* != SWIFT_*.
"""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import socket
import stat as statmod
from pathlib import Path

from ..ops_send import (
    O_FAILED_PERMANENT, O_FAILED_RETRYABLE, O_SPOOLED,
    SCHEMA_SEND_META, SendAdapterResult, SendRequest,
    V_COLLISION, V_NOT_SPOOLED, V_SPOOLED, V_UNKNOWN,
    content_sha256_of)
from ..semantic_hash import canonical_json

CONFIG_KEYS = frozenset({
    "host", "port", "username", "username_env",
    "private_key_path", "private_key_passphrase_env", "password_env",
    "known_hosts_path", "host_key_fingerprint",
    "remote_outbox", "remote_receipts", "local_receipt_staging",
    "remote_receipt_disposition", "read_back_verify",
    "connect_timeout_seconds", "operation_timeout_seconds"})
REQUIRED_KEYS = frozenset({
    "host", "remote_outbox", "remote_receipts",
    "local_receipt_staging"})


class _MissingParamiko(Exception):
    pass


def _paramiko():
    try:
        import paramiko
        return paramiko
    except ImportError as exc:
        raise _MissingParamiko() from exc


# ------------------------------------------------------------------
# config / connect
# ------------------------------------------------------------------

def _cfg(cfg: dict, key, default=None):
    v = (cfg or {}).get(key)
    return v if v not in (None, "") else default


def _remote(cfg, *parts) -> str:
    return posixpath.join(*(p.strip("/") for p in parts))


def _fingerprint_sha256(key) -> str:
    return hashlib.sha256(key.asbytes()).hexdigest()


def _check_key_permissions(path: str) -> str | None:
    """POSIX: la clave privada no debe ser legible por group/other.
    Windows no expone el modelo -> sin check."""
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return None
    if os.name == "posix" and (mode & (statmod.S_IRWXG | statmod.S_IRWXO)):
        return "INSECURE_KEY_PERMISSIONS"
    return None


def _connect(cfg: dict):
    """Devuelve (paramiko, SSHClient) o lanza la excepcion que
    clasifica _classify_connect_error."""
    pm = _paramiko()
    host = _cfg(cfg, "host")
    port = int(_cfg(cfg, "port", 22))
    username = _cfg(cfg, "username") or os.environ.get(
        str(_cfg(cfg, "username_env", "")), "")
    connect_timeout = float(_cfg(cfg, "connect_timeout_seconds", 15))

    client = pm.SSHClient()
    pinned = _cfg(cfg, "host_key_fingerprint")
    if pinned:
        class _Pinned(pm.MissingHostKeyPolicy):
            def missing_host_key(self, cl, hostname, key):
                if _fingerprint_sha256(key) != pinned:
                    raise pm.SSHException(
                        "HOST_KEY_FINGERPRINT_MISMATCH")
        client.set_missing_host_key_policy(_Pinned())
        client.load_system_host_keys()
    else:
        kh = _cfg(cfg, "known_hosts_path")
        client.load_system_host_keys()
        if kh:
            client.load_host_keys(kh)
        client.set_missing_host_key_policy(pm.RejectPolicy())

    kwargs = {"hostname": host, "port": port, "username": username,
              "timeout": connect_timeout,
              "banner_timeout": connect_timeout,
              "auth_timeout": connect_timeout,
              "look_for_keys": False, "allow_agent": False}
    key_path = _cfg(cfg, "private_key_path")
    if key_path:
        kwargs["key_filename"] = key_path
        pw_env = _cfg(cfg, "private_key_passphrase_env")
        if pw_env:
            kwargs["passphrase"] = os.environ.get(str(pw_env))
    else:
        pw_env = _cfg(cfg, "password_env")
        kwargs["password"] = os.environ.get(str(pw_env), "")

    client.connect(**kwargs)
    return pm, client


def _classify_connect_error(exc) -> str:
    """PERMANENT|RETRYABLE segun la clase de error de conexion."""
    import paramiko as pm  # si falla el import, deliver() ya salio
    if isinstance(exc, pm.AuthenticationException):
        return "PERMANENT"
    if isinstance(exc, pm.ssh_exception.BadHostKeyException):
        return "PERMANENT"
    if isinstance(exc, pm.SSHException) and \
            "HOST_KEY_FINGERPRINT_MISMATCH" in str(exc):
        return "PERMANENT"
    return "RETRYABLE"


def _open_sftp(cfg):
    """connect + open_sftp; fija el timeout de operacion en el
    channel donde la API lo expone."""
    pm, client = _connect(cfg)
    sftp = client.open_sftp()
    op_timeout = _cfg(cfg, "operation_timeout_seconds")
    if op_timeout:
        try:
            sftp.get_channel().settimeout(float(op_timeout))
        except Exception:  # noqa: BLE001 — best-effort
            pass
    return pm, client, sftp


# ------------------------------------------------------------------
# remote helpers
# ------------------------------------------------------------------

def _mkdir_p(sftp, remote: str):
    """mkdir -p remoto; ignora 'ya existe', propaga el resto."""
    parts = [p for p in remote.strip("/").split("/") if p]
    cur = ""
    for part in parts:
        cur += "/" + part
        try:
            sftp.stat(cur)
        except IOError:
            sftp.mkdir(cur)


def _remote_stat(sftp, path: str):
    try:
        return sftp.stat(path)
    except (IOError, OSError):
        return None


def _read_remote_sha(sftp, path: str) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with sftp.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _put_atomic(sftp, data: bytes, final: str):
    """put a tmp -> rename al nombre final (mismo fs remoto)."""
    tmp = final + ".tmp"
    with sftp.open(tmp, "wb") as f:
        f.write(data)
        try:
            f.flush()
        except Exception:  # noqa: BLE001
            pass
    try:
        sftp.posix_rename(tmp, final)
    except IOError:
        # servidor sin posix-rename: rename estandar (OpenSSH
        # sobreescribe atomicamente dentro del mismo fs)
        try:
            sftp.remove(final)
        except IOError:
            pass
        sftp.rename(tmp, final)


def _meta_doc(request: SendRequest) -> dict:
    return {
        "schema": SCHEMA_SEND_META,
        "delivery_id": request.delivery_id,
        "instruction_id": request.instruction_id,
        "message_reference": request.message_reference,
        "message_schema": request.message_schema,
        "content_sha256": request.content_sha256,
        "destination_id": request.destination_id,
        "adapter_type": request.adapter_type,
        "generation": request.generation}


def _evidence(cfg, request: SendRequest, remote_msg: str,
              size: int, read_sha: str | None, sftp) -> dict:
    try:
        banner = sftp.get_channel().get_transport()\
            .remote_version
    except Exception:  # noqa: BLE001
        banner = None
    return {
        "transport_evidence": "REMOTE_PERSISTED",
        "remote_path": remote_msg,
        "remote_size": size,
        "read_back_sha256": read_sha,
        "read_back_verify": bool(_cfg(cfg, "read_back_verify", True)),
        "server": banner}


# ------------------------------------------------------------------
# inspect remoto (compartido por deliver/verify)
# ------------------------------------------------------------------

def _inspect_remote(sftp, request: SendRequest, cfg) -> str:
    """Estado remoto comprometido para este delivery.

    COMMITTED   meta+msg presentes, meta.sha casa, msg verificado
    ORPHAN_MSG  .msg presente con sha del ledger, sin meta
    COLLISION   evidencia remota con sha distinto
    ABSENT      nada comprometido (reintento seguro)
    """
    outbox = _cfg(cfg, "remote_outbox")
    msg = _remote(cfg, outbox, f"{request.delivery_id}.msg")
    meta = _remote(cfg, outbox, f"{request.delivery_id}.meta.json")

    meta_st = _remote_stat(sftp, meta)
    if meta_st is not None:
        try:
            with sftp.open(meta, "rb") as f:
                meta_doc = json.loads(f.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return "COLLISION"  # meta corrupto: no se puede probar
        if meta_doc.get("content_sha256") != request.content_sha256:
            return "COLLISION"
        if _remote_stat(sftp, msg) is None:
            return "COLLISION"
        if _cfg(cfg, "read_back_verify", True):
            sha, _ = _read_remote_sha(sftp, msg)
            return "COMMITTED" if sha == request.content_sha256 \
                else "COLLISION"
        st = _remote_stat(sftp, msg)
        expected = len(request.message_text.encode("utf-8"))
        return "COMMITTED" if st and st.st_size == expected \
            else "COLLISION"

    if _remote_stat(sftp, msg) is not None:
        if _cfg(cfg, "read_back_verify", True):
            sha, _ = _read_remote_sha(sftp, msg)
            return "ORPHAN_MSG" if sha == request.content_sha256 \
                else "COLLISION"
        st = _remote_stat(sftp, msg)
        expected = len(request.message_text.encode("utf-8"))
        return "ORPHAN_MSG" if st and st.st_size == expected \
            else "COLLISION"
    # tmp huerfano de un intento cortado: se pisa en el retry
    tmp = msg + ".tmp"
    if _remote_stat(sftp, tmp) is not None:
        try:
            sftp.remove(tmp)
        except IOError:
            pass
    return "ABSENT"


# ------------------------------------------------------------------
# adapter contract
# ------------------------------------------------------------------

def deliver(request: SendRequest, dest_config: dict) \
        -> SendAdapterResult:
    """Handoff remoto transaccional. Clasificacion por fase:

    connect/auth  -> retryable (auth permanente)
    tmp upload    -> retryable (nada comprometido)
    post .msg     -> UNKNOWN (verify() resuelve)
    """
    actual_sha = content_sha256_of(request.message_text)
    if actual_sha != request.content_sha256:
        return SendAdapterResult(
            O_FAILED_PERMANENT, error_code="CONTENT_HASH_MISMATCH",
            error_detail_safe="message_text no casa con "
                              "content_sha256 del ledger")
    cfg = dest_config or {}
    key_path = _cfg(cfg, "private_key_path")
    if key_path:
        perm_err = _check_key_permissions(key_path)
        if perm_err:
            return SendAdapterResult(
                O_FAILED_PERMANENT, error_code=perm_err)

    try:
        pm, client, sftp = _open_sftp(cfg)
    except _MissingParamiko:
        return SendAdapterResult(
            O_FAILED_PERMANENT, error_code="PARAMIKO_UNAVAILABLE",
            error_detail_safe="pip install ca-es[sftp]")
    except Exception as exc:  # noqa: BLE001
        cls = _classify_connect_error(exc)
        return SendAdapterResult(
            O_FAILED_PERMANENT if cls == "PERMANENT"
            else O_FAILED_RETRYABLE,
            error_code=("AUTH_FAILED" if cls == "PERMANENT"
                        else "CONNECT_FAILED"),
            error_detail_safe=exc.__class__.__name__)

    outbox = _cfg(cfg, "remote_outbox")
    msg = _remote(cfg, outbox, f"{request.delivery_id}.msg")
    meta = _remote(cfg, outbox, f"{request.delivery_id}.meta.json")
    body = request.message_text.encode("utf-8")

    try:
        _mkdir_p(sftp, outbox)
        _mkdir_p(sftp, _cfg(cfg, "remote_receipts"))
    except Exception as exc:  # noqa: BLE001
        client.close()
        return SendAdapterResult(
            O_FAILED_RETRYABLE, error_code="REMOTE_MKDIR_FAILED",
            error_detail_safe=exc.__class__.__name__)

    # ---- idempotencia / collision ---------------------------------
    try:
        remote_state = _inspect_remote(sftp, request, cfg)
    except Exception as exc:  # noqa: BLE001
        client.close()
        return SendAdapterResult(
            O_FAILED_RETRYABLE, error_code="REMOTE_STAT_FAILED",
            error_detail_safe=exc.__class__.__name__)

    if remote_state == "COLLISION":
        client.close()
        return SendAdapterResult(
            O_FAILED_PERMANENT, error_code="DELIVERY_ID_COLLISION",
            error_detail_safe="evidencia remota con sha distinto")
    if remote_state == "COMMITTED":
        sha = None
        size = _remote_stat(sftp, msg)
        if _cfg(cfg, "read_back_verify", True):
            try:
                sha, _ = _read_remote_sha(sftp, msg)
            except IOError:
                sha = None
        client.close()
        return SendAdapterResult(
            O_SPOOLED, receipt={
                "replayed": True,
                **_evidence(cfg, request, msg,
                            size.st_size if size else 0, sha, sftp)})
    if remote_state == "ORPHAN_MSG":
        # msg comprometido, meta ausente: completar el commit
        try:
            _put_atomic(sftp, canonical_json(
                _meta_doc(request)).encode("utf-8"), meta)
        except Exception as exc:  # noqa: BLE001
            client.close()
            return SendAdapterResult(
                "UNKNOWN", error_code="SFTP_IO_POST_MSG",
                error_detail_safe=exc.__class__.__name__)
        st = _remote_stat(sftp, msg)
        client.close()
        return SendAdapterResult(
            O_SPOOLED, receipt={
                "replayed": False, "completed_orphan": True,
                **_evidence(cfg, request, msg,
                            st.st_size if st else 0, None, sftp)})

    # ---- escritura transaccional ----------------------------------
    try:
        _put_atomic(sftp, body, msg)
    except Exception as exc:  # noqa: BLE001
        client.close()
        return SendAdapterResult(
            O_FAILED_RETRYABLE, error_code="SFTP_UPLOAD_FAILED",
            error_detail_safe=exc.__class__.__name__)

    # verificacion post-rename del .msg
    if _cfg(cfg, "read_back_verify", True):
        try:
            sha, _ = _read_remote_sha(sftp, msg)
        except Exception as exc:  # noqa: BLE001
            client.close()
            return SendAdapterResult(
                "UNKNOWN", error_code="SFTP_IO_POST_MSG",
                error_detail_safe=exc.__class__.__name__)
        if sha != request.content_sha256:
            client.close()
            return SendAdapterResult(
                O_FAILED_PERMANENT, error_code="REMOTE_HASH_MISMATCH",
                error_detail_safe="read-back remoto no casa")
    else:
        st = _remote_stat(sftp, msg)
        if st is None or st.st_size != len(body):
            client.close()
            return SendAdapterResult(
                O_FAILED_PERMANENT, error_code="REMOTE_SIZE_MISMATCH")

    # punto de no retorno parcial: .msg renombrado, meta aun no
    try:
        _put_atomic(sftp, canonical_json(
            _meta_doc(request)).encode("utf-8"), meta)
    except Exception as exc:  # noqa: BLE001
        client.close()
        return SendAdapterResult(
            "UNKNOWN", error_code="SFTP_IO_POST_MSG",
            error_detail_safe=exc.__class__.__name__)

    st = _remote_stat(sftp, msg)
    read_sha = request.content_sha256 if _cfg(
        cfg, "read_back_verify", True) else None
    client.close()
    return SendAdapterResult(
        O_SPOOLED, receipt={
            "replayed": False,
            **_evidence(cfg, request, msg,
                        st.st_size if st else 0, read_sha, sftp)})


def verify(request: SendRequest, dest_config: dict) -> str:
    """Verificacion post-crash remota. Un fallo de conexion es
    UNKNOWN — nunca NOT_SPOOLED (podria ya estar comprometido)."""
    cfg = dest_config or {}
    try:
        _pm, client, sftp = _open_sftp(cfg)
    except Exception:  # noqa: BLE001
        return V_UNKNOWN
    try:
        remote = _inspect_remote(sftp, request, cfg)
    except Exception:  # noqa: BLE001
        client.close()
        return V_UNKNOWN
    client.close()
    return {"COMMITTED": V_SPOOLED, "ORPHAN_MSG": V_NOT_SPOOLED,
            "ABSENT": V_NOT_SPOOLED, "COLLISION": V_COLLISION
            }[remote]


# ------------------------------------------------------------------
# receipt polling (P12.2)
# ------------------------------------------------------------------

def poll_receipts(dest_config: dict) -> list[dict]:
    """Descarga receipts remotos a local_receipt_staging/receipts.

    Devuelve [{remote_name, local_path, delivery_id}]. El core
    valida cada fichero local con el contrato P11. Un fallo de red
    propaga como excepcion — el poller lo registra como fallo
    tecnico, nunca rechazo de negocio.
    """
    cfg = dest_config or {}
    _pm, client, sftp = _open_sftp(cfg)
    remote_dir = _cfg(cfg, "remote_receipts")
    staging = Path(_cfg(cfg, "local_receipt_staging"))
    local_dir = staging / "receipts"
    local_dir.mkdir(parents=True, exist_ok=True)

    out = []
    try:
        names = sftp.listdir(remote_dir)
    except IOError:
        client.close()
        return out
    for name in sorted(names):
        if not (name.endswith(".ack.json")
                or name.endswith(".nak.json")):
            continue
        did = name.rsplit(".", 2)[0]
        if not did.startswith("SND-"):
            continue
        remote_path = _remote(cfg, remote_dir, name)
        local_path = local_dir / name
        try:
            data = b""
            with sftp.open(remote_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    data += chunk
        except (IOError, OSError):
            continue  # receipt desaparecio/ilegible: siguiente poll
        _write_local_atomic(local_path, data)
        out.append({"remote_name": name, "local_path": local_path,
                    "delivery_id": did})
    client.close()
    return out


def archive_remote_receipt(dest_config: dict, remote_name: str):
    """Mueve el receipt remoto a processed/ tras una ingestion
    valida (disposition=archive). Fallos remotos se tragan — la
    evidencia local ya esta en el ledger."""
    cfg = dest_config or {}
    if _cfg(cfg, "remote_receipt_disposition", "archive") != "archive":
        return
    try:
        _pm, client, sftp = _open_sftp(cfg)
        remote_dir = _cfg(cfg, "remote_receipts")
        processed = _remote(cfg, remote_dir, "processed")
        _mkdir_p(sftp, processed)
        src = _remote(cfg, remote_dir, remote_name)
        dst = _remote(cfg, processed, remote_name)
        try:
            sftp.posix_rename(src, dst)
        except IOError:
            try:
                sftp.remove(dst)
            except IOError:
                pass
            sftp.rename(src, dst)
        client.close()
    except Exception:  # noqa: BLE001 — archive es best-effort
        return


def _write_local_atomic(path: Path, data: bytes):
    import tempfile
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
