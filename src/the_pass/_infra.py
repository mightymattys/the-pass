"""Shared low-level infrastructure with explicitly preserved semantics."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml


def utc_now_iso_precise() -> str:
    """UTC timestamp retaining the clock's microsecond precision."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_now_iso_seconds() -> str:
    """UTC timestamp truncated to whole seconds."""

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def json_fingerprint(value: Any) -> str:
    return sha256_text(canonical_json(value))


def write_json_atomic(path: Path, document: object) -> None:
    atomic_write_document(path, document, json_only=True)


def atomic_write_document(
    path: Path, document: object, *, json_only: bool = False
) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            if json_only or path.suffix.lower() == ".json":
                json.dump(document, handle, indent=2, sort_keys=True)
                handle.write("\n")
            else:
                yaml.safe_dump(document, handle, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


@contextmanager
def exclusive_dispatch_lock(
    scope: str | Path | None, error_type: type[Exception]
) -> Iterator[None]:
    """Preserve the secure per-workspace external-dispatch lock semantics."""

    if os.name == "posix":
        import pwd

        account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    else:
        account_home = Path.home()
    lock_dir = account_home
    for component in (".cache", "the-pass", "locks"):
        lock_dir = lock_dir / component
        if lock_dir.is_symlink():
            raise error_type("agent dispatch lock directory cannot use symlinks")
        lock_dir.mkdir(mode=0o700, exist_ok=True)
        metadata = lock_dir.stat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise error_type("agent dispatch lock path must be a directory")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise error_type("agent dispatch lock directory has an unexpected owner")
    if hasattr(os, "chmod"):
        os.chmod(lock_dir, 0o700)
    scope_value = "global" if scope is None else str(Path(scope).expanduser().resolve())
    scope_id = hashlib.sha256(scope_value.encode("utf-8")).hexdigest()[:24]
    path = lock_dir / f"external-dispatch-{scope_id}.lock"
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise error_type("cannot securely open the agent dispatch lock") from exc
    acquired = False
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise error_type("agent dispatch lock must be a regular file")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise error_type("agent dispatch lock has an unexpected owner")
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        if os.name == "nt":
            import msvcrt

            if metadata.st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise error_type(
                    "another external agent dispatch is active; nested or concurrent dispatch is forbidden"
                ) from exc
        else:
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise error_type(
                    "another external agent dispatch is active; nested or concurrent dispatch is forbidden"
                ) from exc
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def exclusive_workflow_lock(
    state_path: Path, error_type: type[Exception]
) -> Iterator[None]:
    """Preserve the canonical workflow-state lock semantics."""

    state_path = state_path.resolve()
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    acquired = False
    try:
        metadata = os.fstat(descriptor)
        if not lock_path.is_file() or lock_path.is_symlink():
            raise error_type("workflow lock must be a regular file")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise error_type("workflow lock has an unexpected owner")
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        if os.name == "nt":
            import msvcrt

            if metadata.st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise error_type("another supervisor is active for this workflow state") from exc
        else:
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise error_type("another supervisor is active for this workflow state") from exc
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def terminate_process_safely(process: subprocess.Popen[Any]) -> None:
    """Agent-orchestration termination semantics, including guarded kill."""

    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except OSError:
            pass
        process.wait()


def terminate_process_strict(process: subprocess.Popen[Any]) -> None:
    """Workflow-supervisor termination semantics."""

    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait()


def terminate_remaining_process_group(process: subprocess.Popen[Any]) -> None:
    if os.name == "nt":
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
