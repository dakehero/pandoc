#!/usr/bin/env python3
"""Build a Windows-hosted ARM64 GHC using its pinned upstream CI recipe."""

import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    source = Path(sys.argv[1]).resolve()
    jobs_text = "\n".join(
        line for line in (source / ".gitlab/jobs.yaml").read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    jobs = json.loads(jobs_text)
    job = jobs[
        "aarch64-linux-deb12-wine-int_native-cross_aarch64-unknown-mingw32-validate"
    ]
    env = os.environ.copy()
    env.update(job["variables"])
    # Stage 2 is a Linux-hosted cross compiler. Stage 3 produces the
    # Windows-hosted compiler needed to execute Template Haskell natively.
    env.update(
        CROSS_STAGE="3",
        BIN_DIST_NAME="ghc-windows-arm64",
        CI_JOB_NAME="pandoc-windows-arm64-bootstrap",
        CI_PROJECT_DIR=str(source),
        CI_COMMIT_BRANCH="windows-arm64-validation",
    )
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    report = {"ghc_revision": revision, "stage": 3, "completed": []}
    report_path = source / "arm64-bootstrap.json"
    for phase in ("setup", "configure", "build_hadrian"):
        report["current_phase"] = phase
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        subprocess.run(["bash", ".gitlab/ci.sh", phase], cwd=source,
                       env=env, check=True)
        report["completed"].append(phase)
    report["current_phase"] = "complete"
    report_path.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
