#!/usr/bin/env python3
"""Check native GHC executable startup only; this is not a compiler usability test."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tarfile

archive_path, output = map(Path, sys.argv[1:])
output.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location(
    "verify_pandoc", Path(__file__).with_name("verify-pandoc.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
report = {"scope": "native executable startup only", "programs": {}}
with tarfile.open(archive_path) as archive:
    for name in ("ghc.exe", "ghc-pkg.exe"):
        # Do not extract build-tree symlinks or arbitrary archive paths.
        member = archive.getmember(f"stage2/bin/{name}")
        if not member.isfile():
            raise ValueError(f"Expected a regular executable: {member.name}")
        executable = output / name
        with archive.extractfile(member) as stream:
            executable.write_bytes(stream.read())
        machine = module.pe_machine(executable)
        if machine != 0xAA64:
            raise ValueError(f"{name} has wrong PE machine: {machine:#06x}")
        result = subprocess.run([str(executable.resolve()), "--version"],
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=60)
        report["programs"][name] = {"machine": hex(machine),
                                     "exit_code": result.returncode,
                                     "stdout": result.stdout, "stderr": result.stderr}
        (output / "native-startup.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report["programs"][name]))
        if result.returncode or "version" not in result.stdout.lower():
            raise RuntimeError(f"{name} failed native startup")
