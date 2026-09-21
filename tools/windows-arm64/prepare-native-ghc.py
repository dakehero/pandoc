#!/usr/bin/env python3
"""Prepare the probe's GHC files for a disposable Windows ARM64 compiler test."""

import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import subprocess
import tarfile


def extract_compiler(archive_path, output):
    output.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive_path) as archive:
        members = {m.name.rstrip("/"): m for m in archive.getmembers()}

        def resolve(member, seen=()):
            if member.name in seen:
                raise ValueError(f"Archive link cycle: {member.name}")
            if member.issym() or member.islnk():
                target = member.linkname
                if target.startswith("/") and "/_build/stage2/" in target:
                    target = "stage2/" + target.split("/_build/stage2/", 1)[1]
                elif member.issym():
                    target = posixpath.join(posixpath.dirname(member.name), target)
                target = posixpath.normpath(target)
                if not target.startswith("stage2/"):
                    raise ValueError(f"Link is outside target stage: {member.name}")
                return resolve(members[target], (*seen, member.name))
            if not member.isfile():
                raise ValueError(f"Expected a regular target file: {member.name}")
            return member

        for member in members.values():
            if not member.name.startswith(("stage2/bin/", "stage2/lib/")):
                continue
            destination = output.joinpath(*PurePosixPath(member.name).parts[1:]).resolve()
            if not destination.is_relative_to(output):
                raise ValueError(f"Unsafe archive path: {member.name}")
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            source = resolve(member)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(source) as incoming, destination.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--llvm", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Run this compiler test on Windows ARM64")
    output = args.output.resolve()
    llvm = args.llvm.resolve(strict=True)
    extract_compiler(args.archive, output)
    # GHC's Windows findToolDir requires a sibling mingw directory even when
    # every compiler/linker path in the target record is already absolute.
    shutil.copytree(llvm, output / "mingw")
    llvm = output / "mingw"
    reports = output / "verification"
    reports.mkdir()
    settings_path = output / "lib/settings"
    settings = ast.literal_eval(settings_path.read_text(encoding="utf-8"))
    # GHC writes a list of string tuples; do not execute the settings as code.
    if not all(isinstance(pair, tuple) and len(pair) == 2 and
               all(isinstance(part, str) for part in pair) for pair in settings):
        raise ValueError("Unexpected GHC settings format")
    missing_tools = []

    def native_tool(match):
        name = match[1]
        # The prefixed ld shipped by LLVM-MinGW is a POSIX shell wrapper.
        # Clang already supplies the ARM64 PE emulation when invoking ld.lld.
        if name == "aarch64-w64-mingw32-ld":
            name = "ld.lld"
        tool = llvm / "bin" / (name if name.endswith(".exe") else name + ".exe")
        if not tool.is_file():
            missing_tools.append(str(tool))
        return tool.as_posix()

    def relocate(value):
        value = re.sub(r"/opt/llvm-mingw-linux/bin/([A-Za-z0-9+_.-]+)", native_tool, value)
        value = value.replace("/opt/llvm-mingw-linux", llvm.as_posix())
        value = value.replace('"llvm-dlltool-19"',
                              json.dumps((llvm / "bin/llvm-dlltool.exe").as_posix()))
        value = re.sub(r'/__w/[^ "\n]*/_build/stage2', lambda _: output.as_posix(), value)
        return value.replace("_build/stage2", output.as_posix())

    overrides = {"LibDir": (output / "lib").as_posix(),
                 "Relative Global Package DB": "package.conf.d"}
    rewritten = [(key, overrides.get(key, relocate(value))) for key, value in settings]
    settings_path.write_text("[" + ",\n".join(
        "(" + json.dumps(key) + "," + json.dumps(value, ensure_ascii=False) + ")"
        for key, value in rewritten) + "]\n", encoding="utf-8")
    package_db = output / "lib/package.conf.d"
    # This GHC revision keeps C/linker commands in toolchain target records,
    # rather than in the older settings format. Preserve the target properties
    # while replacing only paths to the corresponding native LLVM programs.
    for path in (output / "lib/targets").glob("*.target"):
        content = relocate(path.read_text(encoding="utf-8"))
        # Unlike the Linux cross-build host, this Windows host can execute the
        # Windows ARM64 target. GHC exposes this field as "cross compiling".
        content = content.replace("tgtLocallyExecutable = False", "tgtLocallyExecutable = True")
        path.write_text(content, encoding="utf-8")
    for path in package_db.glob("*.conf"):
        path.write_text(relocate(path.read_text(encoding="utf-8")), encoding="utf-8")
    environment = os.environ.copy()
    environment["PATH"] = str(llvm / "bin") + os.pathsep + environment["PATH"]
    spec = importlib.util.spec_from_file_location(
        "verify_pandoc", Path(__file__).with_name("verify-pandoc.py"))
    verification = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verification)
    report = {"scope": "compiler, Template Haskell and C callback smoke",
              "unavailable_referenced_tools": sorted(set(missing_tools)), "commands": []}

    def run(*command):
        result = subprocess.run([str(arg) for arg in command], env=environment,
                                cwd=reports, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=300)
        record = {"command": list(map(str, command)), "exit_code": result.returncode,
                  "stdout": result.stdout, "stderr": result.stderr}
        report["commands"].append(record)
        (reports / "compiler-smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({key: value[:4000] if isinstance(value, str) else value
                          for key, value in record.items()}), flush=True)
        if result.returncode:
            raise RuntimeError(f"Compiler test command failed: {command}")
        return result.stdout

    compiler = output / "bin/ghc.exe"
    manager = output / "bin/ghc-pkg.exe"
    for path in (compiler, manager):
        if verification.pe_machine(path) != 0xAA64:
            raise ValueError(f"Not a Windows ARM64 executable: {path}")
    run(manager, f"--global-package-db={package_db}", "recache")
    run(compiler, f"-B{output / 'lib'}", "--info")
    smoke = Path(__file__).with_name("smoke").resolve()
    hello = reports / "hello.exe"
    run(compiler, f"-B{output / 'lib'}", "-fforce-recomp",
        "-odir", reports, "-hidir", reports, smoke / "Hello.hs", "-o", hello)
    if verification.pe_machine(hello) != 0xAA64:
        raise ValueError("GHC did not produce a native ARM64 executable")
    if "Native Haskell compilation passed" not in run(hello):
        raise RuntimeError("Unexpected basic compiler smoke output")
    executable = reports / "smoke.exe"
    run(compiler, f"-B{output / 'lib'}", "-threaded", "-fforce-recomp",
        "-odir", reports, "-hidir", reports, "-stubdir", reports,
        smoke / "Main.hs", smoke / "ffi.c", "-o", executable)
    if verification.pe_machine(executable) != 0xAA64:
        raise ValueError("GHC did not produce a native ARM64 executable")
    result = run(executable)
    if "Native C and Haskell callback passed" not in result:
        raise RuntimeError("Unexpected compiler smoke output")
    template_exe = reports / "template-haskell.exe"
    run(compiler, f"-B{output / 'lib'}", "-fforce-recomp",
        "-odir", reports, "-hidir", reports,
        smoke / "TemplateHaskell.hs", "-o", template_exe)
    if verification.pe_machine(template_exe) != 0xAA64:
        raise ValueError("Template Haskell did not produce an ARM64 executable")
    if "Native Template Haskell passed" not in run(template_exe):
        raise RuntimeError("Unexpected Template Haskell smoke output")


if __name__ == "__main__":
    main()
