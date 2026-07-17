#!/usr/bin/env python3
"""Command-line entry point for k8sagent workflows."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.log_analysis_orchestrator import run_log_analysis_agent  # noqa: E402
from agent.requirement_orchestrator import run_requirement_agent  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the k8sagent planning and validation workflow."
    )
    parser.add_argument(
        "--requirement",
        help="Natural language requirement file.",
    )
    parser.add_argument(
        "--log-dir",
        help=(
            "Existing logs/scaffold, logs/patch, or "
            "logs/kind-deployment directory to analyze."
        ),
    )
    parser.add_argument("--analyze-log", help="Alias of --log-dir.")
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
        choices=["fast", "standard"],
        help=(
            "Execution depth. fast skips final LLM evaluation; standard adds "
            "it. Compile and kind matrices are run through the regression "
            "script's full suite."
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
        "--artifact-dir",
        default="generated",
        help="Directory for generated specs, proposals, and command plans.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Allow real execution for mutating tools.",
    )
    parser.add_argument(
        "--capability-proposal",
        help="Reviewed capability proposal path for this execution.",
    )
    parser.add_argument(
        "--capability-approval",
        help="Reviewed proposalId required to approve that exact proposal.",
    )
    parser.add_argument(
        "--resume-existing",
        action="store_true",
        help=(
            "Skip scaffold creation for an existing target project and "
            "continue artifact patching and make validation."
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    # CLI는 두 가지 진입점을 하나로 묶는다.
    # 1) requirement 기반 Operator 생성/검증
    # 2) 기존 실행 로그 분석
    # 실제 orchestration은 전용 모듈로 위임해 진입점이 커지지 않도록 한다.
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
