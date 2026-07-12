"""Supervisor for the isolated virtual paper worker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from the_pass.data.contracts import CanonicalEvent, canonical_value, stable_fingerprint


PAPER_ENV_ALLOWLIST = {"LANG", "LC_ALL", "PATH", "PYTHONPATH", "TMPDIR"}


@dataclass(frozen=True)
class ObservationPolicy:
    max_staleness_ns: int
    max_clock_skew_ns: int
    max_outage_gap_ns: int

    def __post_init__(self) -> None:
        if min(self.max_staleness_ns, self.max_clock_skew_ns, self.max_outage_gap_ns) <= 0:
            raise ValueError("paper observation limits must be positive")


def validate_observation(
    events: Iterable[CanonicalEvent],
    *,
    observation_time_ns: int,
    policy: ObservationPolicy,
) -> list[dict[str, Any]]:
    rows = sorted(events, key=CanonicalEvent.sort_key)
    if not rows:
        return [{"code": "no_data", "severity": "critical", "blocks_runtime": True}]
    breaches = []
    future_rows = [index for index, event in enumerate(rows) if event.receive_time_ns > observation_time_ns]
    if future_rows:
        breaches.append(
            {
                "code": "future_data",
                "severity": "critical",
                "blocks_runtime": True,
                "event_indexes": future_rows,
            }
        )
    if observation_time_ns - rows[-1].receive_time_ns > policy.max_staleness_ns:
        breaches.append({"code": "stale_data", "severity": "critical", "blocks_runtime": True})
    for index, event in enumerate(rows):
        if abs(event.receive_time_ns - event.event_time_ns) > policy.max_clock_skew_ns:
            breaches.append(
                {"code": "clock_skew", "severity": "critical", "blocks_runtime": True, "event_index": index}
            )
    streams: dict[tuple[str, str, str, str], list[CanonicalEvent]] = {}
    for event in rows:
        key = (event.source, event.venue, event.instrument_id, event.event_type.value)
        streams.setdefault(key, []).append(event)
    for stream, stream_rows in sorted(streams.items()):
        for index, (previous, current) in enumerate(zip(stream_rows, stream_rows[1:]), start=1):
            if current.receive_time_ns - previous.receive_time_ns > policy.max_outage_gap_ns:
                breaches.append(
                    {
                        "code": "outage_gap",
                        "severity": "critical",
                        "blocks_runtime": True,
                        "stream": ":".join(stream),
                        "event_index": index,
                    }
                )
    return breaches


def run_virtual_paper_process(
    *,
    strategy_name: str,
    events: Iterable[CanonicalEvent],
    risk_policy: dict[str, Any],
    observation_policy: ObservationPolicy,
    observation_time_ns: int,
    output_path: Path,
) -> dict[str, Any]:
    rows = sorted(events, key=CanonicalEvent.sort_key)
    breaches = validate_observation(rows, observation_time_ns=observation_time_ns, policy=observation_policy)
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    config_hash = stable_fingerprint(
        {
            "strategy_name": strategy_name,
            "risk_policy_hash": risk_policy["policy_hash"],
            "observation_policy": observation_policy.__dict__,
        }
    )
    if breaches:
        result = {
            "schema_version": 1,
            "status": "frozen",
            "strategy_name": strategy_name,
            "config_hash": config_hash,
            "process_isolated": True,
            "breaches": breaches,
            "decision_journal": [],
            "simulated_intents": [],
            "fills": [],
            "missed_fills": [],
            "risk_events": breaches,
        }
        output_path.write_text(
            json.dumps(canonical_value(result), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        events_path = root / "events.jsonl"
        risk_path = root / "risk_policy.json"
        worker_output = root / "paper_result.json"
        events_path.write_text(
            "\n".join(json.dumps(event.as_dict(), sort_keys=True) for event in rows) + "\n",
            encoding="utf-8",
        )
        risk_path.write_text(json.dumps(risk_policy, sort_keys=True), encoding="utf-8")
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "the_pass.paper.worker",
                "--strategy",
                strategy_name,
                "--events",
                str(events_path),
                "--risk-policy",
                str(risk_path),
                "--config-hash",
                config_hash,
                "--output",
                str(worker_output),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env={name: value for name, value in os.environ.items() if name in PAPER_ENV_ALLOWLIST},
        )
        if process.returncode != 0 or not worker_output.is_file():
            raise RuntimeError(f"virtual paper worker failed: {process.stderr.strip()}")
        result = json.loads(worker_output.read_text(encoding="utf-8"))
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
