#!/usr/bin/env python3
"""Package a verified Windows binary using Pandoc's existing WiX authoring."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

import importlib.util


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--architecture", choices=("arm64", "x64"), required=True)
    parser.add_argument("--wix-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    executable = args.executable.resolve(strict=True)
    wix = args.wix_bin.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "verify_pandoc", Path(__file__).with_name("verify-pandoc.py")
    )
    verification = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verification)
    verification.verify(executable, args.architecture,
                        output / f"verification-{args.architecture}.json")
    version_line = subprocess.check_output([str(executable), "--version"],
                                            text=True, encoding="utf-8").splitlines()[0]
    match = re.fullmatch(r"pandoc (\d+\.\d+(?:\.\d+){0,2})", version_line)
    if not match:
        raise ValueError(f"Expected a release version, got {version_line!r}")
    version = match[1]
    label = {"x64": "x86_64", "arm64": "arm64"}[args.architecture]
    basename = f"pandoc-{version}-windows-{label}"
    with tempfile.TemporaryDirectory(prefix="pandoc-package-") as temporary:
        working = Path(temporary)
        package = working / f"pandoc-{version}"
        package.mkdir()
        shutil.copy2(executable, package / "pandoc.exe")
        shutil.copy2(root / "COPYRIGHT", package / "COPYRIGHT.txt")
        for source, name, options in (
            ("MANUAL.txt", "MANUAL.html", ["-s", "--toc"]),
            ("COPYING.md", "COPYING.rtf", ["-s", "-t", "rtf"]),
        ):
            subprocess.run([str(executable), *options, str(root / source),
                            "-o", str(package / name)], check=True, cwd=root)
        for pattern in ("*.wxs", "*.wxl"):
            for source in (root / "windows").glob(pattern):
                shutil.copy2(source, working / source.name)
        shutil.copy2(package / "COPYING.rtf", working / "COPYING.rtf")
        objects = working / "wixobj"
        objects.mkdir()
        subprocess.run([
            str(wix / "candle.exe"), "-arch", args.architecture,
            f"-dVERSION={version}", f"-dBINPATH={package}",
            *[str(p) for p in sorted(working.glob("*.wxs"))],
            "-out", str(objects) + "\\",
        ], cwd=working, check=True)
        subprocess.run([
            str(wix / "light.exe"), "-sw1076", "-ext", "WixUIExtension",
            "-ext", "WixUtilExtension", "-cultures:en-us",
            "-loc", "Pandoc-en-us.wxl", "-out", str(output / f"{basename}.msi"),
            *[str(p) for p in sorted(objects.glob("*.wixobj"))],
        ], cwd=working, check=True)
        archive_path = output / f"{basename}.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(package.iterdir()):
                archive.write(path, path.relative_to(working))
        # Validate the archive's actual executable, not just the build tree.
        unpacked = working / "unpacked"
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(unpacked)
        verification.verify(unpacked / package.name / "pandoc.exe",
                            args.architecture,
                            output / f"verification-zip-{args.architecture}.json")
    hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (output / f"{basename}.zip", output / f"{basename}.msi")
    }
    (output / f"{basename}.sha256.json").write_text(
        json.dumps(hashes, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
