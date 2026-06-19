#!/usr/bin/env python3
"""External worker for persistent Web Agent jobs."""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web.job_manager import JobManager  # noqa: E402


JOB_ROOT = REPO_ROOT / "logs" / "web" / "jobs"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--worker-id",
        default=f"{socket.gethostname()}-{os.getpid()}",
    )
    args = parser.parse_args()
    manager = JobManager(REPO_ROOT, JOB_ROOT, execution_mode="external")

    while True:
        job = manager.claim_next(args.worker_id)
        if job:
            manager.run_claimed(job)
            if args.once:
                return 0
            continue
        if args.once:
            return 0
        time.sleep(max(0.1, args.poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
