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

[Run 35638337747](https://github.com/dakehero/pandoc/actions/runs/35638337747)
reached native target library compilation and linked `ghc-pkg`, then failed with
`rule finished running but did not produce file: _build/stage2/bin/ghc-pkg`.
The Windows linker appends `.exe`, but Hadrian used the Linux host's extension
when generating and matching program paths. The probe patch now selects the
Windows target extension and uses `programPath` for program lookup as well.
The workflow preserves build caches for subsequent diagnostic iterations and
checks compiler executable startup on Windows ARM64 after a successful build.
Startup alone does not establish compiler, Template Haskell or Pandoc usability.
[Run 35645086353](https://github.com/dakehero/pandoc/actions/runs/35645086353)
passed both target compilation and native executable startup. Both executables
have PE machine `0xAA64` and report GHC `10.1.20260917`. The preserved compiler
build cache is available for further experiments.

`windows-native-toolchain.yml` continues from a selected bootstrap artifact on
`windows-11-arm`. It uses SHA-256-pinned native LLVM-MinGW 19.1.7, relocates the
compiler settings, toolchain target records and package registrations, and
recaches the package database. LLVM is copied into the sibling `mingw` directory
required by GHC's Windows toolchain discovery. The Linux prefixed `ld` shell
wrapper is replaced with native `ld.lld.exe`, and the target is marked locally
executable on the Windows ARM64 host. The probe separately compiles and executes
a basic Haskell program, a C/Haskell callback, and a Template Haskell splice.
Each executable must have the ARM64 PE machine type. These are diagnostic
checks; adding the workflow is not evidence that they passed.

After the compiler checks succeed, the workflow uses the official Cabal 3.18.1.0
x64 frontend under emulation with the explicitly selected native ARM64 GHC.
It resolves dependencies without relaxing package bounds, builds and tests all
project packages with Lua, embedded data and HTTP enabled, then runs the
runtime, ZIP and MSI checks against the resulting ARM64 Pandoc. Failures stop
later gates and retain the available logs. No system toolchain is installed on
the local host by these scripts.

To reproduce the compiler smoke on Windows ARM64, use a fresh output directory:

```powershell
python tools/windows-arm64/prepare-native-ghc.py ghc-target-stage-probe.tar.xz --llvm path/to/llvm-mingw-20250114-ucrt-aarch64 --output native-ghc
```

The archive is still an uninstalled compiler probe. The preparation script
copies target-stage files and resolves internal file links without creating
Windows symlinks; it rejects traversal, external links and link cycles. The
resulting compiler directory is for this pinned experiment, not a release GHC
distribution.

### Native compiler results and runtime linker blocker

Local Windows ARM64 testing with the compiler from run `35645086353` and the
prepared LLVM layout passed package-database recaching, `ghc --info`, native
Haskell compilation/execution, and a C function invoking a Haskell callback.
The generated executables were checked for ARM64 PE headers before execution.

The separate Template Haskell test fails with exit code 11 after repeated
`PE/PE+ not supported on ARM64.` messages and an access violation. This is not
an installer or PATH problem: the pinned GHC
[`rts/linker/PEi386.c`](https://github.com/ghc/ghc/blob/5236634abce50db7e8e7ecf375def90bf45d2476/rts/linker/PEi386.c#L2349)
has only a placeholder in its ARM64 relocation branch. The existing native
code generator and static C/Haskell FFI work, but this does not establish
runtime object loading, GHCi or Template Haskell support.

The native workflow deliberately fails this gate and retains the diagnostic
report; later Pandoc build/package steps are not counted as passing or skipped
silently. Completing this route requires GHC runtime linker development and
validation, plus native build helpers such as `unlit` and `hsc2hs`. The LLVM
backend is also unverified; the successful native compilation uses GHC's native
code generator.

An independent local `cabal build all --dry-run --enable-tests
--disable-optimization -fembed_data_files -flua -fhttp` with the explicitly
selected native compiler also failed dependency resolution. At Hackage index
state `2026-09-21T20:25:14Z`, GHC's bundled `base-4.23.0.0` conflicts with
`vector-0.13.2.0` and `0.13.1.0`, which require `base < 4.23`; the selected
`aeson` requires `vector ^>= 0.13.0.0`. This is the first observed solver
blocker, not an exhaustive list of dependency compatibility problems. No
`allow-newer` overrides or production dependency changes were made.

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
