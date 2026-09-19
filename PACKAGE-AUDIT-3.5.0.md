# OpenMS 3.5.0 package audit

Audit date: 2026-09-19. Target: every artifact published for `release/3.5.0` — 8 GitHub release
assets and 25 pyOpenMS wheels on PyPI.

Two methods were combined:

- **Runtime labs.** Nine unattended runs of this repository's Windows, macOS and Linux labs against
  the released packages (run IDs in [Lab runs](#lab-runs)).
- **Static artifact analysis.** Every published wheel and native package was downloaded and
  inspected directly (hash verification, `RECORD`/metadata checks, `auditwheel`, `readelf`,
  `macholib`, `pefile`, `dpkg-deb`, XAR/cpio extraction), plus a functional pyOpenMS test suite.

Findings are ordered by release impact. Each one states what was observed and how it was observed,
so it can be re-checked independently.

---

## Summary

| # | Finding | Affects | Severity |
|---|---|---|---|
| 1 | macOS wheels require macOS 15+; 3.4.0 required 13/14 | 10 wheels | **Blocker** |
| 2 | Linux DEB fails to install when `libsqlite3-dev` is present | 3 DEBs | **Blocker** |
| 3 | DEB declares `libc6 (>= 2.28)`, binaries need glibc 2.34 | 3 DEBs | **High** |
| 4 | Two different ARM64 DEBs published under the same name/version | 2 DEBs | **High** |
| 5 | Neither desktop installer is signed | .exe, .pkg | **High** |
| 6 | DEB vendors ~103 system libraries into flat `/usr/lib`, incl. OpenSSL 3.0.2, zlib 1.2.11 | 3 DEBs | **High** |
| 7 | Three different Qt and OpenSSL versions across one release; Linux wheels ship Qt 6.6.2 (CVE-2024-39936) | wheels, DEB | **High** |
| 8 | No `Requires-Python` in any wheel | 25 wheels | Medium |
| 9 | No license file shipped in any wheel | 25 wheels | Medium |
| 10 | `pyopenms.SysInfo` is a leaked `struct sysinfo`; Linux-only name | wheels | Medium |
| 11 | `pyopenms` publicly exports `ctypes`, `numpy`, `warnings`, … | wheels | Medium |
| 12 | Every `import pyopenms` writes to stderr on macOS | 10 wheels | Medium |
| 13 | `IdXMLFile.store/load` silently dropped plain-list support | wheels | Medium |
| 14 | `FeatureMap.get_df()` still returns non-snake_case columns | wheels | Medium |
| 15 | 23 public names have no type-stub declaration | 25 wheels | Medium |
| 16 | Invalid escape sequences in shipped `.pyi` stubs | 25 wheels | Medium |
| 17 | Class→submodule partitioning differs per platform | 25 wheels | Low |
| 18 | macOS PKG declares no minimum OS version | 2 PKGs | Low |
| 19 | macOS PKG offers an "MSFragger" choice with an empty payload | 2 PKGs | Low |
| 20 | `pandas` + `matplotlib` are hard runtime dependencies | 25 wheels | Low |

Items 1–7 should gate the next release. Items 8–16 are each a small, self-contained fix.

---

## Blockers

### 1. macOS wheels exclude macOS 13 and 14 — a regression against 3.4.0

pyOpenMS 3.5.0 publishes `macosx_15_0_arm64` and `macosx_15_0_x86_64` wheels. pip on macOS 13 or 14
matches neither tag and fails with *"Could not find a version that satisfies the requirement
pyopenms"*. Previous releases supported those systems:

| Release | macOS wheel tags |
|---|---|
| 3.3.0 | `macosx_13_0_x86_64`, `macosx_14_0_arm64` |
| 3.4.0 | `macosx_13_0_x86_64`, `macosx_14_0_arm64` |
| **3.5.0** | **`macosx_15_0_arm64`, `macosx_15_0_x86_64`** |

The tag is honest, not merely conservative: 121 of the 134 Mach-O objects in the arm64 wheel carry
`LC_BUILD_VERSION minos = 15.0.0` (`macholib`; the remaining 13 are at 11.x/12.x).

Root cause — two settings disagree, and the workflow wins:

- `src/pyOpenMS/pyproject.toml:256` → `MACOSX_DEPLOYMENT_TARGET = "14.0"`
- `.github/workflows/pyopenms-wheels-cibuildwheel.yml:441` → `MACOSX_DEPLOYMENT_TARGET=15.0`
  inside `CIBW_ENVIRONMENT`, which overrides the `pyproject.toml` value.

**This is still `15.0` on `develop`, so the next release repeats it.** It is also internally
inconsistent: the desktop `.pkg` for the same release is built for macOS 12.0 (`FileInfo` reports
`minos 12.0`, SDK 26.0), so the desktop product supports three major versions that the Python
product does not.

Intel deserves special attention: 3.5.0 is announced as the final Intel release, and it moved the
Intel floor from macOS 13 to 15, locking out Intel Macs that cannot run Sequoia.

*Fix:* drop the `MACOSX_DEPLOYMENT_TARGET=15.0` line from `CIBW_ENVIRONMENT` so the declared 14.0
(or lower) applies, and add a CI assertion that the produced wheel tags match the intended floor.

### 2. The Linux DEB cannot be installed when `libsqlite3-dev` is present

All three DEBs ship `/usr/include/sqlite3.h` (SQLite 3.49.2), a path owned by Debian/Ubuntu's
`libsqlite3-dev`, and declare no `Conflicts:`/`Replaces:`/`Breaks:`. `dpkg` refuses the unpack:

```
dpkg: error processing archive .../OpenMS-3.5.0-Debian-Linux-x86_64.deb (--unpack):
 trying to overwrite '/usr/include/sqlite3.h', which is also in package libsqlite3-dev:amd64 3.45.1-1ubuntu2.7
```

Reproduced in three lab runs — Ubuntu 24.04 x86_64, Ubuntu 22.04 x86_64 and Ubuntu 24.04 arm64
(same error, `libsqlite3-dev:arm64`). It is not architecture- or release-specific. The package is
otherwise fine: apt resolves every declared dependency and unpacks 26 packages before failing on
OpenMS itself.

Note the header is *newer* than the distribution's (3.49.2 vs 3.45.1), so even where the install
succeeds — a machine without `libsqlite3-dev` — it leaves a header on the system that does not match
the system `libsqlite3`, and a later `apt install libsqlite3-dev` then fails.

*Fix:* stop installing third-party headers into `/usr/include`. `sqlite3.h` is a contrib build
artifact, not part of the OpenMS API.

---

## High

### 3. `libc6 (>= 2.28)` is understated by six glibc releases

The DEB control file declares `libc6 (>= 2.28)`, but **all 152 binaries in `/usr/bin` require
`GLIBC_2.34`** (`readelf -V` over every shipped ELF; the maximum version referenced anywhere in the
package is 2.34). On Debian 11 or Ubuntu 20.04 (glibc 2.31) apt accepts the package and every TOPP
tool then fails at startup with a missing-version error.

*Fix:* `libc6 (>= 2.34)`, ideally generated by `dpkg-shlibdeps` rather than hand-maintained.

### 4. Two different ARM64 packages published under one name and version

The release contains both `OpenMS-3.5.0-Debian-Linux-aarch64.deb` and
`OpenMS-3.5.0-Debian-Linux-arm64.deb`. Both declare `Package: openms`, `Version: 3.5.0`,
`Architecture: arm64` — but they are **not the same build**:

| | aarch64.deb | arm64.deb |
|---|---|---|
| SHA-256 | `6fcc3a95…` | `e9d0d696…` |
| `libOpenMS.so` build date | 2025-12-11 | 2025-12-08 |
| Maintainer | `OpenMS Inc <info@openms.de>` | `OpenMS developers <open-ms-general@lists.sourceforge.net>` |
| `MRMAssay::generateTargetAssays_` | takes `std::map` | takes `boost::unordered::unordered_map` |
| Doc files | `TOPP_OpenNuXL.html` | `UTILS_OpenNuXL.html` |

Comparing the packages' own `md5sums`: 225 of 227 files under `/usr/bin` and `/usr/lib` are
identical; `libOpenMS.so` and `libOpenMS_GUI.so` differ. The differing mangled symbols show they
were compiled from different source states three days apart, and the stale maintainer string and old
`UTILS_` doc naming both point at `arm64.deb` being the older, accidental artifact.

Users have no way to tell which to install, and package managers would treat them as the same
package. For contrast, the two source tarballs (`OpenMS-3.5.0.tar.gz` and `OpenMS-3.5.tar.gz`) *are*
byte-identical (`29ddff87…`), so that duplicate is harmless — this one is not.

*Fix:* delete the stale asset from the release and publish exactly one ARM64 DEB.

### 5. Neither desktop installer is signed

- **`OpenMS-3.5.0-Win64.exe`** — the PE Security directory is empty
  (`VirtualAddress=0, Size=0`), i.e. no Authenticode signature. Every user gets a SmartScreen
  *"Windows protected your PC"* interstitial.
- **`OpenMS-3.5.0-macOS-Silicon.pkg`** — the XAR table of contents contains no `<signature>` element
  and zero `<X509Certificate>` entries. An unsigned, un-notarized `.pkg` downloaded from GitHub is
  refused by Gatekeeper on open.

The macOS case is the frustrating one: the *binaries inside* are properly signed. `FileInfo` carries
an `LC_CODE_SIGNATURE` whose CMS slot holds a real 4,779-byte certificate chain (not an ad-hoc
signature), and `TOPPView.app` ships a `_CodeSignature` directory. The signing already happens — only
the installer wrapper is left unsigned, so users still hit the warning.

*Fix:* `productsign` + `notarytool` for the `.pkg`; `signtool` for the `.exe`.

### 6. The DEB vendors ~103 system libraries into flat `/usr/lib`

Alongside `libOpenMS.so`, the DEB installs 103 third-party shared objects **directly into
`/usr/lib`** under their standard SONAMEs, including:

`libcrypto.so.3`, `libssl.so.3`, `libz.so.1.2.11`, `libgnutls.so.30`, `libnettle.so.8`,
`libhogweed.so.6`, `libtasn1.so.6`, `libp11-kit.so.0`, `libkrb5.so.3`, `libgssapi_krb5.so.2`,
`libldap-2.5.so.0`, `libsasl2.so.2`, `libssh.so.4`, `librtmp.so.1`, `libnghttp2.so.14`,
`libcurl-gnutls.so.4`, `libicuuc.so.70`, `libblas.so.3`, `liblapack.so.3`, `libgfortran.so.5`,
`libffi.so.8`, `libgmp.so.10`, `libbz2.so.1.0`, `libzstd.so.1`, `libxerces-c-3.2.so`,
`libboost_regex.so.1.74.0` — **and `libresolv.so.2`, a glibc component.**

Two of these are outdated enough to matter:

- **`libcrypto.so.3` is OpenSSL 3.0.2** (identified from the embedded version string) — the March
  2022 Ubuntu 22.04 build, 19 patch releases behind the current 3.0.21, and affected by fixes issued
  since, including CVE-2026-45447 (High, use-after-free in `PKCS7_verify`).
- **`libz.so.1.2.11` is zlib 1.2.11** (2017) — CVE-2018-25032 (fixed in 1.2.12) and CVE-2022-37434
  (fixed in 1.2.13).

These copies are actually used, not inert: every OpenMS binary carries `RUNPATH $ORIGIN/../lib/`,
which for `/usr/bin/FileInfo` resolves to `/usr/lib` and takes precedence over the loader cache, and
`libOpenMS.so` lists `libcrypto.so.3` and `libz.so.1` among its `NEEDED` entries.

One thing this does **not** do, which is worth stating because it is the obvious worry: it does not
silently downgrade the rest of the system. A controlled `ldconfig` run over a mirrored Ubuntu loader
configuration shows the multiarch entries (`/usr/lib/x86_64-linux-gnu/…`) still rank first in the
resulting cache, so other programs keep resolving to the system copies. The exposure is OpenMS's own
processes, plus the `libresolv.so.2` placement, which has no business being in a non-glibc package.

*Fix:* install private dependencies into a private directory (`/usr/lib/openms/`) rather than
`/usr/lib`, drop `libresolv.so.2` entirely, and rebuild the vendored set against current upstreams.

### 7. Three different Qt and OpenSSL versions inside one release

Each artifact of the same release bundles a different dependency stack:

| Artifact | Qt | OpenSSL | zlib |
|---|---|---|---|
| Windows wheel | 6.8.3 | — (Schannel) | 1.3.1 |
| macOS wheel | 6.9.3 | 3.6.0 | system |
| **Linux wheel** | **6.6.2** | 3.5.1 | system |
| Linux DEB | system Qt6 ≥ 6.2.2 | **3.0.2** | **1.2.11** |

(Qt versions from `_qt_version_info.py` and the binaries themselves; Linux wheel Qt built against
`/usr/lib64`, macOS against `/opt/homebrew/lib`.)

The Linux wheels' **Qt 6.6.2 is affected by CVE-2024-39936** (CVSS 8.6 High) — an HTTP/2 race in
QtNetwork where data can be sent before the TLS handshake result is processed, fixed in Qt 6.7.3 /
6.8.0. Qt 6.6 is out of support, so it will not receive a backport. The Windows (6.8.3) and macOS
(6.9.3) wheels are unaffected, which means the Linux build container is simply the stale one.

The Linux wheels' OpenSSL 3.5.1 is affected by issues fixed in 3.5.5 (January 2026), including
CVE-2025-15467 (High, stack buffer overflow in CMS `(Auth)EnvelopedData` parsing).

*Fix:* pin one Qt and one OpenSSL version across all three wheel builders and the DEB, and refresh
the manylinux build image.

---

## Medium

### 8. No `Requires-Python` in any of the 25 wheels

None of the wheels declare `Requires-Python` in `METADATA` (confirmed for all 25; PyPI reports
`requires_python: null` for every file). Resolvers therefore cannot explain *why* no wheel matches on
an unsupported interpreter, and a future `pyopenms` source distribution would be offered to any
Python version at all.

### 9. No license file in any wheel

No wheel contains a `LICENSE`/`COPYING` file, and `METADATA` carries
`License: http://opensource.org/licenses/BSD-3-Clause` — a URL where an SPDX expression belongs, with
no `License-File` entries. BSD-3-Clause requires the copyright notice to accompany binary
redistribution, and each wheel additionally bundles 14–134 third-party libraries (Qt, OpenSSL, Coin-OR,
Abseil, Arrow, ICU, Kerberos, …) whose license texts are likewise absent.

### 10. `pyopenms.SysInfo` is a leaked Linux `struct sysinfo`

`pyopenms.SysInfo` resolves to `pyopenms._sysinfo.SysInfo` — a `ctypes.Structure` mirroring the Linux
`sysinfo(2)` syscall, with members `uptime`, `loads`, `totalram`, `freeram`, … It is **not** OpenMS's
`SysInfo` class, and `getProcessMemoryConsumption()` is unreachable from Python.

Because `_sysinfo.py` only defines the class under `sys.platform.startswith("linux")`, the name
exists on Linux and not on macOS or Windows — the same release exposes a different API surface
depending on the platform.

### 11. `pyopenms` pollutes its public namespace

`from ._sysinfo import *` and module-level imports publish these as public `pyopenms` attributes:

```
c, ctypes, libc, np, numpy, warnings, print_function, streampos, free_mem,
default_openms_data_path, env_openms_data_path, common_meta_value_types
```

`from pyopenms import *` therefore silently rebinds a user's `np`, `numpy`, `ctypes` and `warnings`.
`print_function` is a Python 2 `__future__` leftover and `streampos` is a leaked C++ type.

### 12. Every `import pyopenms` writes to stderr on macOS

`_sysinfo.py` branches on `linux` and `win32`; macOS falls into the `else` branch and executes
`sys.stderr.write("Determination of memory status is not supported on this \n platform, measuring
for memoryleaks will never fail\n")`. Confirmed in the macOS lab run's `python-smoke.log`. The
message is a developer note about a memory-leak test harness and is meaningless to users, but it
appears on every import and will contaminate any tool that parses stderr.

The `win32` branch is also dead: it depends on `win32api` (pywin32), which pyOpenMS does not require.

### 13. `IdXMLFile.store/load` no longer accepts a list of `PeptideIdentification`

In 3.5.0 these calls require the new `PeptideIdentificationList`; a plain Python list raises

```
Exception: can not handle type of ('/tmp/x.idXML', [<...ProteinIdentification object...>], [PeptideIdentification(...)])
```

The `std::vector<PeptideIdentification>` → `PeptideIdentificationList` change is listed in the
release notes' *OpenMS Library* section, but the pyOpenMS section flags only the DataFrame column
rename as breaking — so Python users reading the pyOpenMS notes get no warning, and every tutorial
and script written against ≤ 3.4 breaks. The error message names neither the expected type nor the
offending argument.

### 14. `FeatureMap.get_df()` still returns non-snake_case columns

The release notes state that DataFrame column names were standardized to lowercase snake_case for
PEP 8. `FeatureMap.get_df()` returns:

```
['peptide_sequence', 'peptide_score', 'ID_filename', 'ID_native_id', 'charge', 'rt', 'mz',
 'rt_start', 'rt_end', 'mz_start', 'mz_end', 'quality', 'intensity']
```

`ID_filename` and `ID_native_id` were missed. `MSSpectrum.get_df()` is correct
(`['mz', 'intensity', 'rt', 'ms_level', 'native_id']`). Since this was a deliberate breaking change,
finishing it now is cheaper than a second break later.

### 15. 23 public names have no type-stub declaration

`py.typed` is present and the stubs parse cleanly, but comparing the runtime namespace against the
shipped `.pyi` files leaves these public names undeclared — type checkers reject them:

```
PeakMap, PeakSpectrum, DPosition1, DPosition2, Interfaces, ArrayWrapperDouble, ArrayWrapperFloat,
SignalToNoiseEstimatorMedianChrom, SimpleOpenMSSpectraFactory, SysInfo, …
```

`PeakMap` and `PeakSpectrum` are the widely used aliases for `MSExperiment`/`MSSpectrum`, so this hits
ordinary code. (The remaining entries are the namespace-pollution names from finding 11, which should
disappear rather than gain stubs.)

### 16. Invalid escape sequences in the shipped stubs

`_pyopenms_*.pyi` contains Doxygen markup that leaked into Python docstrings —
`\<isolationWindow\>` — producing `SyntaxWarning: invalid escape sequence '\<'` on Python 3.12+
(observed in the macOS lab run) and `DeprecationWarning` on 3.11. Invalid escape sequences are
scheduled to become a `SyntaxError`, which would eventually break importing the package's own stubs.
The fix is to emit raw strings or escape the backslash in the stub generator.

---

## Low

### 17. Class→submodule partitioning differs per platform

The 741 public classes and functions are split across `_pyopenms_1` … `_pyopenms_8` differently on
each platform. All eight stub files differ between Linux, macOS and Windows, and `_pyopenms_3`
contains 73, 80 and 88 classes respectively, with disjoint contents.

The **API surface is identical** (741 names on all three platforms, zero differences), so ordinary
code is unaffected. But `__module__`, `repr()` and any pickle that records a class path become
platform-dependent — e.g. `ProteinIdentification` is `pyopenms._pyopenms_3.…` on Linux and a
different submodule on Windows.

### 18. The macOS PKG declares no minimum OS version

The `Distribution` file contains no `allowed-os-versions` constraint, so the installer accepts macOS
releases older than its binaries' 12.0 deployment target and fails later at launch instead of at
install time.

### 19. The macOS PKG offers an install choice that installs nothing

`MSFraggerChoice` appears in the installer's component list, but
`OpenMS-3.5.0-macOS-Silicon-MSFragger.pkg` has a 3,902-byte payload that expands to no files. (Comet,
Sage, Percolator, MS-GF+, LuciPHOr2 and ThermoRawFileParser all ship real payloads.) Not shipping
MSFragger is correct given its license — but the empty, selectable choice should be removed.

### 20. `pandas` and `matplotlib` are hard runtime dependencies

`Requires-Dist: numpy>=1.25.0`, `pandas`, `matplotlib>=3.5`. Only `_dataframes` and `plotting` need
the latter two; making them extras (`pyopenms[plotting]`) would cut installation weight for headless
and container users.

---

## What was verified as sound

Reported so the next audit does not repeat this work:

- **Artifact integrity.** All 25 PyPI wheels match their published SHA-256; none are yanked; every
  `RECORD` is complete and every recorded hash and size matches; no unrecorded files. The
  `share/OpenMS` data set is identical (149 files) across all platforms — an earlier apparent
  discrepancy was an artifact of Linux wheels storing explicit directory entries.
- **manylinux compliance.** `auditwheel show` confirms all 10 Linux wheels are genuinely consistent
  with `manylinux_2_34`; external references are limited to whitelisted libraries.
- **CPU baseline.** `libOpenMS.so` contains AVX2 and AVX-512 instructions, but exclusively inside
  runtime-dispatched Arrow/Parquet kernels (`arrow::internal::unpack32_avx512`, `xsimd::avx2`,
  `parquet::internal::FindMinMaxAvx2`), with CPUID dispatch present. No unconditional AVX use — no
  SIGILL risk on older x86-64 CPUs.
- **Functional behaviour.** A 18-check functional suite (peptide masses, mzML round-trip, gzip-mzML
  reading, isotope distributions, theoretical spectra, NumPy interop, DataFrame export, idXML
  round-trip, parameter handling, ModificationsDB with 3,612 modifications) passes on Linux x86_64.
  The only failures were findings 13 and 10.
- **Locale.** `import pyopenms` no longer changes `LC_NUMERIC` (the 3.5.0 fix holds).
- **Windows packaging.** The wheel bundles Microsoft-signed MSVC runtimes, ships no `zlib1.dll`,
  bundles current zlib 1.3.1, and imports only expected system DLLs plus `python3xx.dll`. The
  desktop installer installs and passes the CLI smoke test.
- **macOS code signing.** Mach-O binaries in the PKG carry real CMS signatures, and the desktop
  deployment target (12.0) is appropriately low.
- **Source tarballs.** `OpenMS-3.5.0.tar.gz` and `OpenMS-3.5.tar.gz` are byte-identical — a benign
  alias, unlike the ARM64 DEB duplicate.

---

## Lab runs

All nine runs used the released packages (`pyopenms==3.5.0`, `openms_package=latest`) with SSH
disabled.

| Run | Platform | Python | Desktop package | Result |
|---|---|---|---|---|
| [35426946121](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35426946121) | windows-2025 | 3.12 | Win64.exe | pass |
| [35426968597](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35426968597) | windows-2025 | 3.14 | — | pass |
| [35426947315](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35426947315) | macos-15 arm64 | 3.12 | macOS-Silicon.pkg | pass |
| [35426951986](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35426951986) | macos-15-intel | 3.12 | macOS-Intel.pkg | pass |
| [35426965287](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35426965287) | macos-15 arm64 | 3.14 | — | pass |
| [35426953674](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35426953674) | ubuntu-24.04 x64 | 3.12 | x86_64.deb | **DEB install failed** (finding 2) |
| [35426958001](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35426958001) | ubuntu-24.04 arm64 | 3.12 | aarch64.deb | **DEB install failed** (finding 2) |
| [35426959561](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35426959561) | ubuntu-22.04 x64 | 3.12 | x86_64.deb | **DEB install failed** (finding 2) |
| [35426963380](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35426963380) | ubuntu-24.04 x64 | 3.14 | — | pass |

The wheel smoke test passed in every run, including on Ubuntu 22.04 (glibc 2.35), confirming the
`manylinux_2_34` floor is satisfiable on the oldest currently supported Ubuntu LTS.

---

## Suggested release gate

Checks that would have caught these findings automatically, cheapest first:

1. **Assert wheel tags.** Fail the wheel workflow if the produced platform tags differ from an
   expected list (catches 1).
2. **Install the DEB in a container that has `libsqlite3-dev`** and run `apt-get install ./*.deb`
   (catches 2, and 3 if the container is the oldest supported distro).
3. **Generate DEB dependencies with `dpkg-shlibdeps`** instead of a static `Depends:` line
   (catches 3).
4. **Assert the release asset set** — exactly one artifact per platform/architecture, with no name
   collisions (catches 4).
5. **Verify signatures after upload**: `signtool verify /pa` and `spctl -a -vv -t install`
   (catches 5).
6. **Diff the bundled dependency set across builders** and fail on version drift or on a bundled
   library older than a threshold (catches 6, 7).
7. **Run `twine check` plus a metadata assertion** for `Requires-Python` and `License-File`
   (catches 8, 9).
8. **Import with `-W error::SyntaxWarning`, compile all `.pyi` files, and compare the public
   namespace against the stubs** on every platform (catches 11, 12, 15, 16, 17).
