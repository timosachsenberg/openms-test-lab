# OpenMS nightly package audit — 2026-09-22

Audit date: 2026-09-22. Target: the current **nightly** packages, not a release.

| Product | Artifact under test |
|---|---|
| Desktop | `OpenMS-3.6.0-pre-nightly-2026-09-21-{Win64.exe, macOS-Silicon.pkg, Debian-Linux-x86_64.deb, Debian-Linux-aarch64.deb}`, folder [`2026.09.22`](https://archive.openms.de/openms/OpenMSInstaller/nightly/2026.09.22/) |
| pyOpenMS | `pyopenms-3.6.0.dev20260922-cp311-abi3-{manylinux_2_34_x86_64, manylinux_2_34_aarch64, macosx_15_0_arm64, win_amd64}.whl` |

Both products are built from OpenMS revision `bb3737c` (`FileInfo --help` reports
`3.6.0-pre-nightly-2026-09-21 Sep 22 2026, 01:37:17, Revision: bb3737c`; the wheel build is
[OpenMS/OpenMS run 35676062677](https://github.com/OpenMS/OpenMS/actions/runs/35676062677) on
`nightly`, head `bb3737cea74ac4aff7adfbda5b12e51032a10793`).

Two methods were combined, as in the [3.5.0 audit](PACKAGE-AUDIT-3.5.0.md):

- **Runtime labs.** The nine runs of this repository's release test matrix with `nightly` for both
  package inputs and SSH disabled (run IDs in [Lab runs](#lab-runs)).
- **Static artifact analysis.** Every nightly artifact was downloaded and inspected directly
  (`dpkg-deb`, `readelf`, `ld.so` tracing, XAR/cpio extraction, Mach-O load commands, `pefile`,
  `auditwheel`, `RECORD`/`METADATA` verification), plus a functional pyOpenMS suite on Linux x86_64.

**Artifact provenance.** The SHA-256 of all four desktop packages downloaded here matches what the
lab runs recorded independently (`fe52d784…` x86_64 DEB, `82e0a90e…` aarch64 DEB, `5ae01d20…`
Win64.exe, `f15c14d5…` macOS-Silicon.pkg).

**One caveat on the wheels.** `pypi.openms.de` was unreachable for the whole audit (finding 1), so
the published nightly wheels could not be fetched. The wheel analysis below was run against the
artifacts of the wheel build that feeds that index — the same commit, the same job, but the CI
artifact rather than the published file. Everything wheel-internal (metadata, `RECORD`, stubs,
bundled libraries, deployment targets, behaviour) therefore holds for the build; what could *not*
be checked is whether the published copy matches it byte for byte.

---

## Summary

| # | Finding | Affects | Severity | vs 3.5.0 |
|---|---|---|---|---|
| 1 | `pypi.openms.de` returns HTTP 504 — no nightly wheel installs anywhere | all wheels | **Blocker** | new |
| 2 | DEB needs glibc 2.38 + Qt6 `t64`, so Ubuntu 22.04 LTS is dropped — over `__isoc23_*` symbols alone | 2 DEBs | **High** | new |
| 3 | `OpenMS-…-Win64.exe` is still unsigned | .exe | **High** | unchanged |
| 4 | macOS floor is inconsistent and undeclared: wheel 15.0, CLI 14.0, bundled Qt stack 15.0 | wheel, .pkg | **High** | partly unchanged |
| 5 | Shipped `maracluster` has RPATH `/usr/lib:/tmp/build_Z0sb/tools/lib` | x86_64 DEB | **High** | new |
| 6 | DEB still vendors 53 third-party libraries into flat `/usr/lib`; OpenSSL there is 3.0.8 (Feb 2023) | 2 DEBs | **High** | reduced |
| 7 | RUNPATHs padded with empty entries make the loader search the current directory | 2 DEBs | Medium | new |
| 8 | Every nightly DEB declares `Version: 3.6.0` | all DEBs | Medium | new |
| 9 | The Thermo bridge needs .NET 8, which is neither shipped nor declared | 2 DEBs | Medium | new |
| 10 | `pyopenms.SysInfo` is still a leaked Linux `struct sysinfo` | wheels | Medium | unchanged |
| 11 | `pyopenms` still exports `ctypes`, `warnings`, `libc`, `c`, … | wheels | Medium | reduced |
| 12 | Every `import pyopenms` still writes to stderr on macOS | macOS wheel | Medium | unchanged |
| 13 | `FeatureMap.to_df()` still returns `ID_filename`, `ID_native_id` | wheels | Medium | unchanged |
| 14 | `to_df()` raises a bare `ModuleNotFoundError` instead of naming the extra | wheels | Low | new |
| 15 | `matplotlib` is still a hard runtime dependency | wheels | Low | reduced |
| 16 | macOS PKG still declares no minimum OS version | .pkg | Low | unchanged |
| 17 | The two DEB architectures ship different content under one version | 2 DEBs | Low | new |
| 18 | macOS PKG ships AppleDouble `._*` sidecar files | .pkg | Low | new |

Finding 1 blocks the nightly wheel channel outright and should be treated as an outage, not a
packaging bug. Findings 2–6 should gate 3.6.0. **Thirteen of the twenty 3.5.0 findings are fixed** —
see [What 3.5.0 fixed](#what-350-fixed).

---

## Blockers

### 1. The nightly wheel index is down: `pypi.openms.de` returns 504

Every request to the PEP 503 index returns *504 Gateway Time-out* from the site's own nginx after
about 60 s:

```
$ curl https://pypi.openms.de/simple/pyopenms/
<html><head><title>504 Gateway Time-out</title></head>
<body><center><h1>504 Gateway Time-out</h1></center>
<hr><center>nginx/1.24.0 (Ubuntu)</center></body></html>
```

The site root (`https://pypi.openms.de/`) answers the same way, so this is the whole service and not
one path. Observed continuously from 06:45 to 07:23 UTC on 2026-09-22 across fourteen probes,
and still failing when this report was written.

It is not a local network artifact. **All nine lab runs failed at the same call**, on GitHub-hosted
Azure runners in three operating systems:

```
File ".../scripts/resolve_nightly.py", line 74, in wheel
  ...
urllib.error.HTTPError: HTTP Error 504: Gateway Time-out
```

Consequences, all of which the labs reproduced:

- `pip install --index-url https://pypi.openms.de/simple pyopenms` cannot work for anyone;
- the labs install no wheel, so `numpy` is absent and the Python smoke test fails with
  `ModuleNotFoundError: No module named 'numpy'`;
- the desktop half of each run still proceeded, which is why this audit has desktop results at all.

`archive.openms.de` — the desktop nightly host, same nginx version — was reachable throughout,
so only the wheel channel is affected.

*Fix:* this is a service outage; restore the index backend. Worth adding an uptime check, because
nothing in the publishing pipeline notices that the channel is unreachable.

---

## High

### 2. The nightly DEB drops Ubuntu 22.04 LTS, and only `__isoc23_*` symbols make it necessary

The DEB declares `libc6 (>= 2.38)` plus hard dependencies on the Qt6 `t64` packages. On Ubuntu
22.04 (glibc 2.35, Qt6 6.2) `apt` refuses it outright — reproduced in lab run
[35696793233](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35696793233):

```
The following packages have unmet dependencies:
 openms : Depends: libc6 (>= 2.38) but 2.35-0ubuntu3.14 is to be installed
          Depends: libqt6core6t64 (>= 6.4.0) but it is not installable
          …
          Depends: libstdc++6 (>= 13.1) but 12.3.0-1ubuntu1~22.04.3 is to be installed
E: Unable to correct problems, you have held broken packages.
```

The declaration is *honest* — `readelf -V` over all 222 ELF files finds 21 that genuinely reference
`GLIBC_2.38` — which is itself the fix for 3.5.0's finding 3, where the declared floor was six
releases below what the binaries needed. The problem is what creates that requirement. There are
only eight distinct `GLIBC_2.38` symbols in the entire package:

| Symbol | Files referencing it |
|---|---|
| `__isoc23_strtol` | 20 |
| `__isoc23_sscanf` | 8 |
| `__isoc23_fscanf` | 4 |
| `__isoc23_strtoul` | 4 |
| `__isoc23_strtoll` | 3 |
| `__isoc23_strtoull` | 3 |
| `fmod` | 2 |
| `fmodf` | 1 |

Six of the eight are the `__isoc23_*` redirects glibc 2.38 introduced: when C code is compiled in
C23 mode, `strtol` and friends bind to a new symbol version. Nothing in OpenMS asks for a C23
library feature — the build container's compiler default does. `fmod`/`fmodf@GLIBC_2.38` come from
the same place (new correctly-rounded versions), and appear only in `libCbc` and `libgfortran`, both
contrib builds.

So the dependency is correct but the requirement is accidental: Ubuntu 22.04, supported until April
2027, loses OpenMS to a compiler default. The older LTS is also exactly what row 8 of the release
test matrix exists to cover.

*Fix:* build the C parts with `-std=gnu17` (or build in a container with an older glibc) and
re-measure; keep `dpkg-shlibdeps` deriving the floor either way. If dropping 22.04 is intended,
say so in the release notes and retire matrix row 8 — right now the matrix asserts a floor the
package no longer meets.

### 3. The Windows installer is still unsigned

`OpenMS-3.6.0-pre-nightly-2026-09-21-Win64.exe` has an empty PE Security directory
(`VirtualAddress=0, Size=0`), i.e. no Authenticode signature, so every user still gets the
SmartScreen *"Windows protected your PC"* interstitial. Unchanged from 3.5.0.

The installer is otherwise built with ASLR and DEP (`DllCharacteristics=0x8540`), and its version
resource correctly carries `3.6.0-pre-nightly-2026-09-21`.

**macOS is now fixed, which is what makes this stand out.** The nightly `.pkg` carries a real
`<signature style="RSA">` whose chain is

```
Developer ID Installer: OpenMS Inc. (C64UCGJ5PL)
  → Developer ID Certification Authority (G2, Apple Inc.)
    → Apple Root CA          (valid 2025-01-16 … 2030-01-17)
```

plus an `<x-signature style="CMS">`. The same signing work has simply not been done for Windows.

*Fix:* `signtool` with the organization's code-signing certificate. (The XAR carries no stapled
notarization ticket, so whether the `.pkg` is notarized as well as signed still needs checking on a
real macOS host with `spctl`/`stapler validate`.)

### 4. The macOS floor is inconsistent across the two products and undeclared in the installer

Three different minimums coexist in one nightly:

| Object | `LC_BUILD_VERSION minos` | Count |
|---|---|---|
| pyOpenMS wheel (`macosx_15_0_arm64`) | **15.0** | 136 of 137 Mach-O objects |
| Desktop: OpenMS's own binaries and libraries | **14.0** | 223 objects, incl. all 154 tools and `TOPPView` |
| Desktop: bundled Qt/Homebrew stack | **15.0** | 18 objects |

The wheel tag is honest and the wheel side of 3.5.0's finding 1 is resolved only in the sense that
the two conflicting settings now agree — both `src/pyOpenMS/pyproject.toml:266` and
`.github/workflows/pyopenms-wheels-cibuildwheel.yml:480` say `15.0`, and
`tools/ci/check_macos_wheel_target.py` now verifies the wheel against its tag. The *floor itself*
was never lowered, so macOS 13 and 14 still cannot install pyOpenMS.

The desktop package is the new problem. `TOPPView` is built for macOS 14.0 but links
`QtSvg.framework`, which is built for 15.0, as are `libglib-2.0`, `libharfbuzz`, `libfreetype`,
`libicuuc`, `libpng16`, `libpcre2-*` and `libzstd` — Homebrew bottles for Sequoia, copied in
verbatim. On macOS 14 `dyld` will refuse to load them, so the GUI cannot start. The CLI tools are
unaffected: `libOpenMS.dylib` links no Qt at all (`libcurl`, `libxerces-c`, Boost, Arrow, CoinOR,
`libsqlite3` and system frameworks only), so `FileInfo` and friends really do run on 14.

And nothing declares any of this: the installer's `Distribution` file has no
`<allowed-os-versions>`, no `<volume-check>` and no `<installation-check>` (finding 16), so on
macOS 14 the package installs cleanly and then the GUI fails at launch.

*Fix:* build the bundled dependencies against the same deployment target as OpenMS itself, and add
`<allowed-os-versions><os-version min="…"/></allowed-os-versions>` so the installer refuses
early. Separately, decide whether the wheel floor of 15.0 is intended; if it is not, the single
`MACOSX_DEPLOYMENT_TARGET` value now has one place to change.

### 5. A shipped third-party binary searches a world-writable `/tmp` path for libraries

`usr/share/OpenMS/THIRDPARTY/MaRaCluster/maracluster` in the x86_64 DEB carries

```
RPATH = /usr/lib:/tmp/build_Z0sb/tools/lib
```

a leftover from the machine it was built on. `/tmp/build_Z0sb` does not exist on a user's system,
`/tmp` is world-writable, and RPATH is searched **before** the system library directories. Traced
with `LD_DEBUG=libs`:

```
search path=/usr/lib                                      (system search path)
  trying file=/usr/lib/libpthread.so.0
search path=/tmp/build_Z0sb/tools/lib/glibc-hwcaps/x86-64-v4:…:/tmp/build_Z0sb/tools/lib   (RPATH)
  trying file=/tmp/build_Z0sb/tools/lib/libpthread.so.0
…
```

Every one of maracluster's dependencies — `libpthread.so.0`, `libstdc++.so.6`, `libm.so.6`,
`libgomp.so.1`, `libgcc_s.so.1`, `libc.so.6` — lives in `/usr/lib/x86_64-linux-gnu`, not `/usr/lib`,
so each lookup falls through to the `/tmp` path before reaching the real one. Any local user can
create `/tmp/build_Z0sb/tools/lib/libgomp.so.1` and have it loaded into another user's
`maracluster` process (CWE-426, untrusted search path).

*Fix:* strip the RPATH from vendored third-party binaries at packaging time (`patchelf
--remove-rpath`, or `chrpath -d`), and add a packaging check that rejects any RPATH/RUNPATH outside
`$ORIGIN`.

### 6. The DEB still vendors 53 third-party libraries into flat `/usr/lib`, and its OpenSSL is from 2023

`/usr/lib` holds 89 entries: 5 OpenMS libraries, 53 third-party libraries (52 on aarch64) and 30
version symlinks, all under their standard SONAMEs — `libcrypto.so.3`, `libssl.so.3`, `libz.so.1`,
`libcurl.so.4`, `libbz2.so.1.0`, `liblz4.so.1`, `libzstd.so.1`, `libsnappy.so.1`, `libre2.so.11`,
`libbrotli*`, `libgfortran.so.5`, `liblapack.so.3`, `libopenblas.so.0`, `libsqlite3.so`,
`libxerces-c-3.3.so`, `libthrift`, `libarrow*`, `libaws-*`, the CoinOR set, and so on.

The set is much healthier than 3.5.0's: **`libresolv.so.2` — a glibc component — is gone**, as are
the GnuTLS/Kerberos/LDAP/SASL/SSH/RTMP stack and `libcurl-gnutls`, and the versions that were
called out are current:

| Library | 3.5.0 | nightly |
|---|---|---|
| zlib | 1.2.11 (2017) | **1.3.2** |
| curl | `libcurl-gnutls.so.4` | **libcurl/8.20.0** |
| Xerces-C | 3.2 | **3.3** |
| **OpenSSL** | **3.0.2** | **3.0.8 — still 2023** |

`libcrypto.so.3` identifies itself as `OpenSSL 3.0.8 7 Feb 2023`. That is three and a half years
old and below every 3.0.x security release since, including the 3.0.21 fix level the 3.5.0 audit
cited for CVE-2026-45447. Note the wheels do *not* share this problem — they bundle OpenSSL 3.5.5
(Linux) and 3.6.4 (macOS), both current — so the DEB is simply built against a much older contrib.

The placement is still the structural issue: these are private dependencies in a directory the
distribution owns, reached through `RUNPATH $ORIGIN/../lib/` on every OpenMS binary.

*Fix:* install private dependencies into `/usr/lib/openms/`, and rebuild the DEB's contrib against
the same OpenSSL the wheels already use.

---

## Medium

### 7. Empty RUNPATH entries make the loader search the current working directory

Two libraries carry a RUNPATH padded with dozens of empty entries — the signature of an in-place
RPATH rewrite that pads rather than truncates:

| File | RUNPATH |
|---|---|
| `usr/lib/libOpenSwathAlgo.so` (both arches) | `$ORIGIN/../lib/` + 93 empty entries |
| `usr/lib/libopenms_thermo_bridge.so` (aarch64) | same |

An empty path element resolves to the current directory. `LD_DEBUG=libs` on the shipped file:

```
search path=/tmp/rp-test/./../lib:glibc-hwcaps/x86-64-v4:glibc-hwcaps/x86-64-v3:…   (RUNPATH)
  trying file=/tmp/rp-test/./../lib/libstdc++.so.6
  trying file=glibc-hwcaps/x86-64-v4/libstdc++.so.6      ← relative to $PWD
  trying file=libstdc++.so.6                             ← relative to $PWD
  trying file=/lib/x86_64-linux-gnu/libstdc++.so.6       ← only now the real one
```

The CWD lookups precede the system path, so a `libstdc++.so.6` dropped in a shared working
directory would win.

**Reachability is limited, and worth stating plainly:** in the normal load order nothing hits this.
A TOPP tool loads `libOpenMS.so` first, which brings in `libstdc++`, `libm`, `libgcc_s` and `libc`
before `libOpenSwathAlgo` is processed, so its dependencies are already resolved — traced on the
real chain, no CWD lookup occurs. The exposure is a program that loads `libOpenSwathAlgo.so`
first, e.g. by `dlopen`. This is a latent defect and a sign the RPATH-rewriting step is emitting
malformed entries, rather than an exploitable path in the shipped tools.

*Fix:* rewrite RUNPATHs with `patchelf --set-rpath` instead of padding, and reject empty entries in
the same packaging check as finding 5.

### 8. Every nightly DEB declares `Version: 3.6.0`

`dpkg-deb -f` reports `Package: openms`, `Version: 3.6.0` for a package whose file name, binaries
and Windows version resource all say `3.6.0-pre-nightly-2026-09-21`. `FileInfo --help` from that
very DEB prints `Version: 3.6.0-pre-nightly-2026-09-21 … Revision: bb3737c`, so the information
exists at build time and is simply not carried into the control file.

Consequences: `apt`/`dpkg` cannot tell two nightlies apart, cannot upgrade one to the next, and
will not distinguish any of them from the eventual 3.6.0 release. This is the same class of problem
as 3.5.0's finding 4 (two different builds under one version), but systematic rather than
accidental.

*Fix:* set `CPACK_DEBIAN_PACKAGE_VERSION` to a Debian-comparable pre-release version, e.g.
`3.6.0~nightly20260921`, which sorts before `3.6.0`.

### 9. The Thermo RAW bridge needs .NET 8, which is neither shipped nor declared

`ThermoWrapperManaged.runtimeconfig.json` requests `Microsoft.NETCore.App` 8.0 with
`rollForward: Major`, but neither DEB ships a .NET runtime — no `libhostfxr`, no `libcoreclr`, no
`System.Private.CoreLib.dll` — and `Depends:` names no `dotnet-runtime-8.0`. On a clean Ubuntu
24.04 the managed half of the bridge cannot start.

*Fix:* declare the runtime dependency, or ship a self-contained build of the managed assembly.

### 10. `pyopenms.SysInfo` is still a leaked Linux `struct sysinfo`

Unchanged from 3.5.0. Verified on the nightly Linux wheel:

```
SysInfo from pyopenms._sysinfo, getProcessMemoryConsumption=NO
```

It is the `ctypes.Structure` mirroring `sysinfo(2)`, not OpenMS's `SysInfo`, and because
`_sysinfo.py` defines it only under `sys.platform.startswith("linux")` it is the **one** name by
which the public API differs between platforms — the stub comparison across all four wheels finds
exactly one symmetric difference, `SysInfo` (692 classes on Linux, 691 on macOS and Windows).

### 11. `pyopenms` still pollutes its public namespace

Reduced but not gone. Still public on the nightly wheel:

```
ctypes, warnings, libc, c, free_mem, default_openms_data_path, env_openms_data_path
```

`numpy`, `np`, `print_function`, `streampos` and `common_meta_value_types` have disappeared since
3.5.0. The seven that remain are also the entire residue of 3.5.0's finding 15 — see
[What 3.5.0 fixed](#what-350-fixed).

### 12. Every `import pyopenms` still writes to stderr on macOS

`pyopenms/_sysinfo.py` in the macOS wheel still ends with

```python
else:
    sys.stderr.write("Determination of memory status is not supported on this \n"
                     " platform, measuring for memoryleaks will never fail\n")
```

so macOS falls into that branch on every import. The `win32` branch is still dead code depending on
`pywin32`, which pyOpenMS does not require. Unchanged from 3.5.0.

### 13. `FeatureMap.to_df()` still returns non-snake_case columns

```
['peptide_sequence', 'peptide_score', 'ID_filename', 'ID_native_id', 'charge', 'rt', 'mz',
 'rt_start', 'rt_end', 'mz_start', 'mz_end', 'quality', 'intensity']
```

`ID_filename` and `ID_native_id` were missed by the 3.5.0 rename and are still missed.
`MSSpectrum.to_df()` is correct (`['mz', 'intensity', 'rt', 'ms_level', 'native_id']`).
`get_df()` now warns `get_df() is deprecated. Use to_df() instead.` — the rename went ahead without
finishing the column names.

---

## Low

### 14. `to_df()` fails with a bare `ModuleNotFoundError` when the extra is not installed

Making `pandas` an extra (below) is right, but the failure mode is unhelpful:

```
>>> spectrum.to_df()
ModuleNotFoundError: No module named 'pandas'
```

Nothing tells the user that `pip install pyopenms[dataframes]` is the answer.

*Fix:* catch the import and raise with the extra's name.

### 15. `matplotlib` is still a hard runtime dependency

`Requires-Dist: numpy>=2.0, matplotlib>=3.5, nanobind-backend>=1.0` plus
`pandas>=3; extra == "dataframes"` and `pyarrow; extra == "arrow"`. `pandas` moving to an extra is
the fix 3.5.0's finding 20 asked for; `matplotlib` — needed only by `plotting` — did not move with
it, so headless and container installs still pull it in.

### 16. The macOS PKG still declares no minimum OS version

The `Distribution` file has no `<allowed-os-versions>`, `<volume-check>` or `<installation-check>`.
Unchanged from 3.5.0, and now consequential because of finding 4.

### 17. The two DEB architectures ship different content under one version

| | x86_64 | aarch64 |
|---|---|---|
| THIRDPARTY tools | Comet, LuciPHOr2, MSFragger, MSGFPlus, **MaRaCluster**, Percolator, Sage, **SpectraST**, ThermoRawFileParser, **XTandem** | Comet, LuciPHOr2, MSFragger, MSGFPlus, Percolator, Sage, ThermoRawFileParser |
| Thermo bridge managed assemblies | `/usr/share/OpenMS/openms_thermo_bridge/managed/` | `/usr/lib/openms_thermo_bridge/managed/` |
| `libnethost.so` | shipped, and linked by the bridge | not shipped, and not linked |
| Bridge headers + CMake config | not shipped | shipped |

The missing ARM builds of MaRaCluster, SpectraST and XTandem are expected — those are upstream
binaries with no ARM release. The bridge split is not: the same payload lands in two different
prefixes. Both happen to resolve, by different routes —
`OpenMS/src/openms/source/FORMAT/ThermoRawFile.cpp:97` looks in
`<OpenMS share dir>/openms_thermo_bridge/managed`, which matches x86_64, and the bridge's own
fallback looks next to its shared library, which matches aarch64 — so this is a consistency and
maintainability problem rather than a broken build. The architecture-dependent capability list
should still be documented.

### 18. The macOS PKG ships AppleDouble sidecar files

The `MSFragger` component's 11 entries include `._README.MD` (9,975 bytes) and `._License.txt`
(9,982 bytes) beside the 756-byte `README.MD` and 8,545-byte `License.txt` — AppleDouble resource
forks, larger than the files they describe, produced by archiving on a filesystem without native
extended-attribute support.

*Fix:* `COPYFILE_DISABLE=1` (or `--no-xattrs`) when building the payloads.

---

## What 3.5.0 fixed

Thirteen of the twenty findings in the [3.5.0 audit](PACKAGE-AUDIT-3.5.0.md) are resolved in the
nightly. Recorded so the next audit does not re-litigate them.

| 3.5.0 finding | State | Evidence |
|---|---|---|
| 2. DEB fails to install when `libsqlite3-dev` is present | **Fixed** | No `/usr/include/sqlite3.h`; `/usr/include` holds only `OpenMS/`. The DEB installs cleanly on ubuntu-24.04 x86_64 and arm64 (`Setting up openms (3.6.0) …`) |
| 3. `libc6 (>= 2.28)` understated by six releases | **Fixed** | Now `libc6 (>= 2.38)`, derived by `dpkg-shlibdeps`, and matching the 21 binaries that reference `GLIBC_2.38`. (It over-corrects into finding 2) |
| 4. Two different ARM64 DEBs under one name | **Fixed** | Each of the last ten nightly folders holds exactly four files, one per platform; no `arm64`/`aarch64` duplicate |
| 5. Neither desktop installer signed | **Half fixed** | `.pkg` signed with a Developer ID Installer chain; `.exe` still unsigned (finding 3) |
| 6. 54 vendored libraries, incl. `libresolv.so.2`, OpenSSL 3.0.2, zlib 1.2.11 | **Partly fixed** | `libresolv` and the GnuTLS/Kerberos stack gone; zlib 1.3.2, curl 8.20.0, Xerces 3.3. Still flat in `/usr/lib`, still OpenSSL 3.0.8 (finding 6) |
| 7. Three Qt and OpenSSL versions; Linux wheels on Qt 6.6.2 (CVE-2024-39936) | **Fixed** | **No Qt is bundled in any wheel.** OpenSSL is 3.5.5 in the Linux wheels and 3.6.4 in the macOS wheel; the Windows wheel uses Schannel |
| 8. No `Requires-Python` | **Fixed** | `Requires-Python: >=3.11` in all four wheels |
| 9. No license file in any wheel | **Fixed** | `dist-info/LICENSE` plus `share/OpenMS/LICENSES/OpenMS-BSD-3-Clause.txt`; `License: BSD-3-Clause` is now an SPDX id, not a URL |
| 13. `IdXMLFile.store/load` rejected plain lists | **Fixed** | Both work again, with `DeprecationWarning: Passing a Python list for peptide_ids is deprecated since pyOpenMS 3.5` |
| 15. 23 public names without stub declarations | **Fixed** | 4 remain (`annotations`, `c`, `importlib`, `warnings`) and all four are finding 11's leaked imports. `PeakMap` and `PeakSpectrum` are declared |
| 16. Invalid escape sequences in `.pyi` stubs | **Fixed** | All 44 stubs in all four wheels parse as UTF-8 Python and compile with warnings as errors |
| 17. Class→submodule partitioning differs per platform | **Fixed** | 13 domain-named submodules (`_pyopenms_analysis`, `_pyopenms_chemistry`, …) with **identical class membership on all four platforms**; the stub files differ only in line endings |
| 19. macOS PKG offers an MSFragger choice with an empty payload | **Fixed** | The component now installs `README.MD` and `License.txt` explaining how to obtain MSFragger |
| 20. `pandas` + `matplotlib` hard dependencies | **Partly fixed** | `pandas>=3` is now `extra == "dataframes"`; `matplotlib` is still required (finding 15) |
| 1. macOS wheels require macOS 15 | **Not fixed** | Still `macosx_15_0_arm64`, 136 of 137 objects at `minos 15.0`. The *inconsistency* is resolved — `pyproject.toml` and the workflow now both say 15.0, and `tools/ci/check_macos_wheel_target.py` verifies it — but the floor was standardized upward rather than lowered (finding 4). No Intel wheel is built at all now |
| 10, 11, 12, 14, 18 | **Not fixed** | Findings 10, 11, 12, 13 and 16 above |

---

## What was verified as sound

- **Wheel integrity and metadata.** All four wheels have a complete `RECORD` — no unrecorded files,
  no phantom entries, every hash and size matching. `py.typed` present. `pip check` clean after
  installation.
- **manylinux compliance.** `auditwheel show` confirms both Linux wheels are consistent with
  `manylinux_2_34`; external references are limited to whitelisted libraries.
- **Wheel dependency resolution.** `nanobind-backend`, the new hard dependency, exists on PyPI and
  resolves. The Windows wheel's `METADATA` uses CRLF line endings, which the email parser strips —
  every `Requires-Dist` parses correctly, so this is cosmetic.
- **Desktop startup.** `FileInfo --help` exits 0 on all four platforms in the lab runs, and the
  installed package is located through the package manager's own file list on macOS and Linux.
- **macOS code signing.** All 242 Mach-O objects in the `.pkg` carry `LC_CODE_SIGNATURE`.
- **Windows wheel packaging.** No `zlib1.dll`; the bundled DLLs are delvewheel-mangled
  (`zlib-7ef9…dll`, `OpenMS-7348…dll`, `libcurl-7eec…dll`) alongside Microsoft's `msvcp140` and
  `vcomp140`.
- **Functional behaviour.** 11 of 13 checks pass on the nightly Linux x86_64 wheel — peptide mass
  (`PEPTIDE` = 799.35997), NumPy → `MSSpectrum` → mzML → NumPy round trip, gzip-mzML reading,
  isotope distributions, theoretical spectra, `ModificationsDB` (3,610 modifications), parameter
  handling, idXML round trip with plain lists. The two failures are the `pandas` extra not being
  installed (finding 14), not defects. `import pyopenms` emits nothing on stderr on Linux and
  raises no warning under `-W error`.
- **Locale.** `import pyopenms` still does not change `LC_NUMERIC`.
- **Nightly publishing hygiene.** Each of the last ten dated folders holds exactly one package per
  platform; the resolver's newest-build tie-break was not needed.

---

## Lab runs

All nine runs of the [release test matrix](README.md#release-test-matrix) used `nightly` for both
package inputs with `debug: false`, dispatched from `claude/sweet-hypatia-wjwrqo`.

| Run | Platform | Python | Desktop package | Result |
|---|---|---|---|---|
| [35696771564](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35696771564) | windows-2025 | 3.12 | Win64.exe — installed, CLI smoke passed | **wheel index 504** (finding 1) |
| [35696774536](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35696774536) | windows-2025 | 3.14 | — | **wheel index 504** |
| [35696777151](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35696777151) | macos-15 arm64 | 3.12 | macOS-Silicon.pkg — installed, `FileInfo --help` exit 0 | **wheel index 504** |
| [35696779434](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35696779434) | macos-15-intel | 3.12 | — | **wheel index 504** |
| [35696781276](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35696781276) | macos-15 arm64 | 3.14 | — | **wheel index 504** |
| [35696787652](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35696787652) | ubuntu-24.04 x64 | 3.12 | x86_64.deb — **installed cleanly** (3.5.0 finding 2 fixed) | **wheel index 504** |
| [35696790381](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35696790381) | ubuntu-24.04 arm64 | 3.12 | aarch64.deb — **installed cleanly** | **wheel index 504** |
| [35696793233](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35696793233) | ubuntu-22.04 x64 | 3.12 | x86_64.deb — **dependency failure** (finding 2) | **wheel index 504** |
| [35696795407](https://github.com/timosachsenberg/openms-test-lab/actions/runs/35696795407) | ubuntu-24.04 x64 | 3.14 | — | **wheel index 504** |

Every run is marked failed, and all nine failed for the same reason: the wheel index. The desktop
half of each run still ran, which is where the DEB and PKG results above come from.

The macOS Intel run was dispatched with `pyopenms_spec: nightly` deliberately, to test the README's
claim that no Intel nightly exists. The outage means it could not answer that question — but the
wheel build publishes no `macosx_*_x86_64` artifact at all, so the claim holds by construction.

*Re-run these once `pypi.openms.de` is back:* the entire pyOpenMS runtime half of this audit —
installation on each interpreter and platform, the stub parse on macOS, the loaded-library capture —
is still outstanding, and the nine runs are the way to get it.
