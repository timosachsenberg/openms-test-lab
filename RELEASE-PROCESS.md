# Making an OpenMS release

[RELEASE-READINESS.md](RELEASE-READINESS.md) decides *whether* a revision may become a release.
This document says *how* to make the release. It runs from preparing `develop` to cleaning up
afterwards, and names the readiness checks that gate each step. It describes the machinery as
it worked for 3.6.0 on 2026-09-30. [Known gaps](#known-gaps) lists what has never run or is
known to be broken.

An agent follows it from top to bottom. Steps marked **Maintainer** publish something or need
rights an agent does not have: pushing a tag, publishing to PyPI, readthedocs administration,
opening upstream Bioconda PRs, sending the announcement. An agent prepares these steps and says
what to run. It carries one out only when a maintainer asks in writing for that step. Everything
else an agent may do on a branch and report. The [rules for agents](AGENTS.md#rules) apply
throughout.

Facts below cite OpenMS/OpenMS files as of `develop` ec49b87 (2026-09-30).

## At a glance

| Stage | What happens | Who | Gate |
| --- | --- | --- | --- |
| [1. Prepare](#1-prepare-develop) | Version numbers, CHANGELOG, docs versions on `develop` | PRs | A3, D1, D5, E1–E8 |
| [2. Qualify](#2-qualify-the-candidate) | Readiness procedure on the nightly of the candidate commit | Agent | Verdict READY FOR RC |
| [3. Release candidate](#3-release-candidate-optional-untested) | Optional, and broken today | Maintainer | G1–G5 |
| [4. Tag](#4-tag-the-release) | Annotated `v<version>` on the qualified commit | **Maintainer** | Step 2 |
| [5. Tag build](#5-what-the-tag-starts-and-how-to-check-it) | Installers, GitHub release, docs, wheels to the archive, containers, next-version PR; then the Windows installer signed by hand | Automatic, then **Maintainer** | G1–G5, G9, G10 |
| [6. PyPI](#6-publish-pyopenms-to-pypi) | Dispatch the wheel workflow with `upload-to-pypi` | **Maintainer** | G6 |
| [7. Documentation](#7-documentation) | readthedocs version, version switcher | **Maintainer** and a PR | G8, E10 |
| [8. Conda](#8-bioconda) | Bioconda: `openms-meta` first, then `pyopenms` | **Maintainer** (upstream PR) | G7 |
| [9. Announce](#9-website-and-announcement) | Website PR, mailing lists | **Maintainer** | G10 |
| [10. After the release](#10-after-the-release) | Next-version PR, nightly recipe, release report, follow-ups | PRs, agent | — |

## 1. Prepare develop

**Version numbers.** `develop` carries the upcoming version for the whole cycle:
- **The automatic bump.** Pushing the previous release's tag started `update_version_numbers.yml`. It runs `tools/update_version_numbers.sh <major> <minor+1> 0` and opens a PR titled *"[GHA] Updated OpenMS package version numbers to X.Y.Z"* (for 3.7.0: OpenMS/OpenMS#10349).
- **What the script covers:** `CMakeLists.txt` (`OPENMS_PACKAGE_VERSION_MAJOR/MINOR/PATCH`), `VersionInfo_test.cpp`, `vcpkg.json`, the test INIs and TOPPAS files, and a new CHANGELOG heading `OpenMS X.Y.Z (under development)`.
- **What is left by hand.** Make sure that PR is merged. Then update the rest by PR:

| File | Field | Value |
| --- | --- | --- |
| `doc/openms/docs/conf.py` | `version`, `release` | `X.Y.Z` |
| `doc/pyopenms/docs/source/conf.py` | `version` | `X.Y.Z` |
| `doc/pyopenms/docs/source/_static/switcher.json` | new entry; the `nightly` entry | `X.Y.Z` → `https://pyopenms.readthedocs.io/en/vX.Y.Z/` (the link works after [step 7](#7-documentation)); nightly → the next `…dev` version |
| `src/pyOpenMS/pyproject.toml` | `version` | `X.Y.Z` (wheel builds overwrite it from CMake, but A3 compares it) |
| `src/tests/package_layers/CMakeLists.txt` | `OPENMS_PACKAGE_VERSION` | `X.Y.Z` |

Every page of the pyOpenMS docs reads `switcher.json` from `develop`
(`conf.py`, `json_url`), so one entry there serves all versions.

**The CHANGELOG** feeds the release notes: `release.yml`, step *Create Change Log*, cuts out
the section under the `OpenMS X.Y.Z` heading. Before the tag:
- Date the heading, e.g. `(Released September 2026)`.
- Add a short introduction and a *Known issues:* list. The release notes move *Known issues* up front, and trim the rest when it exceeds GitHub's 125,000-character limit (OpenMS/OpenMS#10355).
- Announce every removed tool and every breaking pyOpenMS change, with the new call (checks D1, D5, E2).
- `tools/changelog_helper.sh` compares the TOPP binaries of two releases and lists new and removed tools and INI parameter changes.
- Check `AUTHORS` for new contributors.

For 3.6.0, the commit that dated the heading, 5d5cbff (OpenMS/OpenMS#10348), is also the commit
that was tagged.

**Gate:**
```bash
python3 scripts/release-docs-audit.py --openms <checkout of the candidate> --base v<previous>
```
It covers A3 (`VERSION-STRINGS`) and E1–E8. `CHANGELOG-LINT` fails while the heading still says
"under development". A3's switcher part is checked by hand.

## 2. Qualify the candidate

- **Choose the commit.** There are no release branches since 3.6.0: the release is tagged on
  `develop`. Agree on the candidate commit and keep unrelated merges out of `develop` until it
  is tagged, or name the exact commit in the report.
- **Get packages of it.** `update_nightly.yml` runs daily at 01:07 UTC, or when dispatched
  (input `force` resets `nightly` when it cannot fast-forward). It moves `nightly` to `develop`
  and builds packages of that commit:
  - installers under `archive.openms.de/openms/OpenMSInstaller/nightly/`;
  - wheels on `pypi.openms.de`;
  - Bioconda packages on the anaconda.org channel `openms`;
  - containers tagged `latest`.
- **Run the readiness procedure.** Follow [RELEASE-READINESS.md](RELEASE-READINESS.md) on the
  nightly whose revision (A2) is the candidate. Write the report
  `readiness/<date>-X.Y.Z-nightly.md`.
- **Proceed only on READY FOR RC.** Every blocking failure must be fixed, or waived by a
  maintainer in writing; the report links the waiver. A failure that ships instead goes into
  the CHANGELOG's *Known issues*.

For 3.6.0, every nightly report from 2026-09-24 to 2026-09-30 ended NOT READY. The maintainer
released with written waivers for Sage's SQLite (F6) and the F8 license gaps, and with the
remaining problems listed as *Known issues* in the CHANGELOG. The waivers are in
[lab PR #5](https://github.com/timosachsenberg/openms-test-lab/pull/5), as is the report on
the release's own files, `readiness/2026-09-30-3.6.0-release.md`.

## 3. Release candidate (optional, untested)

A tag `vX.Y.Z-rcN` matches the `v[0-9]*` trigger of every release workflow. No release
candidate has been built since the move to `v` tags. The workflows say it would go like this:

- **`release.yml`** builds with version type `rcN`. It deploys to
  `OpenMSInstaller/rcN/X.Y.Z/` and `Documentation/rcN/X.Y.Z/` without `--mkpath`, and
  archive.openms.de has no `rcN/` directories. The deploy therefore likely fails, and
  everything after it is skipped. By design, an RC gets no GitHub release and no website PR.
- **Package names.** `CMakeLists.txt` recognises only an exact `vX.Y.Z` tag as a release, so
  RC packages are named `X.Y.Z-pre-HEAD-<date>`. G2 cannot pass on them.
- **Wheels.** The wheel version comes from `CMakeLists.txt`, not from the tag, so RC wheels
  are versioned plain `X.Y.Z`. They land in `archive.openms.de/openms/pyopenms/release/X.Y.Z/`,
  the folder of the final release. A dispatch with `upload-to-pypi` on the RC tag would publish
  the RC to PyPI as the final version, which can never be replaced. **Never do that.**
- **Containers** are published as `X.Y.Z-rcN`.
- **`update_version_numbers.yml`** fails on the tag, because it accepts only `vX.Y[.Z]`. That
  is harmless.

Until these are fixed, qualify on the nightly of the candidate commit ([step 2](#2-qualify-the-candidate)).
Check the G items on the final tag build before announcing anything ([step 5](#5-what-the-tag-starts-and-how-to-check-it)).
That is how 3.6.0 was released.

## 4. Tag the release

**Maintainer.** Tag the commit the readiness report names. It must contain the dated CHANGELOG
heading.

```bash
git fetch origin develop
git tag -a vX.Y.Z <commit> -m "OpenMS X.Y.Z"
git push origin vX.Y.Z
```

Only `vX.Y.Z` with no suffix counts as a release: `.github/actions/version/action.yml` maps
`^v\d+\.\d+\.\d+$` to type `release`. **Never move or delete a published tag.** A defect found
after the tag is fixed in the next version (`X.Y.Z+1`). An infrastructure failure (a runner, an
upload) is retried by re-running the failed jobs, or by dispatching `release.yml` on the tag ref.

## 5. What the tag starts, and how to check it

| Workflow in OpenMS/OpenMS | What it does | 3.6.0 |
| --- | --- | --- |
| `release.yml` | Builds and tests (ctest) Windows, macOS, Linux x86_64 and aarch64. Signs and notarizes the macOS `.pkg`. The Windows `.exe` comes out **unsigned**: a maintainer signs it by hand (see below). Uploads installers to `archive.openms.de/openms/OpenMSInstaller/release/X.Y.Z/` and the Doxygen docs to `Documentation/release/X.Y.Z/`, and moves both `latest` symlinks. Publishes the GitHub release *Release X.Y.Z* with the installers and `OpenMS-X.Y.Z.tar.gz`, notes from the CHANGELOG, marked latest. Opens a PR in OpenMS/OpenMS-website with the announcement | run 36689531481, 34 min |
| `pyopenms-wheels-cibuildwheel.yml` | Builds and tests the four wheels and uploads them to `archive.openms.de/openms/pyopenms/release/X.Y.Z/`. **Not to PyPI**: that is [step 6](#6-publish-pyopenms-to-pypi) | run 36689531521 |
| `containerdeploy.yml` | Publishes `ghcr.io/openms/openms-library`, `openms-tools`, `openms-executables` and `openms-tools-thirdparty` (plus `-sif` images), tagged `X.Y.Z` | published as `v3.6.0`; the name is fixed since OpenMS/OpenMS#10355 |
| `update_version_numbers.yml` | Opens the PR that bumps `develop` to `X.(Y+1).0` | OpenMS/OpenMS#10349 |

Check before [step 6](#6-publish-pyopenms-to-pypi) and before announcing:

- **G1–G4:** the runs are green; the archive folders, the GitHub release and its assets exist;
  `FileInfo --help` says `Version: X.Y.Z`; the tarball is named `OpenMS-X.Y.Z.tar.gz`.
- **G5:** run the release matrix with `openms_package=vX.Y.Z` (the labs resolve a GitHub release
  by its tag) and `pyopenms_spec=<wheel URL from the archive folder>`. Then run *Release
  readiness* with the same two values.
- **G9:** the container tags exist. To fix a wrongly named tag, copy it rather than rebuild,
  so both names carry the same image: run
  `docker buildx imagetools create --tag ghcr.io/openms/<image>:X.Y.Z ghcr.io/openms/<image>:<wrong tag>`
  for each image. That needs write access to the `ghcr.io/openms` packages.
- **G10, Maintainer:** sign the Windows installer by hand, and replace both copies with the
  signed file: the asset of the GitHub release and the file in
  `OpenMSInstaller/release/X.Y.Z/`. The maintainers decided this on 2026-09-27; CI has no
  Windows certificate. Until the copies are replaced, users download the unsigned file:
  `openms.de/download/` redirects to the GitHub release.
- **The GitHub release notes:** open the release page and check that the notes are complete
  and that their download link works. Replace the body by hand if not; for 3.6.0 it was cut
  off at GitHub's length limit, which OpenMS/OpenMS#10355 addresses for later releases.

## 6. Publish pyOpenMS to PyPI

**Maintainer**, after G5 passed for the wheels:

```bash
gh workflow run pyopenms-wheels-cibuildwheel.yml -R OpenMS/OpenMS --ref vX.Y.Z -f upload-to-pypi=true
```

- **What the dispatch does.** It builds and tests the wheels again on the tag, then publishes
  them with PyPI trusted publishing (GitHub environment `pypi`, job *Upload release to PyPI*).
  The job runs only for `workflow_dispatch` on a `refs/tags/v*` ref.
- **What reaches PyPI.** The uploaded wheels are rebuilt from the same commit as the tested
  archive wheels, not the same files.
- **No second chance.** PyPI never accepts a file name twice.
- **For 3.6.0,** the dispatch was run 36703348530 at 10:35 UTC, and the files were on PyPI at
  12:03.

Then **G6**: every lab with `pyopenms_spec=pyopenms==X.Y.Z`.

## 7. Documentation

- **Doxygen (API reference):** automatic, [step 5](#5-what-the-tag-starts-and-how-to-check-it).
  It lives at `https://archive.openms.de/openms/Documentation/release/X.Y.Z/html/` and
  `…/release/latest/`.
- **pyOpenMS on readthedocs.** **Maintainer**, with admin rights on the `pyopenms` project:
  activate the version `vX.Y.Z`, build it, and make it the default version. Releases before
  3.6.0 were built from release branches, e.g. `release-3.5.0`. The build installs
  `pyopenms==X.Y.Z` from PyPI (`doc/pyopenms/docs/install_pyopenms.py`), so do this after
  [step 6](#6-publish-pyopenms-to-pypi).
  - As of 2026-09-30 the project has built nothing since 2026-04-30, not even `latest`, and
    has no version for `v3.6.0`. The `openms` project built from the tag within a minute, so
    the `pyopenms` project's connection to GitHub looks broken (an inference). Resync its
    versions or reconnect it first.
- **Version switcher.** If step 1 did not add the entry, add it now by PR to `develop`.
- **OpenMS docs on readthedocs** (`openms.readthedocs.io`) need no new version. `latest` follows
  `develop`, and `stable` is built from the newest tag. A page fixed on `develop` after the tag
  reaches `latest` at once, but `stable` only with the next release.

Checks: **G8** and **E10** (`https://pyopenms.readthedocs.io/en/vX.Y.Z/` answers 200).

## 8. Bioconda

The conda packages are two recipes in bioconda/bioconda-recipes:
- `recipes/openms-meta`, with the outputs `libopenms`, `openms` and `openms-thirdparty`;
- `recipes/pyopenms`, which pins `libopenms =={{ version }}`.

So `pyopenms` goes second: its PR opens after the `openms-meta` PR is merged and its packages
are published, unless both recipes are in one PR, as for 3.6.0.

Keep them separate. As an output of `openms-meta`, `pyopenms` is built in the same conda-build
run as the C++ build, once per Python version, and the build time available on conda CI is not
sufficient for that (jpfeuffer). This was tried and reverted on 2026-10-02. It may be worth
another try once pyopenms can be built only once, against the stable ABI (abi3), in nanobind's
split mode; that needs recipe changes, and whether Bioconda handles abi3 builds is open
(jpfeuffer, OpenMS/OpenMS#10395).

Prepare each recipe in the fork OpenMS/bioconda-recipes, on its own branch off a current
bioconda `master`. For 3.6.0 both recipes are on `claude/openms-3.6.0`
(bioconda/bioconda-recipes#69770); `claude/pyopenms-3.6.0` is an older draft it supersedes.

**`meta.yaml`**
- `version`.
- `url: https://github.com/OpenMS/OpenMS/releases/download/v{{ version }}/OpenMS-{{ version }}.tar.gz`
  (before 3.6.0: `release%2F{{ version }}`).
- `sha256` of that release asset. GitHub lists it as the asset's digest; otherwise use
  `curl -L <url> | sha256sum`.
- `build: number: 0`.
- Dependency changes: take them from the fork's `nightly` branch, whose recipes built `develop`
  all cycle.

**`build.sh`**
- `-DGIT_TRACKING=OFF -DOPENMS_GIT_SHORT_REFSPEC="v${PKG_VERSION}" -DOPENMS_GIT_SHORT_SHA1="<short revision of the tag>"`.
  The tarball has no `.git`, so without `GIT_TRACKING=OFF` the tools would report
  `X.Y.Z-pre-exported-<date>`.
- `mkdir -p build`, because the tarball contains an empty `build/` directory.
- Both work around the tarball `release.yml` builds with `tar`. OpenMS/OpenMS#10359 (open)
  builds it with `git archive` instead and records the version in `.git_archival.txt`; once it
  is merged, check whether the next recipe still needs these two lines.

**Maintainer:** open the PR from the fork branch to bioconda/bioconda-recipes `master`.
Claude's GitHub access does not reach bioconda/bioconda-recipes, so an agent hands over the
compare link and a PR description. For 3.6.0 the PR is bioconda/bioconda-recipes#69770.

Check **G7** once the packages are on the bioconda channel.

## 9. Website and announcement

**Maintainer.**
- **Before announcing:** G10 must pass, so that the announcement never points to an unsigned
  installer.
- **Website:** `release.yml` opened a PR in OpenMS/OpenMS-website
  (`content/en/news/releaseX.Y.Z.md`, branch `releaseannouncementX.Y.Z`). Check its links, then
  merge it. For 3.6.0 (OpenMS/OpenMS-website#289), the download link pointed to abibuilder,
  which no longer receives uploads. OpenMS/OpenMS#10354 fixed the template for later
  releases.
- **Announcement:** its text is the `release-announcement.txt` artifact of the tag's
  `release.yml` run. Send it to the mailing lists and channels the maintainers use.

## 10. After the release

- **Start the next cycle.** Merge the next-version PR from [step 5](#5-what-the-tag-starts-and-how-to-check-it).
  Its `(under development)` CHANGELOG heading is what the daily changelog-sync workflow edits.
- **Bioconda nightly.** Bump the fork's `nightly` recipes to the next `…dev` version.
  `bioconda_deploy.yaml` builds them every night into the anaconda.org channel `openms`.
  Before each build it merges `bioconda/master` into `nightly`, so once the release recipe is
  merged upstream, that merge conflicts on the version line.
  - Resolve it once in the fork: merge `bioconda/master` into `nightly` and keep the `…dev`
    version and the `develop` git source.
  - Keep `GIT_TRACKING` on for dev builds: the release `build.sh` passes `GIT_TRACKING=OFF`
    with a fixed revision, which is wrong for `develop`.
  - Keep `-DWITH_OPENTIMS=ON` for dev builds (`openms-meta/build.sh`): pyOpenMS on `develop`
    includes `BrukerTimsFile.h`, which libopenms installs only with opentims. The release turns
    opentims off and patches pyOpenMS instead.
- **Release report.** Write `readiness/<date>-X.Y.Z-release.md` from
  [readiness/TEMPLATE.md](readiness/TEMPLATE.md), with G1–G9 and H on the release's own
  artifacts.
- **Update the lab for the next version:** the release matrix and *Supported platforms* in
  RELEASE-READINESS.md. The baseline follows by itself: *Release readiness* takes the newest
  PyPI version.
- **Known issues.** Open or link an issue for every *Known issues* entry of the CHANGELOG.

## Patch releases

Not yet exercised since 3.6.0. The pieces that exist:

- **Branch.** A patch release needs a branch off the release tag, because `develop` has moved
  on. Earlier releases used `release/X.Y.Z`. `cherry-pick-to-release.yml` opens backport PRs
  onto the branch named by the repository variable `CURRENT_RELEASE_BRANCH`, for merged
  `develop` PRs labelled `patch` (or `vars.PATCH_LABEL`).
- **Version.** On the branch, run `tools/update_version_numbers.sh X Y Z+1` and add a dated
  CHANGELOG section. Update the files in the [step 1 table](#1-prepare-develop) by hand.
- **Testing.** `test.yml` builds and tests pushes to `release/*`. No workflow produces
  installers or wheels of the branch before the tag, so the labs can test only the tag build
  ([step 5](#5-what-the-tag-starts-and-how-to-check-it)).
- **Tag.** Tag `vX.Y.Z+1` on the branch, then continue with steps 5–10.
- **Duplicate bump.** `update_version_numbers.yml` computes `X.(Y+1).0` again and reopens the
  bump PR. Close it when `develop` already has that version.

## Known gaps

As of 2026-09-30:

| Gap | Consequence | Where |
| --- | --- | --- |
| Release candidates are broken | [Step 3](#3-release-candidate-optional-untested): missing archive folders; wrongly named packages; wheels that look final | `release.yml`, `.github/actions/version`, `CMakeLists.txt`, the wheel workflow |
| The Windows installer is signed by hand | `release.yml` publishes the unsigned file at once; it stays the download until a maintainer replaces both copies (G10). `cmake/package_nsis.cmake` has a `signed_dist` target, but CI has no certificate | `release.yml` |
| readthedocs and the version switcher are manual | E10 and A3 fail until [step 7](#7-documentation) is done. The `pyopenms` project stopped building in April 2026 | readthedocs admin, `switcher.json` |
| Patch releases have no packages before the tag | Problems show up only after the tag | [Patch releases](#patch-releases) |
| Bioconda is outside Claude's GitHub access | Upstream PRs are opened by a person | [Step 8](#8-bioconda) |

**Open for 3.6.0 on 2026-09-30** (details in the release report of lab PR #5):
- G10: the signed Windows installer, in both places;
- G8: the GitHub release body (cut off); the download link in OpenMS/OpenMS-website#289;
- G8: the container tags `3.6.0`, by `imagetools` from `v3.6.0`;
- E10: the readthedocs project `pyopenms` (reconnect, build `v3.6.0`, make it the default);
- the switcher entry, OpenMS/OpenMS#10363;
- G7: bioconda/bioconda-recipes#69770 from `claude/openms-3.6.0`, with `openms-meta` and
  `pyopenms` as two recipes in one PR (updated 2026-10-02);
- the next-version PR OpenMS/OpenMS#10349;
- the Bioconda nightly: OpenMS/bioconda-recipes#26 brought `nightly` to the 3.6.0 recipes as
  3.7.0dev; the merge from step 10 once #69770 is in (updated 2026-10-02).

## Secrets and permissions

Names only. They live in OpenMS/OpenMS unless noted.

| Used by | Secrets and variables |
| --- | --- |
| `release.yml` | `ARCHIVE_RRSYNC_SSH`, `ARCHIVE_RRSYNC_HOST`, `ARCHIVE_RRSYNC_PORT`, `ARCHIVE_RRSYNC_USER`; `APPLE_DEVELOPER_ID_APPLICATION_CERT`, `APPLE_DEVELOPER_ID_APPLICATION_PASSWORD`, `APPLE_DEVELOPER_ID_INSTALLER_CERT`, `APPLE_DEVELOPER_ID_INSTALLER_PASSWORD`, `KEYCHAIN_PASSWORD`, `APPLE_APP_SPECIFIC_NOTARIZATION_PASSWORD`; `OPENMS_GITHUB_APP_PRIVATE_KEY` with variable `OPENMS_GITHUB_APP_ID` (website PR) |
| `pyopenms-wheels-cibuildwheel.yml` | `ARCHIVE_RRSYNC_*`; `openms_pypi_pw` (nightly index); for PyPI, the trusted-publisher entry for environment `pypi` on pypi.org |
| `containerdeploy.yml` | `GITHUB_TOKEN` |
| `bioconda_deploy.yaml` | `ANACONDA_TOKEN` |
| `cherry-pick-to-release.yml` | variables `CURRENT_RELEASE_BRANCH`, `PATCH_LABEL` |

## 3.6.0, as it happened

| When (UTC) | What |
| --- | --- |
| 2025-12-09 | `develop` bumped to 3.6.0 by the next-version PR of 3.5.0 (OpenMS/OpenMS#8446) |
| 2026-09-28 | Both Sphinx `conf.py` set to 3.6.0 (OpenMS/OpenMS#10293) |
| 2026-09-30 07:44 | Maintainer waivers for F6 (Sage's SQLite) and F8, in lab PR #5 |
| 2026-09-30 | 5d5cbff (OpenMS/OpenMS#10348) dates the CHANGELOG and adds *Known issues*. The annotated tag `v3.6.0` is pushed on it at 08:24 |
| 08:24–08:58 | `release.yml` run 36689531481: installers and docs on the archive, GitHub release at 08:58, website PR |
| 08:25 | Next-version PR OpenMS/OpenMS#10349 opened |
| 09:38 | Wheels on the archive (run 36689531521); containers published as `v3.6.0` |
| 09:52 | The release matrix on the release's own files; the report ends NOT READY on G7, G8, G10 and E10, with every package check passing (lab PR #5) |
| 10:35 | PyPI dispatch (run 36703348530); the files are on PyPI at 12:03 |
| 16:10 | bioconda/bioconda-recipes#69770 opened |
