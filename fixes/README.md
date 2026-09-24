# Candidate fixes

A script here changes an installed OpenMS package the way a proposed fix to OpenMS would, so a
lab can show that the fix works before OpenMS ships it. Pass its path as the lab's `fix_script`
input:

```bash
gh workflow run macos-lab.yml -R timosachsenberg/openms-test-lab \
  -f openms_package=nightly -f pyopenms_spec=none -f debug=false \
  -f fix_script=fixes/macos-bin-qt-conf.sh
```

`scripts/installed-checks.py` runs the script with the installation root as its argument after
the package is installed and before any check. Then it records the script in
`installed-checks.json` and warns that the results judge the fix, not the package.

Rules:

- A run with a fix is evidence for the fix, never for the candidate. Do not use it for a check
  in a readiness report.
- Each script names the OpenMS file and line it stands in for, and fails when the package it
  finds does not have the problem, for example because a newer package already carries the fix.
- Only scripts in this directory run; the input is a path, never a command.

| Script | Stands in for | Problem |
| --- | --- | --- |
| `macos-bin-qt-conf.sh` | the commented-out `bin/qt.conf` install in `cmake/package_mac_productbuild.cmake:86-95` | macOS: `ExecutePipeline` cannot find the `cocoa` Qt platform plugin |
