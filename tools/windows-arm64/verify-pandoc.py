#!/usr/bin/env python3
"""Check the PE architecture and exercise a packaged Windows Pandoc."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import zipfile


def pe_machine(path):
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError(f"Not a PE executable: {path}")
        stream.seek(0x3C)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        if stream.read(4) != b"PE\0\0":
            raise ValueError(f"Invalid PE signature: {path}")
        return struct.unpack("<H", stream.read(2))[0]


def verify(executable, architecture, output):
    executable = executable.resolve(strict=True)
    expected = {"arm64": 0xAA64, "x64": 0x8664}[architecture]
    actual = pe_machine(executable)
    if actual != expected:
        raise ValueError(f"Expected {architecture} PE machine {expected:#06x}, "
                         f"got {actual:#06x}: {executable}")
    report = {"architecture": architecture, "machine": hex(actual),
              "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
              "checks": []}
    # Run away from the source tree and installed data directories. The
    # portable release must carry its own templates and reference documents.
    with tempfile.TemporaryDirectory(prefix="pandoc-arm64-") as temporary:
        directory = Path(temporary) / "中文 path"
        directory.mkdir()

        def run(*args):
            result = subprocess.run([str(executable), *args], cwd=directory,
                                    capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=90)
            if result.returncode:
                raise RuntimeError(f"Pandoc exited {result.returncode}: {args!r}\n"
                                   f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
            return result.stdout

        report["version"] = run("--version").splitlines()[0]
        markdown = directory / "输入.md"
        markdown.write_text("# 中文标题\n\nHello **ARM64**.\n\n$x^2$\n",
                            encoding="utf-8")
        html = run(str(markdown), "-s", "-t", "html5",
                   "--metadata=title:ARM64 verification")
        assert "中文标题" in html and "<strong>ARM64</strong>" in html
        assert "<!DOCTYPE html>" in html, "Embedded HTML template missing"
        report["checks"].append("standalone HTML and Unicode input path")

        document = directory / "输出.docx"
        run(str(markdown), "-o", str(document))
        with zipfile.ZipFile(document) as archive:
            assert "word/document.xml" in archive.namelist()
        plain = run(str(document), "-t", "plain")
        assert "中文标题" in plain and "ARM64" in plain
        report["checks"].append("DOCX creation and round trip")

        epub = directory / "输出.epub"
        run(str(markdown), "-o", str(epub), "--metadata=title:ARM64")
        with zipfile.ZipFile(epub) as archive:
            assert archive.read("mimetype") == b"application/epub+zip"
        report["checks"].append("EPUB creation")

        lua = directory / "filter.lua"
        lua.write_text('function Str(el)\n'
                       '  if el.text == "ARM64" then el.text = "Lua_OK" end\n'
                       '  return el\nend\n', encoding="utf-8")
        filtered = run(str(markdown), "-t", "plain", "--lua-filter", lua.name)
        assert "Lua_OK" in filtered
        report["checks"].append("Lua filter and Haskell/C FFI")
        # Lua's narrow fopen path is locale-dependent in the existing Windows
        # release. Record this separately from the required FFI smoke test.
        probe = subprocess.run(
            [str(executable), str(markdown), "-t", "plain", "--lua-filter", str(lua)],
            cwd=directory, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=90)
        report["absolute_unicode_lua_path"] = {
            "passed": probe.returncode == 0 and "Lua_OK" in probe.stdout,
            "exit_code": probe.returncode, "stderr": probe.stderr,
        }

        bibliography = directory / "refs.json"
        bibliography.write_text(json.dumps([{
            "id": "test", "type": "book", "title": "Citation verification",
            "author": [{"family": "Example", "given": "Alice"}],
            "issued": {"date-parts": [[2026]]}
        }]), encoding="utf-8")
        citation = directory / "citation.md"
        citation.write_text("See [@test].\n", encoding="utf-8")
        cited = run(str(citation), "--citeproc", "--bibliography",
                    str(bibliography), "-t", "plain")
        assert "Example" in cited and "citation verification" in cited.casefold(), cited
        report["checks"].append("citeproc and embedded default CSL")

        native = run(str(markdown), "-t", "json")
        assert json.loads(native)["blocks"]
        assert "html" in run("--list-output-formats").splitlines()
        report["checks"].append("JSON AST and format enumeration")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--architecture", choices=("arm64", "x64"), required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    verify(args.executable, args.architecture, args.report)
