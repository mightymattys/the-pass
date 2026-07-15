from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import yaml

from the_pass.orchestration import (
    advance_workflow_state,
    read_workflow_state,
    write_workflow_state_atomic,
)


state_path = Path(os.environ["THE_PASS_WORKFLOW_STATE"])
mode = sys.argv[1]
state = read_workflow_state(state_path)

if mode == "no-progress":
    raise SystemExit(0)
if mode == "sleep":
    state_path.write_text("stage:", encoding="utf-8")
    time.sleep(10)
    raise SystemExit(0)
if mode == "malformed":
    state_path.write_text("{", encoding="utf-8")
    raise SystemExit(0)
if mode == "output-flood":
    sys.stdout.write("x" * 100_000)
    raise SystemExit(0)
if mode in {"skip", "jump"}:
    document = dict(state)
    document["updated_at"] = "2026-07-11T00:00:01Z"
    if mode == "skip":
        document["stage"] = "complete"
        document["status"] = "complete"
        document["transitions_used"] += 1
    else:
        document["transitions_used"] += 2
    state_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    raise SystemExit(0)

if mode == "two-cycle-kill":
    if state["stage"] == "preflight":
        updated = advance_workflow_state(
            state,
            to_stage="research",
            status="in_progress",
            next_action="run bounded research",
            timestamp="2026-07-11T00:00:01Z",
        )
    else:
        updated = advance_workflow_state(
            state,
            to_stage=None,
            status="killed",
            next_action="archive falsified hypothesis",
            blockers=["fixture kill condition reached"],
            timestamp="2026-07-11T00:00:02Z",
        )
    write_workflow_state_atomic(state_path, updated)
    raise SystemExit(0)

if mode in {"blocked", "waiting"}:
    updated = advance_workflow_state(
        state,
        to_stage=None,
        status=mode,
        next_action="resolve fixture condition",
        blockers=[f"fixture {mode} condition"],
        timestamp="2026-07-11T00:00:01Z",
    )
    write_workflow_state_atomic(state_path, updated)
    raise SystemExit(2)

raise SystemExit(f"unknown fake driver mode: {mode}")
