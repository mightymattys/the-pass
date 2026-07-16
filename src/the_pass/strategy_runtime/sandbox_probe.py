"""Active capability probe executed through an operator-supplied sandbox launcher."""

from __future__ import annotations

import json
import resource
import socket
import sys
from pathlib import Path


def _attempt_read(path: Path) -> bool:
    try:
        path.read_bytes()
    except OSError:
        return False
    return True


def _attempt_write(path: Path) -> bool:
    try:
        path.write_text("sandbox escape\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _attempt_network(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _resource_limits_enforced() -> bool:
    finite_limits = []
    for limit in (resource.RLIMIT_CPU, resource.RLIMIT_FSIZE):
        soft, hard = resource.getrlimit(limit)
        finite_limits.append(
            soft not in (resource.RLIM_INFINITY, -1)
            and hard not in (resource.RLIM_INFINITY, -1)
        )
    return all(finite_limits)


def main(argv: list[str] | None = None) -> int:
    values = argv or sys.argv[1:]
    if len(values) != 5:
        return 2
    output, forbidden_read, forbidden_write, host, port = values
    document = {
        "schema_version": 1,
        "forbidden_read_succeeded": _attempt_read(Path(forbidden_read)),
        "forbidden_write_succeeded": _attempt_write(Path(forbidden_write)),
        "network_connect_succeeded": _attempt_network(host, int(port)),
        "resource_limits_enforced": _resource_limits_enforced(),
    }
    Path(output).write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
