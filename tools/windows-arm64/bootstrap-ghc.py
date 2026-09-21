#!/usr/bin/env python3
"""Probe a Windows-hosted ARM64 GHC using the pinned upstream CI toolchain.

The upstream binary-dist-stage3 rule currently has no directory rule. Build
the target executables directly so that failure cannot mask compiler errors.
The resulting stage directory is diagnostic output, not a release bindist.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile


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
    # Hadrian's Stage2 directory holds target executables when crossing.
    # The CI interface calls the corresponding native bindist CROSS_STAGE=3.
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
    report = {"ghc_revision": revision, "stage": 3, "completed": [],
              "artifact_kind": "uninstalled target-stage probe"}
    report_path = source / "arm64-bootstrap.json"
    ci = source / ".gitlab/ci.sh"
    original = ci.read_text()
    marker = '  build_hadrian) time_it "build" build_hadrian ;;'
    if original.count(marker) != 1:
        raise RuntimeError("Pinned GHC CI dispatcher changed")
    ci.write_text(original.replace(marker, marker + '\n'
        '  pandoc_target_probe) run_hadrian _build/stage2/bin/ghc.exe '
        '_build/stage2/bin/ghc-pkg.exe ;;'))
    for phase in ("setup", "configure", "pandoc_target_probe"):
        report["current_phase"] = phase
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        result = subprocess.run(["bash", ".gitlab/ci.sh", phase], cwd=source,
                                env=env)
        if result.returncode:
            report["exit_code"] = result.returncode
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            raise SystemExit(result.returncode)
        report["completed"].append(phase)
    with tarfile.open(source / "ghc-target-stage-probe.tar.xz", "w:xz") as archive:
        archive.add(source / "_build/stage2", arcname="stage2")
    report["current_phase"] = "target executables built; native runtime unverified"
    report_path.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
