# Release readiness: can this nightly become a release?

This is the quality standard an OpenMS release has to meet, and the procedure that checks it.
It is written so that an agent can be told *"check our nightlies and determine whether we can
release"* and carry it out: every check names the command or workflow that produces its
evidence, what counts as a pass, and whether a failure blocks the release.

How to *make* the release (tagging, PyPI, Bioconda, docs, announcement) is
[RELEASE-PROCESS.md](RELEASE-PROCESS.md); it names the checks below that gate each step.

A filled-in example is [readiness/2026-09-24-3.6.0-nightly.md](readiness/2026-09-24-3.6.0-nightly.md);
start new reports from [readiness/TEMPLATE.md](readiness/TEMPLATE.md).

## Verdict

A run of this procedure ends with exactly one verdict:

| Verdict | Meaning |
| --- | --- |
| **NOT READY** | A blocking check in A–F failed or was not run for the chosen revision. |
| **READY FOR RC** | Every blocking check in A–F passed on one revision. What only a tag build exercises (G) and what needs a person (H) is still open: tag the release (release candidates are broken, see [RELEASE-PROCESS.md](RELEASE-PROCESS.md#3-release-candidate-optional-untested)) and check G before announcing it. |
| **READY TO RELEASE** | Additionally, G passed on the tag build's own artifacts and a maintainer signed off H. |

Rules that keep the verdict honest:

- **One revision.** Every artifact reports the git revision it was built from (check A2).
  A verdict covers one revision; when the newest wheels and installers disagree, evaluate
  the newest revision for which all artifacts exist, or wait for the next nightly.
- **Not run is not passed.** A check that could not run is reported as *not run*, with the
  reason. A blocking check that did not run caps the verdict at NOT READY.
- **Only maintainers waive.** A maintainer may accept a failing blocking check for one release
  in writing (an issue or PR comment). The report links the waiver. An agent never waives,
  and never downgrades a check from blocking to advisory on its own.
- **Evidence, not impressions.** Every result links to a workflow run, a report file or the
  command output it came from. A finding that looks like a bug gets a minimal reproduction.
- **Report, don't fix.** Checking a nightly changes nothing in OpenMS. Findings go to the
  report (and to issues, if asked).

## Quick start for an agent

1. **Identify the candidate** (A1, A2): `python3 scripts/resolve_nightly.py wheel` and
   `python3 scripts/resolve_nightly.py desktop`, then read the revisions as described in A2.
2. **Automated Linux gate**: run the
   [Release readiness](https://github.com/timosachsenberg/openms-test-lab/actions/workflows/release-readiness.yml)
   workflow with its defaults, or on a Linux machine with sudo:
   `python3 scripts/release-readiness.py all`. Read `reports/readiness-summary.md`; it lists
   every automated result of A2, A3, C (with C6 on every documented distribution and C10 for
   the container image), D, E, F6 and F11 by check ID. (GitHub offers a new
   workflow for dispatch only once it is on the default branch; before that, run the script.)
3. **Platform labs** (B): dispatch the release matrix below with `debug=false`. Every lab
   that installs a desktop package also runs C1–C3 (the full upstream TOPP suite), C5, C9 and
   F6 on that platform, and a Linux lab C6 for its architecture. Run 10, macOS pkg relocation,
   installs the previous release and then the candidate (C8). Run 11 checks the arm64
   container image (C10).
4. **Static artifact checks** (F) and **judgement checks** (D5, E4): commands below.
5. **Write the report**: copy `readiness/TEMPLATE.md` to
   `readiness/<date>-<version>-<candidate>.md`, tick every box, state the verdict and list
   the blocking failures first.

Dispatching and reading runs from a shell:

```bash
gh workflow run release-readiness.yml -R timosachsenberg/openms-test-lab
gh workflow run linux-lab.yml -R timosachsenberg/openms-test-lab \
  -f runner=ubuntu-24.04 -f python_version=3.12 -f pyopenms_spec=nightly -f openms_package=nightly -f debug=false
gh workflow run macos-pkg-relocation.yml -R timosachsenberg/openms-test-lab \
  -f candidate=nightly -f previous=latest
gh workflow run container-lab.yml -R timosachsenberg/openms-test-lab \
  -f image=ghcr.io/openms/openms-tools-thirdparty:latest -f runner=ubuntu-24.04-arm
gh run list -R timosachsenberg/openms-test-lab --workflow linux-lab.yml --limit 3
gh run download <run-id> -R timosachsenberg/openms-test-lab --dir runs/<run-id>
```

Agents without `gh` use the GitHub API (`actions_run_trigger`, `actions_get`,
`actions_list`) with the same inputs. **Always pass `debug=false`**: the default opens an SSH
session that keeps the runner busy for an hour.

### Release matrix for 3.6

| # | Workflow | Runner | Python | `pyopenms_spec` | `openms_package` | Covers |
| --- | --- | --- | --- | --- | --- | --- |
| R | Release readiness | `ubuntu-24.04` | 3.12 | `nightly` | `nightly` | A2, A3, C1–C3, C5, C6, C9 and F6 on Linux x64, C10 (x64 image), D, E, F11 |
| 1 | Windows package lab | `windows-2025` | 3.12 | `nightly` | `nightly` | `win_amd64` wheel, `Win64.exe`, C1–C3, C5, C9 and F6 on Windows |
| 2 | Windows package lab | `windows-2025` | 3.14 | `nightly` | `none` | newest CPython, wheel only |
| 3 | macOS package lab | `macos-15` | 3.12 | `nightly` | `nightly` | Apple Silicon wheel and `.pkg`, C1–C3, C5, C9 and F6 on macOS |
| 5 | macOS package lab | `macos-15` | 3.14 | `nightly` | `none` | newest CPython on Apple Silicon |
| 6 | Linux package lab | `ubuntu-24.04` | 3.12 | `nightly` | `nightly` | x86_64 wheel and DEB |
| 7 | Linux package lab | `ubuntu-24.04-arm` | 3.12 | `nightly` | `nightly` | aarch64 wheel and DEB, C1–C3, C5, C6, C9 and F6 on ARM |
| 8 | Linux package lab | `ubuntu-22.04` | 3.12 | `nightly` | `none` | the wheel's `manylinux_2_34` floor on the oldest LTS |
| 9 | Linux package lab | `ubuntu-24.04` | 3.14 | `nightly` | `none` | newest CPython on Linux |
| 10 | macOS pkg relocation | `macos-15` | – | – | `candidate=nightly`, `previous=latest` | C8, F11 |
| 11 | Container lab | `ubuntu-24.04-arm` | – | – | `image=ghcr.io/openms/openms-tools-thirdparty:latest` | C10 for the arm64 image |

Changes against the 3.5 matrix in the README: run 4 (macOS Intel) is gone because 3.6 ships no
Intel builds; run 8 no longer installs the DEB, because the 3.6 DEB requires glibc 2.38
(Ubuntu 24.04 or Debian 13) and cannot install on 22.04. That is by design once the
[supported platforms](#supported-platforms-36) say so; check C6 verifies that they do.

## Checks

Each check has an ID used in reports and in `reports/readiness-summary.md`.
**Blocking** failures prevent the release; **Advisory** failures are listed in the report
and do not; **Human** checks need a person with a desktop.

### A. Candidate identity

| ID | Check | How | Pass | Level |
| --- | --- | --- | --- | --- |
| A1 | The artifact set is complete | List the nightly index and archive folder (`resolve_nightly.py` prints both locations) | For one date: wheels for `manylinux` x86_64 and aarch64, `macosx` arm64 and `win_amd64`; installers `Win64.exe`, `macOS-Silicon.pkg`, `Linux-x86_64.deb` and `Linux-aarch64.deb`, exactly one each | Blocking |
| A2 | All artifacts come from one revision | Wheel: `python -c "import pyopenms; print(pyopenms.VersionInfo.getRevision())"`. Installer: the `Revision:` line of `FileInfo --help` | One revision for everything under test | Blocking |
| A3 | The version agrees everywhere | `scripts/release-docs-audit.py` → `VERSION-STRINGS` | `CMakeLists.txt`, `pyproject.toml`, `vcpkg.json`, both Sphinx `conf.py` and the CHANGELOG heading carry the release version; the docs version switcher lists it | Blocking at release, advisory on a nightly |

### B. Packaging on every platform

| ID | Check | How | Pass | Level |
| --- | --- | --- | --- | --- |
| B1–B9 | Each run of the release matrix | The package labs; what every run asserts is listed in the [README](README.md#what-every-run-asserts) | Every step up to and including the desktop smoke test succeeds. The step *Start every installed tool and run upstream TOPP tests* is judged separately, under C1–C3, C5 and F6, so that one finding is not counted twice | Blocking |

### C. The installed desktop package

These run in the Release readiness workflow (Linux x64) and in every package lab that installs a
desktop package (`scripts/installed-checks.py`), so each platform has its own result.

| ID | Check | How | Pass | Level |
| --- | --- | --- | --- | --- |
| C1 | Every registered tool starts | `scripts/topp-tools-smoke.py` → `reports/topp-tools.json` | Each tool in `share/OpenMS/TOOLS/*.tsv` exits 0 on `--help` and prints a `Version:` line, `-write_ctd` writes a CTD that parses and has a category, and all tools report the same version | Blocking |
| C2 | The bundled search engines start | same report, `thirdparty` | Every engine under `share/OpenMS/THIRDPARTY` that has a payload starts without a loader error | Blocking |
| C3 | Upstream TOPP and TOPPAS tests pass on the installation | `scripts/installed-topp-tests.py --select all --fetch-missing` (the labs' default; see [below](#how-c3-replays-the-upstream-tests)) → `reports/installed-topp-tests.json` | No test fails. Every skipped or not-registered test is listed with its reason; one of a tool that is new in this release needs that reason in the report. `package_configuration` matches the package (a wrongly detected build option hides tests) and `replay_notes` is empty | Blocking |
| C4 | Adapters find the bundled engines on their own | Run `CometAdapter` and `SageAdapter` without `-comet_executable` / `-sage_executable` on each platform | Exit 0 | Advisory |
| C5 | Vendor readers work in the installed package | Thermo: install a .NET 8 runtime and run `FileConverter -in ginkgotoxin-ms-switching.raw -out x.mzML -RawToMzML:reader inprocess` (the file is in `src/tests/topp/THIRDPARTY/`), then with the default reader, then with the default reader through a symbolic link that has a name of its own, which is how Nextflow and Galaxy stage every input (OpenMS/OpenMS#10451); `FileInfo -in x.mzML`. Bruker: the same with a timsTOF `.d.zip` from `https://archive.openms.de/openms/testfiles/`. pyOpenMS: `ThermoRawFile` and `BrukerTimsFile` load the same files. The package labs run the Thermo part (`thermo` in `reports/installed-checks.json`; on Windows with the PATH the installer sets) | mzML written, spectra > 0, same spectrum count from both readers and through the link, and the mzML read through the link names the link in its `sourceFile` (as that reader names the real file: ThermoRawFileParser drops the extension), so that results still match the experimental design. A runner that may not create a link records that part as not run | Blocking for every reader the CHANGELOG announces |
| C6 | The DEB installs where it claims to | Linux labs (runs 6 and 7) install it on the runner next to `libsqlite3-dev`. Then `scripts/deb-distributions.py` (Linux labs and Release readiness) installs it with `apt-get` in a clean container of every distribution the [installation page](#supported-platforms-36) names, checks with `ldd` that every ELF file of the package resolves its libraries and that no symbolic link of it dangles, and starts `FileInfo --help`, `OpenMSInfo` and `TOPPView --help`; in containers of the distributions the page excludes, `apt-get` has to refuse it for an unmet dependency → `reports/deb-distributions.json`. The runner is the build distribution, the one place where the names `dpkg-shlibdeps` writes into `Depends:` are sure to exist; 3.6.0 did not install on Ubuntu 26.04 and Debian 13 (OpenMS/OpenMS#10351) | Installs without conflicts and starts on every named distribution, is refused on every excluded one, and the glibc floor of `Depends:` matches the docs | Blocking |
| C7 | Upgrades order correctly | `dpkg --compare-versions <nightly-version> lt <release-version>`; install the previous release, then the candidate | A nightly sorts below its release; the upgrade leaves no files from the old version | Advisory |
| C8 | A macOS upgrade installs the apps into the candidate's folder | [macOS pkg relocation](https://github.com/timosachsenberg/openms-test-lab/actions/workflows/macos-pkg-relocation.yml) (run 10) with `candidate` and `previous`, the release before it: `scripts/pkg-relocation.py upgrade` installs `previous`, registers its apps with Launch Services and Spotlight, installs the candidate over it, and records the Installer's own relocation lines from `install.log` → `reports/upgrade.json` | Every app of the candidate is in its own folder (`/Applications/OpenMS-<candidate version>/`), and the previous release's TOPPView, TOPPAS and INIFileEditor are unchanged. Not proven by a pass: which apps the Installer finds depends on the Mac's Launch Services and Spotlight state, and a runner is not a user's Mac (with relocatable apps, [one run](https://github.com/timosachsenberg/openms-test-lab/actions/runs/36905909728) relocated one app of three). F11 is the gate; this is the upgrade users do | Advisory |
| C9 | The package parallelizes with OpenMP | `installed-checks.py` runs `OpenMSInfo` → `openmp` in `reports/installed-checks.json`, on every platform. A build that finds no OpenMP runtime falls back to `-fopenmp-simd`, which compiles out every `#pragma omp parallel`: the tools then run single-threaded whatever `-threads` says, as the 3.6.0 macOS package did (OpenMS/OpenMS#10326) | `OpenMP : enabled` everywhere | Blocking |
| C10 | The container image works like an installed package | `scripts/container-checks.py --image ghcr.io/openms/openms-tools-thirdparty:<tag>` (Release readiness for x64, Container lab, run 11, for arm64) → `reports/container-checks.json`, with the image's own C1–C3, C5, C9 and F6 reports under `reports/container/`. Three steps: the image as published (every ELF file under `/opt/OpenMS` resolves its libraries, no link dangles, `FileInfo` and `OpenMSInfo` start); `installed-checks.py` in a throwaway container of it, which gets `git` and `cmake` (the upstream tests' check steps run `cmake -P`) for that and finds the engines of `/opt/OpenMS/thirdparty` through links in `share/OpenMS/THIRDPARTY`; and the build options C3 reads from the image against the installers' (PeptDeep/ONNX, Bruker timsTOF, OpenSwath; `--expect`). The images come from `containerdeploy.yml`, not from the Release workflow, with Ubuntu's libraries and options of their own: until OpenMS/OpenMS#10462 they had no ONNX Runtime and no PeptDeep models. `latest` is built from `nightly`; compare its revision with A2 | All three steps pass on x64 and arm64 | Advisory |

#### How C3 replays the upstream tests

OpenMS CI runs `src/tests/topp/CMakeLists.txt` (with `THIRDPARTY/third_party_tests.cmake`) and
`src/tests/toppas/CMakeLists.txt` against its build tree. The TOPPAS file also runs every
example pipeline under `share/OpenMS/examples/TOPPAS`. `installed-topp-tests.py` runs the same
files against an installation, so the example pipelines are the installed ones.
It interprets them in order, as a configure step would: `set`, `list`, `if`, `foreach`,
`macro`, `include`, `option`, `find_program`, `configure_file`, `add_test`,
`set_tests_properties` and the rest of the small set of commands they use. The tests then run
with ctest's rules: a `DEPENDS` companion runs after the test it depends on,
`PASS_REGULAR_EXPRESSION` decides instead of the exit code, `WILL_FAIL` inverts the result,
and `SKIP_RETURN_CODE`, `ENVIRONMENT` and `TIMEOUT` apply.

- **What the build knew is read from the package** and written to `package_configuration`
  with its evidence:
  - `TOPP_TOOLS`: the installed registry.
  - `DISABLE_OPENSWATH`, `WITH_WNETALIGN` and `WITH_GUI`: whether OpenSwathWorkflow,
    FeatureLinkerWNet and ImageCreator are registered.
  - `WITH_OPENTIMS`: whether `d` is among FileConverter's input formats.
  - `ENABLE_TDL`: whether `FileInfo -write_cwl` works.
  - `HAVE_ZLIB_NG`: whether the zlib the tools load is zlib-ng.
  - `WITH_ONNX`: whether the PeptDeep models are in `share/OpenMS/models` and ONNX Runtime is
    loaded with libOpenMS or linked into it. Without it, a package built `WITH_ONNX` would
    run the tests meant for a build without ONNX (`TOPP_OpenDIA_predicted_requires_onnx`
    fails on such a package) and skip the PeptDeep ones.
  - The platform variables come from the runner. `-D NAME=VALUE` overrides any of these.
- **Deviations from CI, on purpose:**
  - `DATA_DIR_SHARE` and `CF_OPENMS_DATA_PATH` are the installed `share/OpenMS`, because that
    is what users get.
  - The bundled engines in `share/OpenMS/THIRDPARTY` stand in for CI's downloaded ones, and
    their directories are on `PATH`, as in CI. Whether the package finds them on its own is C4.
  - An input that the revision has but the sparse checkout lacks is fetched with
    `--fetch-missing`, or the test is skipped.
  - Tools that open a Qt application (ExecutePipeline) run on Qt's `offscreen` platform where
    the package's Qt has one. On Linux the distribution's Qt provides it. Otherwise they use
    the native platform, as a user would. `qt_platform` in the report says which. A macOS
    package without `offscreen` cannot run pipelines without a logged-in desktop session;
    record that under C3 as advisory.
- **Not covered:**
  - Tests whose `if()` is false for the package are reported as not registered, with the
    condition and the values it read. On the 3.6 nightly these are: Bruker DDA data
    (`-D OPENTIMS_DDA_TEST_DATA=<dir.d>` enables them), a Mascot server, a licensed
    MSFragger, Novor, the SpectraST tests that upstream disables (`AND FALSE`), and the CWL
    round trip without TDL.
  - Class tests are compiled test programs that exist only in a build tree, so they are not
    replayed.
- **Cost:** the whole installed-checks step, including C1, C2, the Thermo part of C5 and F6, takes 4 to 7 minutes on
  the hosted runners for about 2,200 tests (`--jobs` defaults to half the cores). The TOPPAS example pipelines take a good part of that. `--select
  release-gate` is the quick subset: new tools, workflows, native formats, adapters and
  pipelines.

### D. pyOpenMS: API and user guide

| ID | Check | How | Pass | Level |
| --- | --- | --- | --- | --- |
| D1 | Every public name removed since the last release is announced | `scripts/pyopenms-api.py diff … --changelog CHANGELOG` → `removed_names_not_in_changelog` | Empty, or every remaining name is listed in the report with a maintainer's acceptance | Blocking |
| D2 | No user-guide page regressed | `scripts/doc-examples.py --baseline <previous release's report>` → `regression` pages | No page that ran with the previous release fails with the candidate | Blocking |
| D3 | The user guide teaches no deprecated API | same report, `warnings` | No `DeprecationWarning` from pyOpenMS while a page runs | Advisory |
| D4 | New classes have docstrings | `pyopenms-api.py diff` → `added_classes_without_docstring` | Empty | Advisory |
| D5 | Every intentional API change has a migration note | For each D2 regression, decide: *bug* (report with a reproduction) or *intentional* (a changed signature, return value or type). Every intentional change needs a `BREAKING` entry in the PyOpenMS section that shows the new call, and the page must be updated | No intentional change without both | Blocking |
| D6 | The wheel's own tests passed for this revision | The `pyopenms-wheels-cibuildwheel.yml` run in OpenMS/OpenMS for the candidate revision | Green on all four platforms | Blocking |

### E. Documentation

| ID | Check | How | Pass | Level |
| --- | --- | --- | --- | --- |
| E1 | Every tool is in the TOPP index and has a complete page | `release-docs-audit.py` → `DOC-TOOL-INDEX`, `DOC-TOOL-PAGE` | Every registered tool listed once; its page has `@brief` and the generated `.cli`/`.html` parameter includes | Blocking for tools new in this release, advisory otherwise |
| E2 | New and removed tools are in the CHANGELOG | `DOC-TOOL-CHANGELOG` | Added tools under *New tools*, removed ones under *Removed tools*, with the name users knew in the previous release | Blocking |
| E3 | Nothing refers to removed tools | `DOC-STALE-TOOLS` | No hits outside CHANGELOG history | Advisory |
| E4 | Every headline feature is documented for users | Judgement, see [below](#e4-headline-features) | Each headline feature has a user-facing page or section; pyOpenMS-exposed features also a user-guide section | Blocking |
| E5 | New public classes are documented | `DOC-CLASS-BRIEF` | Every new public header documents its main class | Advisory |
| E6 | Build options are documented | `DOC-CMAKE-OPTIONS` | New user-facing options documented, removed ones gone from the docs | Advisory |
| E7 | Environment variables are documented | `DOC-ENV-VARS` | Each OpenMS-specific variable the code reads is named in user documentation | Advisory |
| E8 | The CHANGELOG is clean | `CHANGELOG-LINT` | No duplicated bullets or orphaned text; at release, the heading carries a date instead of "under development" | Blocking at release |
| E9 | Documentation builds without warnings | Build the `doc` target and run `Doxygen_Warning_test` (OpenMS `doc/CMakeLists.txt`); run `doc-validate.yml` (Sphinx for `doc/openms` and `doc/pyopenms`) on the candidate revision | Zero Doxygen warnings; both Sphinx builds succeed | Blocking |
| E10 | The online documentation of the version exists | For every tool, the `Full documentation:` URL of `--help` (`doc_url` in `topp-tools.json`); `https://pyopenms.readthedocs.io/en/v<version>/` (before 3.6.0 `release-<version>`), which exists once the readthedocs version is activated ([RELEASE-PROCESS.md, step 7](RELEASE-PROCESS.md#7-documentation)) | HTTP 200 everywhere | Blocking after deployment |

#### E4: headline features

1. List the headline features from the release's CHANGELOG section: *General*, *New tools*,
   *OpenMS Library → Added*, and the new bindings named in *PyOpenMS*.
2. For each, search the user documentation: `doc/openms/docs/**` (openms.readthedocs.io),
   `doc/doxygen/public/*.doxygen`, the tool's own `@page`, and for anything bound in Python
   `doc/pyopenms/docs/source/user_guide/*.rst`. `pyopenms-api.py diff --docs` lists every new
   Python class the user guide never mentions, which is the starting point for the last one.
3. Record, per feature, the page that documents it or **gap**, and whether an existing page
   now describes the feature wrongly (a changed default, a removed option).
4. A gap in a headline feature blocks; class-level API docs alone do not count as
   user-facing documentation.

### F. Static checks of the artifacts

F1–F10 each caught a finding in the [3.5.0 audit](PACKAGE-AUDIT-3.5.0.md) that no lab run
surfaced; F11 comes from OpenMS/OpenMS#8477. F6 (labs and Release readiness) and F11 (Release
readiness and macOS pkg relocation) are automated; the others are run by hand against the
candidate files.

| ID | Check | How | Pass | Level |
| --- | --- | --- | --- | --- |
| F1 | Wheel platform tags match the declared floor | Wheel filenames; `macholib` `LC_BUILD_VERSION minos` for every Mach-O | Tags equal the supported-platform list in the docs and CHANGELOG, and no object needs a newer OS than its tag | Blocking |
| F2 | Wheels are intact | `RECORD` hashes and sizes; SHA-256 against the index | All match | Blocking |
| F3 | Wheel metadata is usable | `twine check`; `Requires-Python`, `License-File` in `METADATA` | Present and correct | Advisory |
| F4 | Stubs are valid Python | `compile()` every `.pyi` under `-W error`; runtime namespace vs stubs | No errors; no undeclared public names | Advisory |
| F5 | `manylinux` compliance | `auditwheel show` | Consistent with the tag | Blocking |
| F6 | No known-vulnerable bundled library | `scripts/bundled-libs.py <installation or unpacked wheel>` → `reports/bundled-libs.json`: versions of bundled OpenSSL, zlib, curl, SQLite, bzip2 and Qt, whether they ship as files of their own or are linked statically into another binary (`"linkage": "static"`). Since 3.6 the Linux and Windows wheels link vcpkg's static libraries into `libOpenMS` and `OpenMS.dll`, and several THIRDPARTY engines carry their own zlib or SQLite. OpenSSL is judged against the advisories on openssl-library.org, the others are checked by hand against their projects' advisories. A static curl reports no version (`?`): take it from the vcpkg baseline of the candidate's revision. A static copy whose identifying texts the linker dropped stays invisible | No bundled library with an unfixed High or Critical CVE | Blocking |
| F7 | Installers are signed | `signtool verify /pa` on the `.exe`; `pkgutil --check-signature` and `spctl -a -vv -t install` on the `.pkg` | Valid signature, notarized `.pkg` | Blocking |
| F8 | Third-party licenses ship with what they cover | List bundled third-party components (installer `THIRDPARTY/`, managed Thermo assemblies, vendored libraries) against `share/OpenMS/LICENSES/` | Each component that requires its license to accompany it has its license file | Blocking |
| F9 | The DEB does not collide with the distribution | `dpkg-deb -c` against `dpkg -S` ownership on the target distribution; vendored libraries in a private directory | No path owned by a distribution package; no system library copied into `/usr/lib` | Advisory |
| F10 | The Linux and Windows wheels bundle no third-party shared library | `unzip -l <wheel> 'pyopenms.libs/*'` for the `manylinux` and `win_amd64` wheels (the macOS wheel takes its dependencies from Homebrew and is not covered) | Linux: only `libOpenMS`, `libOpenSwathAlgo`, `libopenms_thermo_bridge` and the GCC runtime (`libgomp`, `libgfortran`, `libquadmath`). Windows: only `OpenMS`, `OpenSwathAlgo` and the MSVC runtime (`msvcp140*`, `vcomp140`). A third-party library that became shared again (Arrow, OpenSSL, zlib, curl) is loaded next to pyarrow's copy, and F6 then has to judge it as a file of its own | Advisory |
| F11 | The macOS installer relocates no app bundle | `scripts/macos_pkg.py <pkg> --expect-no-relocation`, on any OS: it reads the `PackageInfo` of every component straight from the archive → `reports/macos-pkg.json`. The package is `nightly`, a release tag, a URL or a file; Release readiness takes it as `macos_package` | No component lists a bundle under `<relocate>`. A relocatable app is installed over an app with the same identifier wherever the Installer finds one, such as in an older OpenMS, instead of into the candidate's folder (OpenMS/OpenMS#8477). Packages before OpenMS/OpenMS#8479, 3.6.0 included, fail. Not proven by a pass: where a given Mac puts the apps (C8) | Blocking |

### G. Release mechanics: only a tag build exercises them

A nightly cannot prove these. They are checked on the build of the release tag `v<version>`,
before PyPI, Bioconda and the announcement ([RELEASE-PROCESS.md, step 5](RELEASE-PROCESS.md#5-what-the-tag-starts-and-how-to-check-it)).
A release-candidate tag `v<version>-rc<N>` would be checked the same way, but that path is
broken today ([step 3](RELEASE-PROCESS.md#3-release-candidate-optional-untested)): its deploy
likely fails, and its packages cannot pass G2.

| ID | Check | How | Pass | Level |
| --- | --- | --- | --- | --- |
| G1 | The tag builds and uploads | `release.yml` run of the tag | Green; installers in `archive.openms.de/openms/OpenMSInstaller/release/<version>/`, docs under `Documentation/release/<version>/`, both `latest` symlinks moved; the GitHub release *Release &lt;version&gt;* carries the installers and `OpenMS-<version>.tar.gz` | Blocking |
| G2 | Tag builds carry a clean version | `FileInfo --help`, installer file names, the macOS application folder | `Version: <version>`, with no `-pre-…` suffix | Blocking |
| G3 | The source tarball is right | The tarball artifact of the tag run | Named as the bioconda recipe expects, without `.ccache` or `_thirdparty`, of plausible size | Blocking |
| G4 | Workflows triggered by the tag pass | Actions tab of OpenMS/OpenMS for the tag | Green, or a known and accepted exception | Advisory |
| G5 | The tag build's own artifacts pass B and C | The release matrix with `openms_package=v<version>` and `pyopenms_spec=<wheel URL>` from `archive.openms.de/openms/pyopenms/release/<version>/`, before the PyPI upload | As B and C | Blocking |
| G6 | PyPI serves the release everywhere | After upload: every lab with `pyopenms_spec=pyopenms==<version>` | Every platform installs the binary wheel | Blocking, after upload |
| G7 | Conda packages build and install | The bioconda recipe PR for `<version>`; then `conda create -n t --strict-channel-priority -c conda-forge -c bioconda python=3.12 openms pyopenms` and `OpenMSInfo`, `python -c "import pyopenms"` | Recipe CI green; environment works | Blocking for the conda channel |
| G8 | Documentation and links point at the release | readthedocs builds for the tag; `README.md`, installation pages and `release-announcement.txt` link to the current download server | Builds exist; links resolve to this version | Blocking |
| G9 | Container images exist for the tag | `containerdeploy.yml` run; then C10 with `ghcr.io/openms/openms-tools-thirdparty:<version>` on x64 and arm64 | Images published, and C10 passes for them | Advisory |

### H. Human checks

| ID | Check | Pass | Level |
| --- | --- | --- | --- |
| H1 | GUI on each platform: TOPPView opens an mzML in 1D and 2D; TOPPAS loads and runs a workflow from `share/OpenMS/examples/TOPPAS`; INIFileEditor opens and saves a tool INI; the splash screen shows the release version | All work | Human, blocking |
| H2 | TOPPAS *Open containing folder* on macOS (a past installer-only regression) | Opens Finder | Human, advisory |
| H3 | Clean-machine install: Windows without the VC++ redistributable or .NET; a fresh macOS user (Gatekeeper). The Linux part, a minimal container per distribution, is automated as C6 | Installs and starts; a missing runtime produces a clear message | Human, blocking |
| H4 | The installer's license page | Current text | Human, advisory |

## Supported platforms (3.6)

Checks B, C6 and F1 compare the artifacts with what the release claims. The claims live in the
CHANGELOG (*Dependencies*) and `doc/openms/docs/about/installation/`. As of 2026-09-27 they are:
- no macOS Intel builds;
- macOS 15 or newer (CHANGELOG, since OpenMS/OpenMS#10285). This matches the wheels'
  `macosx_15_0` tag (`src/pyOpenMS/pyproject.toml` sets `MACOSX_DEPLOYMENT_TARGET = "15.0"`),
  but the `.pkg` does not enforce it until OpenMS/OpenMS#10286;
- Python 3.11 or newer;
- DEB for glibc 2.38 or newer (`installation-on-gnu-linux.md`, since OpenMS/OpenMS#10277).
- For 3.7: the DEB installs on Ubuntu 24.04 and 26.04 and on Debian 13, and not on Ubuntu 22.04
  or Debian 12 (`installation-on-gnu-linux.md`, since OpenMS/OpenMS#10367; the 3.6.0 DEB
  installs on Ubuntu 24.04 only, OpenMS/OpenMS#10351). C6 tests exactly these lists: keep
  `INSTALLS` and `REFUSED` in `scripts/deb-distributions.py` in step with that page.

Resolve disagreements between these before a release; the report flags them under F1 and C6.

## The former wiki checklist

The OpenMS wiki page
[Testing an OpenMS release candidate](https://github.com/OpenMS/OpenMS/wiki/Testing-an-OpenMS-release-candidate)
predates GitHub Actions releases, native vendor readers and the removal of KNIME. Its items map
onto this procedure as follows.

| Wiki item | Status in 3.6 | Where it lives now |
| --- | --- | --- |
| RC installers on `abibuilder.cs.uni-tuebingen.de/.../OpenMSInstaller/release/` | Changed: a `v<version>-rc<N>` tag uploads to `archive.openms.de/openms/OpenMSInstaller/rc<N>/<version>/`; RCs get no GitHub release. abibuilder no longer receives uploads | G1, G5 |
| KNIME update site | Obsolete: KNIME support was removed in 3.6.0 (#10135) | none |
| Tutorial data and workflows on abibuilder | Changed: data remains only on abibuilder (`archive.openms.de/openms/Tutorials/` is 404) and is still linked from the TOPPView tutorial and the pyOpenMS user guide; the shipped `share/OpenMS/examples/TOPPAS/*.toppas` use only current tools | H1, E3, G8 |
| Documentation available and correct, version numbers | Still relevant | A3, E9, E10, G8 |
| Splash screens show the correct version | Still relevant; the version is drawn at runtime from `VersionInfo`, so it shows whatever G2 finds | G2, H1 |
| Clean OS installation (VM) | Still relevant; hosted runners are not clean machines. Automated for the DEB in clean containers | C6, H3 |
| License text in the installer (version, year) | Mostly moot: `License.txt` says "2002-present" and has no version; third-party licenses matter more | H4, F8 |
| All installed tools can be executed | Automated | C1 |
| Third-party executables installed and working | Automated for starting them; adapters on Linux need explicit paths | C2, C3, C4 |
| Tutorial pipelines run; pwiz conversions (Windows); Thermo RAW via FileConverter | Changed: pwiz (`msconvert`) still ships on Windows; Thermo `.raw` is now also read natively (.NET 8) and Bruker `.d` via timsTOF support | C3, C5, H1 |
| Interactive applications (TOPPView, TOPPAS, INIFileEditor, IDEvaluator) | Changed: IDEvaluator is gone since 2.4; SwathWizard and FLASHDeconvWizard were removed in 3.6 | H1, E2 |
| TOPPAS *Open containing folder* on macOS | Still relevant, manual | H2 |
| Python wheels from GitHub Actions, `AASequence` smoke test | Automated: labs take a wheel run ID, the nightly index or PyPI, and run more than the wiki's snippet | B, D |
| Conda packages (Python 3.6/3.7 commands) | Changed: two recipes in `bioconda-recipes` (`openms-meta` with `libopenms`/`openms`/`openms-thirdparty`, and `pyopenms`); conda-forge before bioconda with strict priority; Python 3.11+ | G7 |
| Report bugs labelled "OpenMS x.y.z RC1" | Changed: the bug form has a required version field; paste `OpenMSInfo` output and the installer file name | report |

## Adding a check

Give it the next free ID in its section, a pass criterion that a script or a person can decide
without interpretation, a level, and an entry in `readiness/TEMPLATE.md`. Automate it in the
script that already produces the related evidence and add its row to
`scripts/release-readiness.py summary`. Keep the checks honest about what they cannot see: say
what a pass does *not* prove.
