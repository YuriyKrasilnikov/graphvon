"""Adapt the supported native patch event to Graphvon's scoped checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Sequence

from .contracts import Refusal, parse_json
from .installation import resolve_installation
from .patches import inspect_patch
from .sources import (
    check_checkout,
    check_source_basis,
    observe_basis,
)


READ_BUDGET_SECONDS = 6.0
SESSION_SOURCES = frozenset({"startup", "resume", "clear", "compact", "fork"})

_REFUSAL_REASONS = {
    "event": "Graphvon requires a supported native PreToolUse apply_patch event.",
    "context": "Graphvon requires a valid scoped context via exact-checkout registration or an explicit GRAPHVON_CONTEXT override.",
    "checkout": "Graphvon could not confirm the admitted checkout boundary.",
    "patch": "The patch is unsupported or exceeds the admitted operations and paths.",
    "sources": "Graphvon could not confirm the current admission basis; reassess the assignment.",
}


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _within_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError


def _event_fields(event: Any) -> tuple[Path, str]:
    if not isinstance(event, dict):
        raise Refusal("Expected event object.")
    if event.get("hook_event_name") != "PreToolUse":
        raise Refusal("Unsupported event.")
    if event.get("tool_name") != "apply_patch":
        raise Refusal("Unsupported tool.")
    cwd = event.get("cwd")
    tool_input = event.get("tool_input")
    if not isinstance(cwd, str) or not cwd or not Path(cwd).is_absolute():
        raise Refusal("Expected absolute working directory.")
    if not isinstance(tool_input, dict):
        raise Refusal("Expected native tool input.")
    command = tool_input.get("command")
    if not isinstance(command, str) or not command:
        raise Refusal("Expected patch command.")
    return Path(cwd), command


def _check_hook() -> dict[str, Any]:
    deadline = time.monotonic() + READ_BUDGET_SECONDS
    phase = "event"
    try:
        event = parse_json(sys.stdin.read())
        cwd, command = _event_fields(event)
        _within_deadline(deadline)

        phase = "context"
        context = resolve_installation(cwd, deadline).context
        _within_deadline(deadline)

        phase = "checkout"
        check_checkout(context, cwd, deadline)
        _within_deadline(deadline)

        phase = "patch"
        inspect_patch(command, cwd, context.root, context.grants)
        _within_deadline(deadline)

        phase = "sources"
        check_source_basis(context, deadline)
        _within_deadline(deadline)
        return {}
    except TimeoutError:
        return _deny("Graphvon's internal deadline expired; the assignment was not validated.")
    except (Refusal, ValueError, TypeError, OSError):
        # Exception text can contain a private locator or source payload.
        return _deny(_REFUSAL_REASONS[phase])
    except Exception:
        # An unexpected adapter failure is unavailable control, never approval.
        return _deny("Graphvon could not complete its checks; treat the control as unavailable.")


def _session_start() -> dict[str, Any]:
    deadline = time.monotonic() + READ_BUDGET_SECONDS
    try:
        event = parse_json(sys.stdin.read())
        if not isinstance(event, dict) or event.get("hook_event_name") != "SessionStart":
            raise Refusal("Expected a native SessionStart event.")
        if not isinstance(event.get("source"), str) or event["source"] not in SESSION_SOURCES:
            raise Refusal("Unsupported session source.")
        cwd = event.get("cwd")
        if not isinstance(cwd, str) or not cwd or not Path(cwd).is_absolute():
            raise Refusal("Expected an absolute working directory.")
        installation = resolve_installation(Path(cwd), deadline)
        _within_deadline(deadline)
        references = {
            "checkout": str(installation.context.root),
            "context": str(installation.context_path),
            "working_record": (str(installation.working_record)
                               if installation.working_record is not None else None),
            "skill": str(installation.skill_path),
        }
        message = (
            "Graphvon private continuation references (local session only; do not publish): "
            + json.dumps(references, ensure_ascii=True)
            + "\nUse $graphvon-start-work. Reconcile the current assignment, prior tool results "
            "and actual checkout effects before continuing writes. Read current working state "
            "only as needed; these references grant no new authority or generation. "
            "An explicit override supplies no registered working-record reference."
        )
    except Exception:
        # No exception text or partially resolved locator enters session output.
        message = (
            "Graphvon continuation state is unavailable. Confirm the exact checkout's private "
            "registration or explicit GRAPHVON_CONTEXT override. Read-only investigation may "
            "continue; covered writes require a valid reconciled assignment and the pre-tool "
            "checks. This startup message grants no authority."
        )
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": message}}


def _positive_number(value: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a positive integer") from error
    if result < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graphvon-preflight",
        description="Check a native patch event, restore session references, or read a public source basis.",
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("session-start", help="offer private continuation references without granting authority")
    snapshot = commands.add_parser(
        "snapshot", help="read public sources without granting implementation authority"
    )
    snapshot.add_argument("--repository", required=True, help="GitHub owner/name")
    snapshot.add_argument("--issue", required=True, type=_positive_number)
    snapshot.add_argument("--pull", required=True, type=_positive_number)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "session-start":
        json.dump(_session_start(), sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    if arguments.command == "snapshot":
        deadline = time.monotonic() + READ_BUDGET_SECONDS
        try:
            basis = observe_basis(
                arguments.repository, arguments.issue, arguments.pull, deadline
            )
            _within_deadline(deadline)
        except Exception:
            print(
                "Graphvon could not obtain a complete current source basis.",
                file=sys.stderr,
            )
            return 1
        json.dump(basis, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    json.dump(_check_hook(), sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
