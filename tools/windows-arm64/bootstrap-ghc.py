#!/usr/bin/env python3
"""Probe a Windows-hosted ARM64 GHC using the pinned upstream CI toolchain.

The upstream binary-dist-stage3 rule currently has no directory rule. Build
the target executables directly so that failure cannot mask compiler errors.
The resulting stage directory is diagnostic output, not a release bindist.
"""

import json
import hashlib
import importlib.util
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
    patch = Path(__file__).with_name("ghc-native-probe.patch").resolve()
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=source, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=source, check=True)
    report["probe_patch_sha256"] = hashlib.sha256(patch.read_bytes()).hexdigest()
    ci = source / ".gitlab/ci.sh"
    original = ci.read_text()
    marker = '  build_hadrian) time_it "build" build_hadrian ;;'
    if original.count(marker) != 1:
        raise RuntimeError("Pinned GHC CI dispatcher changed")
    ci.write_text(original.replace(marker, marker + '\n'
        '  pandoc_target_probe) run_hadrian pandoc-native-compiler-probe ;;'))
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
    spec = importlib.util.spec_from_file_location(
        "verify_pandoc", Path(__file__).with_name("verify-pandoc.py"))
    verification = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verification)
    report["executables"] = {}
    for name in ("ghc", "ghc-pkg"):
        executable = source / "_build/stage2/bin" / name
        machine = verification.pe_machine(executable)
        if machine != 0xAA64:
            raise RuntimeError(f"{executable} is not Windows ARM64: {machine:#06x}")
        report["executables"][name] = {"machine": hex(machine)}
    with tarfile.open(source / "ghc-target-stage-probe.tar.xz", "w:xz") as archive:
        archive.add(source / "_build/stage2", arcname="stage2")
    report["current_phase"] = "target executables built; native runtime unverified"
    report_path.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
