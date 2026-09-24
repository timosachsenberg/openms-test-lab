# Release readiness: can this nightly become a release?

This is the quality standard an OpenMS release has to meet, and the procedure that checks it.
It is written so that an agent can be told *"check our nightlies and determine whether we can
release"* and carry it out: every check names the command or workflow that produces its
evidence, what counts as a pass, and whether a failure blocks the release.

A filled-in example is [readiness/2026-09-24-3.6.0-nightly.md](readiness/2026-09-24-3.6.0-nightly.md);
start new reports from [readiness/TEMPLATE.md](readiness/TEMPLATE.md).

## Verdict

A run of this procedure ends with exactly one verdict:

| Verdict | Meaning |
| --- | --- |
| **NOT READY** | A blocking check in A–F failed or was not run for the chosen revision. |
| **READY FOR RC** | Every blocking check in A–F passed on one revision. What only a tag build exercises (G) and what needs a person (H) is still open: tag a release candidate. |
| **READY TO RELEASE** | Additionally, G passed on the release candidate's own artifacts and a maintainer signed off H. |

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
   every automated result of C, D and E by check ID.
3. **Platform labs** (B): dispatch the release matrix below with `debug=false`. Every lab
   that installs a desktop package also runs C1–C3 on that platform.
4. **Static artifact checks** (F) and **judgement checks** (D5, E4): commands below.
5. **Write the report**: copy `readiness/TEMPLATE.md` to
   `readiness/<date>-<version>-<candidate>.md`, tick every box, state the verdict and list
   the blocking failures first.

Dispatching and reading runs from a shell:

```bash
gh workflow run release-readiness.yml -R timosachsenberg/openms-test-lab
gh workflow run linux-lab.yml -R timosachsenberg/openms-test-lab \
  -f runner=ubuntu-24.04 -f python_version=3.12 -f pyopenms_spec=nightly -f openms_package=nightly -f debug=false
gh run list -R timosachsenberg/openms-test-lab --workflow linux-lab.yml --limit 3
gh run download <run-id> -R timosachsenberg/openms-test-lab --dir runs/<run-id>
```

Agents without `gh` use the GitHub API (`actions_run_trigger`, `actions_get`,
`actions_list`) with the same inputs. **Always pass `debug=false`**: the default opens an SSH
session that keeps the runner busy for an hour.

### Release matrix for 3.6

| # | Workflow | Runner | Python | `pyopenms_spec` | `openms_package` | Covers |
| --- | --- | --- | --- | --- | --- | --- |
| R | Release readiness | `ubuntu-24.04` | 3.12 | `nightly` | `nightly` | C1–C3 on Linux x64, D, E |
| 1 | Windows package lab | `windows-2025` | 3.12 | `nightly` | `nightly` | `win_amd64` wheel, `Win64.exe`, C1–C3 on Windows |
| 2 | Windows package lab | `windows-2025` | 3.14 | `nightly` | `none` | newest CPython, wheel only |
| 3 | macOS package lab | `macos-15` | 3.12 | `nightly` | `nightly` | Apple Silicon wheel and `.pkg`, C1–C3 on macOS |
| 5 | macOS package lab | `macos-15` | 3.14 | `nightly` | `none` | newest CPython on Apple Silicon |
| 6 | Linux package lab | `ubuntu-24.04` | 3.12 | `nightly` | `nightly` | x86_64 wheel and DEB |
| 7 | Linux package lab | `ubuntu-24.04-arm` | 3.12 | `nightly` | `nightly` | aarch64 wheel and DEB, C1–C3 on ARM |
| 8 | Linux package lab | `ubuntu-22.04` | 3.12 | `nightly` | `none` | the wheel's `manylinux_2_34` floor on the oldest LTS |
| 9 | Linux package lab | `ubuntu-24.04` | 3.14 | `nightly` | `none` | newest CPython on Linux |

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
| B1–B9 | Each run of the release matrix | The package labs; what every run asserts is listed in the [README](README.md#what-every-run-asserts) | Every step up to and including the desktop smoke test succeeds. The step *Start every installed tool and run upstream TOPP tests* is judged separately, under C1–C3 and F6, so that one finding is not counted twice | Blocking |

### C. The installed desktop package

These run in the Release readiness workflow (Linux x64) and in every package lab that installs a
desktop package (`scripts/installed-checks.py`), so each platform has its own result.

| ID | Check | How | Pass | Level |
| --- | --- | --- | --- | --- |
| C1 | Every registered tool starts | `scripts/topp-tools-smoke.py` → `reports/topp-tools.json` | Each tool in `share/OpenMS/TOOLS/*.tsv` exits 0 on `--help` and prints a `Version:` line, `-write_ctd` writes a CTD that parses and has a category, and all tools report the same version | Blocking |
| C2 | The bundled search engines start | same report, `thirdparty` | Every engine under `share/OpenMS/THIRDPARTY` that has a payload starts without a loader error | Blocking |
| C3 | Upstream TOPP tests pass on the installation | `scripts/installed-topp-tests.py --select release-gate` → `reports/installed-topp-tests.json` | No test fails. Skips are listed; a skipped test of a tool that is new in this release needs a reason in the report | Blocking |
| C4 | Adapters find the bundled engines on their own | Run `CometAdapter` and `SageAdapter` without `-comet_executable` / `-sage_executable` on each platform | Exit 0 | Advisory |
| C5 | Vendor readers work in the installed package | Thermo: install a .NET 8 runtime and run `FileConverter -in ginkgotoxin-ms-switching.raw -out x.mzML -RawToMzML:reader inprocess` (the file is in `src/tests/topp/THIRDPARTY/`), then with the default reader; `FileInfo -in x.mzML`. Bruker: the same with a timsTOF `.d.zip` from `https://archive.openms.de/openms/testfiles/`. pyOpenMS: `ThermoRawFile` and `BrukerTimsFile` load the same files | mzML written, spectra > 0, same spectrum count from both readers | Blocking for every reader the CHANGELOG announces |
| C6 | The DEB installs where it claims to | Linux labs (runs 6 and 7) install it next to `libsqlite3-dev`; compare the `Depends:` line (`dpkg-deb -f <deb> Depends`) with the documented supported distributions | Installs without conflicts; the glibc floor matches the docs | Blocking |
| C7 | Upgrades order correctly | `dpkg --compare-versions <nightly-version> lt <release-version>`; install the previous release, then the candidate | A nightly sorts below its release; the upgrade leaves no files from the old version | Advisory |

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
| E10 | The online documentation of the version exists | For every tool, the `Full documentation:` URL of `--help` (`doc_url` in `topp-tools.json`); `https://pyopenms.readthedocs.io/en/<version>/` | HTTP 200 everywhere | Blocking after deployment |

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

The runtime labs cannot see these; each one caught a finding in the
[3.5.0 audit](PACKAGE-AUDIT-3.5.0.md) that no lab run surfaced.

| ID | Check | How | Pass | Level |
| --- | --- | --- | --- | --- |
| F1 | Wheel platform tags match the declared floor | Wheel filenames; `macholib` `LC_BUILD_VERSION minos` for every Mach-O | Tags equal the supported-platform list in the docs and CHANGELOG, and no object needs a newer OS than its tag | Blocking |
| F2 | Wheels are intact | `RECORD` hashes and sizes; SHA-256 against the index | All match | Blocking |
| F3 | Wheel metadata is usable | `twine check`; `Requires-Python`, `License-File` in `METADATA` | Present and correct | Advisory |
| F4 | Stubs are valid Python | `compile()` every `.pyi` under `-W error`; runtime namespace vs stubs | No errors; no undeclared public names | Advisory |
| F5 | `manylinux` compliance | `auditwheel show` | Consistent with the tag | Blocking |
| F6 | No known-vulnerable bundled library | Version strings of bundled OpenSSL, zlib, Qt, curl, SQLite in every wheel and installer (`strings -a <lib> \| grep -m1 '^OpenSSL '` and similar) against current advisories | No bundled library with an unfixed High or Critical CVE | Blocking |
| F7 | Installers are signed | `signtool verify /pa` on the `.exe`; `pkgutil --check-signature` and `spctl -a -vv -t install` on the `.pkg` | Valid signature, notarized `.pkg` | Blocking |
| F8 | Third-party licenses ship with what they cover | List bundled third-party components (installer `THIRDPARTY/`, managed Thermo assemblies, vendored libraries) against `share/OpenMS/LICENSES/` | Each component that requires its license to accompany it has its license file | Blocking |
| F9 | The DEB does not collide with the distribution | `dpkg-deb -c` against `dpkg -S` ownership on the target distribution; vendored libraries in a private directory | No path owned by a distribution package; no system library copied into `/usr/lib` | Advisory |

### G. Release mechanics: only a tag build exercises them

A nightly cannot prove these. Push a release-candidate tag (`v<version>-rc<N>`) once A–F pass,
then check:

| ID | Check | How | Pass | Level |
| --- | --- | --- | --- | --- |
| G1 | The RC builds and uploads | `release.yml` run of the tag | Green; installers in `archive.openms.de/openms/OpenMSInstaller/rc<N>/<version>/`, docs under `Documentation/rc<N>/<version>/` | Blocking |
| G2 | Tag builds carry a clean version | `FileInfo --help`, installer file names, the macOS application folder | `Version: <version>`, with no `-pre-…` suffix | Blocking |
| G3 | The source tarball is right | The tarball artifact of the tag run | Named as the bioconda recipe expects, without `.ccache` or `_thirdparty`, of plausible size | Blocking |
| G4 | Workflows triggered by the tag pass | Actions tab of OpenMS/OpenMS for the tag | Green, or a known and accepted exception | Advisory |
| G5 | The RC's own artifacts pass B and C | The release matrix with the RC's URLs (`openms_package=<https URL>`, `pyopenms_spec=<wheel URL>`) | As B and C | Blocking |
| G6 | PyPI serves the release everywhere | After upload: every lab with `pyopenms_spec=pyopenms==<version>` | Every platform installs the binary wheel | Blocking, after upload |
| G7 | Conda packages build and install | The bioconda recipe PR for `<version>`; then `conda create -n t --strict-channel-priority -c conda-forge -c bioconda python=3.12 openms pyopenms` and `OpenMSInfo`, `python -c "import pyopenms"` | Recipe CI green; environment works | Blocking for the conda channel |
| G8 | Documentation and links point at the release | readthedocs builds for the tag; `README.md`, installation pages and `release-announcement.txt` link to the current download server | Builds exist; links resolve to this version | Blocking |
| G9 | Container images exist for the tag | `containerdeploy.yml` run | Images published | Advisory |

### H. Human checks

| ID | Check | Pass | Level |
| --- | --- | --- | --- |
| H1 | GUI on each platform: TOPPView opens an mzML in 1D and 2D; TOPPAS loads and runs a workflow from `share/OpenMS/examples/TOPPAS`; INIFileEditor opens and saves a tool INI; the splash screen shows the release version | All work | Human, blocking |
| H2 | TOPPAS *Open containing folder* on macOS (a past installer-only regression) | Opens Finder | Human, advisory |
| H3 | Clean-machine install: Windows without the VC++ redistributable or .NET; a fresh macOS user (Gatekeeper); Linux in a minimal container (`docker run ubuntu:24.04`, `apt install ./<deb>`) | Installs and starts; a missing runtime produces a clear message | Human (Linux part scriptable), blocking |
| H4 | The installer's license page | Current text | Human, advisory |

## Supported platforms (3.6)

Checks B, C6 and F1 compare the artifacts with what the release claims. The claims live in the
CHANGELOG (*Dependencies*) and `doc/openms/docs/about/installation/`. At the time of writing
they are: no macOS Intel builds; macOS 14 or newer (CHANGELOG), although the wheels are
tagged `macosx_15_0` (`src/pyOpenMS/pyproject.toml` sets `MACOSX_DEPLOYMENT_TARGET = "15.0"`);
Python 3.11 or newer; DEB for glibc 2.38 or newer. Resolve such disagreements before a
release; the report flags them under F1 and C6.

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
| Clean OS installation (VM) | Still relevant; hosted runners are not clean machines | H3 |
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
