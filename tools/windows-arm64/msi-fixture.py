#!/usr/bin/env python3
"""Exercise ARM64 WiX authoring with a native C fixture, NOT a Pandoc build."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess


def verify(executable):
    spec = importlib.util.spec_from_file_location(
        "verify_pandoc", Path(__file__).with_name("verify-pandoc.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    machine = module.pe_machine(executable)
    if machine != 0xAA64:
        raise ValueError(f"Fixture is not native ARM64: {machine:#06x}")
    output = subprocess.check_output([str(executable)], text=True, timeout=30)
    if output.strip() != "Pandoc MSI fixture: ARM64":
        raise ValueError(f"Unexpected fixture output: {output!r}")
    print(json.dumps({"payload_kind": "C fixture, not Pandoc",
                      "machine": hex(machine), "native_execution": "passed"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--wix-bin", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.verify:
        verify(args.verify.resolve(strict=True))
        return
    if not args.wix_bin or not args.output:
        parser.error("--wix-bin and --output are required to build the fixture")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    wix = args.wix_bin.resolve(strict=True)
    root = Path(__file__).resolve().parents[2]
    fixture = output / "fixture"
    fixture.mkdir()
    vswhere = (Path(os.environ["ProgramFiles(x86)"]) /
               "Microsoft Visual Studio/Installer/vswhere.exe")
    vs = subprocess.check_output([str(vswhere), "-latest", "-products", "*",
                                  "-property", "installationPath"], text=True).strip()
    vcvars = Path(vs) / "VC/Auxiliary/Build/vcvarsall.bat"
    if not vcvars.is_file():
        raise FileNotFoundError(vcvars)
    (fixture / "fixture.c").write_text(
        '#include <stdio.h>\n#ifndef _M_ARM64\n#error Expected ARM64\n#endif\n'
        'int main(void) { puts("Pandoc MSI fixture: ARM64"); return 0; }\n')
    build = fixture / "build.cmd"
    build.write_text(f'@echo off\ncall "{vcvars}" arm64\n'
                     'if errorlevel 1 exit /b %errorlevel%\n'
                     'cl /nologo /W4 /WX /Fe:pandoc.exe fixture.c /link /INCREMENTAL:NO\n'
                     'exit /b %errorlevel%\n')
    subprocess.run(["cmd.exe", "/d", "/c", str(build)], cwd=fixture, check=True)
    verify(fixture / "pandoc.exe")
    (fixture / "COPYRIGHT.txt").write_text("Installer test fixture, not Pandoc.\n")
    (fixture / "COPYING.rtf").write_text(r"{\rtf1 Installer test fixture.}")
    (fixture / "MANUAL.html").write_text("<!doctype html><title>MSI fixture</title>")
    for pattern in ("*.wxs", "*.wxl"):
        for source in (root / "windows").glob(pattern):
            shutil.copy2(source, fixture / source.name)
    objects = fixture / "wixobj"
    objects.mkdir()
    subprocess.run([str(wix / "candle.exe"), "-arch", "arm64",
                    "-dVERSION=99.0.0", f"-dBINPATH={fixture}",
                    *[str(p) for p in sorted(fixture.glob("*.wxs"))],
                    "-out", str(objects) + "\\"], cwd=fixture, check=True)
    subprocess.run([str(wix / "light.exe"), "-sw1076", "-ext", "WixUIExtension",
                    "-ext", "WixUtilExtension", "-cultures:en-us",
                    "-loc", "Pandoc-en-us.wxl", "-out", str(output / "arm64-fixture.msi"),
                    *[str(p) for p in sorted(objects.glob("*.wixobj"))]],
                   cwd=fixture, check=True)


if __name__ == "__main__":
    main()
