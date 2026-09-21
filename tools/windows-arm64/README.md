# Windows ARM64 validation

This fork separates installer readiness from compiler and application readiness.
It does **not** currently provide a native Windows ARM64 Pandoc release.

## Verified packaging changes

`windows/pandoc.wxs` selects `ProgramFiles64Folder` for both x64 and ARM64 and
requires Windows Installer 5.0 for ARM64. The existing x64 requirement remains
3.01. Both are tested with WiX 3.14.1; upgrading to a different WiX major version
is not necessary for this change.

[Package validation run 35637157902](https://github.com/dakehero/pandoc/actions/runs/35637157902)
passed on 2026-09-21 UTC:

| Job | Payload | Checks |
| --- | --- | --- |
| `x64-baseline` | Official Pandoc 3.11 x64 ZIP, SHA-256 pinned | PE machine; standalone HTML; Unicode input/output paths; DOCX round trip; EPUB; Lua FFI; citeproc; JSON AST; ZIP extraction; WiX linking with ICE validation; MSI metadata, install, runtime, uninstall |
| `arm64-msi-fixture` | Locally compiled ARM64 C fixture, **not Pandoc** | PE `0xAA64`; native execution on `windows-11-arm`; real Pandoc WiX authoring; MSI Arm64 template; Installer 5.0; 64-bit components and Program Files directory; install, execution, uninstall |

The ARM64 artifact is named `windows-arm64-msi-fixture-not-pandoc`. Its MSI is
a disposable CI fixture and must not be distributed as a Pandoc release.
The x64 baseline uses a published executable rather than rebuilding this fork.
These checks do not establish that Pandoc's Haskell dependencies compile for
Windows ARM64 or that the full Pandoc test suite passes on that platform.

The existing x64 release fails an absolute Unicode Lua filter path on the
English-locale CI runner with `recoverEncode: invalid argument (cannot encode
character '\\20013')`. The same probe passes on the local Windows ARM64 machine
running that x64 executable. The required Lua smoke uses a relative filter path;
the absolute-path probe and its exact stderr are retained separately in every
runtime JSON report. This is not counted as passing Unicode Lua-path support.

## Reproduce package checks

Use PowerShell 7 on a disposable Windows runner for MSI lifecycle checks.
They install/uninstall the package and can replace an existing Pandoc MSI.
Runtime and ZIP checks do not install Pandoc or change PATH.

```powershell
python tools/windows-arm64/package-pandoc.py path/to/pandoc.exe --architecture arm64 --wix-bin path/to/wix --output package-results
./tools/windows-arm64/verify-msi.ps1 -MsiPath package-results/pandoc-3.11-windows-arm64.msi -Architecture arm64 -ReportDirectory package-results
```

The packager rejects an x64 PE passed with `--architecture arm64` before running
or packaging it. Change the MSI filename to match the executable's version.
For the installer-only fixture:

```powershell
python tools/windows-arm64/msi-fixture.py --wix-bin path/to/wix --output fixture-results
./tools/windows-arm64/verify-msi.ps1 -MsiPath fixture-results/arm64-fixture.msi -Architecture arm64 -ReportDirectory fixture-results -PayloadKind Arm64Fixture
```

## Compiler probe and remaining gates

`windows-arm64.yml` runs on Linux ARM64 in the pinned official GHC cross-build
image, using GHC source `5236634abce50db7e8e7ecf375def90bf45d2476`. It reuses the
upstream Windows ARM64 cross-job variables and native bignum backend.

The initial `CROSS_STAGE=3` attempt failed because `binary-dist-stage3` depends
on `binary-dist-dir-stage3`, whose definition is commented out in
[`Rules/BinaryDist.hs`](https://github.com/ghc/ghc/blob/5236634abce50db7e8e7ecf375def90bf45d2476/hadrian/src/Rules/BinaryDist.hs).
See [run 35634686026](https://github.com/dakehero/pandoc/actions/runs/35634686026).
Enabling the commented rule alone is insufficient: that code also uses the
build host for Windows wrappers and executes the packaged `ghc-pkg` on the
build host.

The current probe applies `ghc-native-probe.patch`, which uses Hadrian's
`bindistPackageTargets targetBindist` to resolve the target compiler and package
manager paths without building a bindist. Hardcoded `.exe` paths and stage3
simple aliases are not valid entry points on this pinned Linux build host.
The script records the patch checksum, failed phase and exit code in
`arm64-bootstrap.json` and checks any resulting executables for ARM64 PE headers.
Any target-stage archive is diagnostic output, **not an installed/relocatable
GHC distribution**.

The current experiment follows the native-compiler route. A Linux-hosted cross
compiler is another possible route, but the upstream cross CI smoke runs only
a small Haskell program under Wine; it does not prove that Pandoc's Template
Haskell, build tools, Lua and C dependencies can be cross-built.

Before adding ARM64 to the release workflow, these gates must pass:

1. Establish a usable compiler/toolchain route: either a Windows-hosted GHC with
   native C/linker tools, settings, package database and distribution, or a
   cross compiler with working build-time Haskell execution.
2. Verify compilation and native execution of a Haskell program, Template
   Haskell and C FFI; for the native route also verify the compiler PE machine
   and execution on Windows ARM64.
3. Solve and build Pandoc and its dependencies with embedded data and Lua
   enabled, then run the project's relevant test suites on Windows ARM64.
4. Run the same runtime, ZIP, and MSI checks against that real ARM64 executable.
5. Integrate distinct ARM64 artifact names/caches and obtain upstream signing
   and release configuration. A fork CI artifact is not a signed public release.

The upstream release workflow is deliberately not expanded to an ARM64 matrix
entry before those gates have been validated.
