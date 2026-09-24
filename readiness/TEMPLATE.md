# Release readiness: OpenMS <version>, <nightly date or RC> (<date checked>)

**Verdict: <NOT READY | READY FOR RC | READY TO RELEASE>**

<One paragraph: what was tested, the revision, and why the verdict is what it is.>

## Candidate

| | |
| --- | --- |
| Wheels | `<file names>`, sha256 `<…>` |
| Installers | `<file names>`, folder `<archive URL>` |
| Revision(s) | wheel `<sha>`, installers `<sha>` |
| Baseline | pyOpenMS `<previous release>`, tag `release/<previous release>` |
| Runs | Release readiness `<run URL>`; labs `<run URLs>` |

## Blocking failures

<Numbered list: check ID, one-sentence finding, evidence link, suggested owner/fix. "None" if none.>

## Checks

`[x]` passed · `[ ]` with **FAIL**, **NOT RUN** or **HUMAN** otherwise. Every line ends with its
evidence.

### A. Candidate identity
- [ ] A1 The artifact set is complete —
- [ ] A2 All artifacts come from one revision —
- [ ] A3 The version agrees everywhere —

### B. Packaging on every platform
- [ ] B1 Windows 3.12, wheel + installer —
- [ ] B2 Windows 3.14, wheel —
- [ ] B3 macOS arm64 3.12, wheel + pkg —
- [ ] B5 macOS arm64 3.14, wheel —
- [ ] B6 Linux x64 3.12, wheel + DEB —
- [ ] B7 Linux arm64 3.12, wheel + DEB —
- [ ] B8 Linux 22.04 3.12, wheel —
- [ ] B9 Linux x64 3.14, wheel —

### C. The installed desktop package (per platform: Linux x64 / Linux arm64 / macOS / Windows)
- [ ] C1 Every registered tool starts —
- [ ] C2 The bundled search engines start —
- [ ] C3 Upstream TOPP tests pass on the installation —
- [ ] C4 Adapters find the bundled engines on their own —
- [ ] C5 Vendor readers work in the installed package —
- [ ] C6 The DEB installs where it claims to —
- [ ] C7 Upgrades order correctly —

### D. pyOpenMS: API and user guide
- [ ] D1 Every removed public name is announced —
- [ ] D2 No user-guide page regressed —
- [ ] D3 The user guide teaches no deprecated API —
- [ ] D4 New classes have docstrings —
- [ ] D5 Every intentional API change has a migration note —
- [ ] D6 The wheel's own tests passed for this revision —

### E. Documentation
- [ ] E1 Every tool is indexed and has a complete page —
- [ ] E2 New and removed tools are in the CHANGELOG —
- [ ] E3 Nothing refers to removed tools —
- [ ] E4 Every headline feature is documented for users —
- [ ] E5 New public classes are documented —
- [ ] E6 Build options are documented —
- [ ] E7 Environment variables are documented —
- [ ] E8 The CHANGELOG is clean —
- [ ] E9 Documentation builds without warnings —
- [ ] E10 The online documentation of the version exists —

### F. Static checks of the artifacts
- [ ] F1 Wheel tags match the declared floor —
- [ ] F2 Wheels are intact —
- [ ] F3 Wheel metadata is usable —
- [ ] F4 Stubs are valid Python —
- [ ] F5 `manylinux` compliance —
- [ ] F6 No known-vulnerable bundled library —
- [ ] F7 Installers are signed —
- [ ] F8 Third-party licenses ship with what they cover —
- [ ] F9 The DEB does not collide with the distribution —

### G. Release mechanics (release candidate only)
- [ ] G1 The RC builds and uploads —
- [ ] G2 Tag builds carry a clean version —
- [ ] G3 The source tarball is right —
- [ ] G4 Workflows triggered by the tag pass —
- [ ] G5 The RC's own artifacts pass B and C —
- [ ] G6 PyPI serves the release everywhere —
- [ ] G7 Conda packages build and install —
- [ ] G8 Documentation and links point at the release —
- [ ] G9 Container images exist for the tag —

### H. Human checks
- [ ] H1 GUI on each platform —
- [ ] H2 TOPPAS *Open containing folder* on macOS —
- [ ] H3 Clean-machine install —
- [ ] H4 The installer's license page —

## Other findings

<Advisory failures and observations that are not tied to a check, with evidence.>
