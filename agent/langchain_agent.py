#!/usr/bin/env python3
"""Command-line entry point for the Kubebuilder Agent orchestrators."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.log_analysis_orchestrator import run_log_analysis_agent  # noqa: E402
from agent.recovery_policy import (  # noqa: E402,F401
    deterministic_recovery_classification,
    validate_recovery_plan,
)
from agent.requirement_orchestrator import run_requirement_agent  # noqa: E402
from agent.tool_validator import (  # noqa: E402,F401
    validate_llm_output_schema,
    validate_planned_tool_calls,
)
from agent.tools import langchain_wrappers as tools  # noqa: E402,F401


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the LLM-based Kubebuilder Agent orchestrator."
    )
    parser.add_argument(
        "--requirement",
        help="Natural language requirement file.",
    )
    parser.add_argument(
        "--log-dir",
        help="Existing logs/scaffold, logs/patch, or logs/e2e directory to analyze.",
    )
    parser.add_argument("--analyze-log", help="Alias of --log-dir.")
    parser.add_argument("--profile", help="Profile YAML path.")
    parser.add_argument(
        "--planner",
        default="llm",
        choices=["llm"],
        help="Only the LLM planner is supported.",
    )
    parser.add_argument(
        "--mode",
        default="dry-run",
        choices=["dry-run", "execute"],
        help="Agent mode. Defaults to dry-run.",
    )
    parser.add_argument(
        "--run-level",
        default="fast",
        choices=["fast", "standard", "full"],
        help=(
            "Execution depth. fast skips final LLM evaluation; standard adds "
            "it; full is reserved for heavier checks."
        ),
    )
    parser.add_argument(
        "--skip-final-llm-evaluation",
        action="store_true",
        help=(
            "Skip the second LLM call and use a deterministic execution "
            "summary."
        ),
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable local Agent LLM planning cache for this run.",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Ignore existing cache and replace it with a fresh LLM plan.",
    )
    parser.add_argument(
        "--workspace",
        default="workspace/generated-operators",
        help="Scaffold workspace parent.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Allow real execution for mutating tools.",
    )
    parser.add_argument(
        "--kind-deploy",
        action="store_true",
        help="Include profile-backed kind deployment after validation.",
    )
    parser.add_argument(
        "--resume-existing",
        action="store_true",
        help=(
            "Skip scaffold creation for an existing target project and "
            "continue patch, validation, and deployment."
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.analyze_log and not args.log_dir:
        args.log_dir = args.analyze_log
    if args.log_dir:
        return run_log_analysis_agent(args)
    if not args.requirement:
        raise SystemExit(
            "--requirement is required unless --log-dir or --analyze-log "
            "is provided."
        )
    return run_requirement_agent(args)


if __name__ == "__main__":
    raise SystemExit(main())
