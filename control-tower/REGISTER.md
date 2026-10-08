# Control tower register

Last digest: 2026-10-08T15:51Z (second digest; covers sessions updated since 14:46Z)

## Sessions (not archived)

| Session | Title | State | Waiting on |
| --- | --- | --- | --- |
| session_01B51nRFoHvZuVXD7cT8XZav | OpenMS idparquet native migration | working (feature linking) | issue for #2; answer on OpenSWATH protein_refs (no trace of one); review of draft OpenMS/OpenMS#10423 |
| session_0191LNr9sLGKAN6uGXdyH88H | PR #119 review and testing (bigbio/andes) | working | — |
| session_01UQCiwdbPoEkrebED8VQ2TJ | Difference between #10400 and #10403 | working (fixing 6 review findings) | step 5 choices: `annotate:self_trained_ion_priors` clash with #10378, isotope_error sign, `precursor:isotopes` removal, Sage-like deisotoping default; then merge #10400, close #10403 |
| session_013WpJU7kvPs7wZymufRtjuZ | Review 10413 | working (rewriting the RFC issue body, as asked 15:42) | — |
| session_01MmskqjZ8rz3sdTKoACxbqz | Nightly test lab analysis | review ready | maintainer approval on #10442 (CI green on 640c59cb); re-check 19:44Z |
| session_01M6AHDXanQaXQA1vwts2r81 | Bug: OnDiscMSExperiment range filter drops spectrum metadata | starting (spawned 15:55Z for #29) | — |
| session_015XZxMxzXdp9KCpUSpQL9EF | Bug: OpenSSL 3.6.4 pinned in vcpkg.json | review ready | CI on OpenMS/OpenMS#10458; check-in 16:17Z |
| session_017T36hh5UMDeyMRwLiBVkbi | Bug: TOPP -write_cwl crashes | idle, CWL-enabled build running | fix af3ef01 committed, not pushed; then PR |
| session_01DtWvvGGZSyZtVEvxGcPBGc | Bug: SimpleSearchEngine deisotoping deletes fragments | idle, build running | regression test pushed (claude/sse-deisotope-start-check); fix not written |
| session_01WZ2mArNHq4sHgJEMJmn2zU | Prose in-process percolator usage | done | you: treat OpenMS/OpenMS#10449 as the vehicle; branch claude/vigilant-cori-lvoib0 can go |
| session_01D1N3pC2AqJt57Q3v87bWxz | ProSE improvement PRs untangling | done (idle since 10-03) | approve/merge or close #9975 |
| session_015y74VhdLraCwu7JxgvGwd9 | OpenMS issue #10326 status | done | — (#10396 merged; 10-08 macOS nightly green) |
| session_016mhkk96UKnN229owYHC75b | Pyopenms bioconda recipe revert | done | you: edit description of bioconda/bioconda-recipes#69770 |
| session_013vafYuimyKzwjxdeqBKob5 | Static linking GUI applications to OpenMS | done | maintainers on #10384 (okohlbacher replied 10-02, session never saw it) |

Archived since the first digest (asks they left are orphaned until someone takes them):
QPX Parquet export dedup (root cause is coincident target/decoy features; its own fix was dropped
for jpfeuffer's OpenMS/OpenMS#10453, branch reset to develop; findings 12 and 13 never filed),
LFQ and TMT quantification in Andes (OpenMS/OpenMS#10448 merged; Andes work on bigbio/andes branch
claude/intelligent-johnson-tk7099 at a52aece, no PR), OpenMS PR #10402 review (asked to open issues
for 4 and 5), OpenMS issue #10110 resolution (asked why #10409 was closed), ProSE speed
optimizations (asked to reopen #10407 or open a new PR from claude/vibrant-edison-n57o3w).

## Findings

Status: open = nobody owns it; owned = an existing session is on it or asking about it;
spawn? = bug waits for confirmation to get a session; spawned = bug session running; closed = fixed.

| # | Finding | Kind | Source | Status | Owner |
| --- | --- | --- | --- | --- | --- |
| 1 | OpenMS vcpkg.json:60 pins OpenSSL 3.6.4, bundled in all wheels/packages; High advisory (CVE-2026-84782, DTLS-only). Also: OpenSSL 3.6 support ends 2026-11-01, pin must move to 4.0 or 3.5 LTS (tracked in #10270) | bug (security) | Nightly test lab analysis | spawned; OpenMS/OpenMS#10458 (3.6.5) open, CI running | session_015XZxMxzXdp9KCpUSpQL9EF |
| 2 | ConsensusXMLHandler.cpp:899 default-inserts accession_to_id_ and writes wrong PH_0 protein ref; FeatureXMLHandler may share the pattern | bug | idparquet migration | owned (asks to open issue + fix PR); still no issue | idparquet migration |
| 3 | FragmentIndex tied-peptide sort order depends on the standard library, results differ by platform; fix 834e2ca only on closed #10407's branch. Related: Boost.Sort total-order peptide key proposal, in neither #10400 nor #10403 | bug | ProSE speed optimizations (archived) | open | — |
| 4 | MRMDecoy.cpp:913/:367 shuffle decoys seeded from time(nullptr): libraries differ between runs | bug | PR #10402 review (archived) | open (no issue filed) | — |
| 5 | IPF/UIS transition generation: ~200 transitions/precursor, ~14 GB for 8.7k precursors | bug (perf) | PR #10402 review (archived) | open (no issue filed) | — |
| 7 | TOPP `-write_cwl` crashes instead of printing an error (3.6.0 too); reproduced, ParamCWLFile throws std::runtime_error TOPPBase does not catch | bug | Nightly test lab analysis | spawned; fix af3ef01 local, not pushed | session_017T36hh5UMDeyMRwLiBVkbi |
| 8 | SimpleSearchEngineAlgorithm calls deisotopeAndSingleCharge with start_intensity_check=2, deleting real fragments (21% on TMTpro in ProSE) | bug | ProSE PRs untangling | spawned; regression test pushed, fix not written | session_01DtWvvGGZSyZtVEvxGcPBGc |
| 9 | ToolHandler.cpp:93: OpenMS-GUI.tsv next to a full install's tool list gives "Duplicate tool name", no tool starts (read from code, not reproduced) | bug | Static linking GUI | spawn? | — |
| 10 | FragmentIonLikelihoodModel_test.cpp:121-122 `T(quiet_NaN())` parsed as a declaration under clang; fix was in closed #10378, unclear if on develop | bug | ProSE PRs untangling | spawn? (check develop first) | — |
| 11 | Windows installer unsigned (readiness blocker 10-03, 10-07) | release blocker | Nightly test lab analysis | open (needs a signing certificate, not a code session) | — |
| 12 | quantms Sage: decoy_string_position defaults to prefix, test DB uses suffix _rev, Sage searches without decoys | bug (external: quantms) | QPX dedup (archived) | open (never filed) | — |
| 13 | sdrf-pipelines sdrf_schema.py: 'float' object has no attribute 'strip' with -profile test_lfq_sage | bug (external) | QPX dedup (archived) | open (never filed) | — |
| 14 | Release workflow: one failing macOS job blocks publishing every platform | minor | Nightly test lab analysis | open | — |
| 15 | MzMLSpectrumDecoder.cpp:142: indexed/on-disc access returns spectra unsorted/unfiltered, unlike MzMLHandler (see 29) | minor | Review 10413 | open | — |
| 16 | IsobaricWorkflow: isotope_correction, normalization, min_precursor_purity, min_precursor_intensity never read | minor | Andes quant | open | — |
| 17 | ProteomicsLFQ.cpp:1722: Seeding:charge, Seeding:traceRTTolerance registered but unused | minor | Andes quant | open | — |
| 18 | TOPPBase.cpp:731: nightly tools link to a stale docs copy, 3 tool pages 404 | minor | Nightly test lab analysis | open | — |
| 19 | DEB conflicts with Ubuntu's OpenMS 2.6 `topp` packages | minor | Nightly test lab analysis | open | — |
| 20 | tools/ci/deps-windows.sh: choco 504 reported as success, cache restore then fails | minor (flaky CI) | Nightly test lab analysis | open (retry snippet on #10442; separate PR not opened) | — |
| 21 | ci-tools rsync-cache "reading from write-only server" in every PR run | minor | Nightly test lab analysis | open | — |
| 22 | CHANGELOG lacks OpenDIA; OpenMS/OpenMS#10387 conflicted since 10-01 | minor | Nightly test lab analysis | open | — |
| 23 | Bundled Comet/MaRaCluster/Sage carry old zlib/SQLite | minor | Nightly test lab analysis | open | — |
| 24 | featureXML writes a list with one empty string as [] | minor | idparquet migration | open (worked around in e90db72) | — |
| 25 | ControlledVocabulary::getPSIMSCV(): repeated loadFromOBO() adds spurious name+description keys | minor | issue #10110 (archived) | open (fix only in closed #10409) | — |
| 26 | File.cpp resolveOpenMSDataPath_: compiled-in prefixes probed before exe-relative path | minor | Static linking GUI (okohlbacher on #10384) | open | — |
| 27 | TOPP_ProSE_DDA Bruker tests run in no CI workflow (ENABLE_OPENTIMS_TESTS off); floors may be stale | minor | ProSE PRs untangling | open | — |
| 28 | Docs: Sage DOCS.md integration enum, Philosopher --tol default, ANDES TRAIN.md flags | minor (external docs) | Andes quant, ProSE PRs untangling | open | — |
| 29 | OnDiscMSExperiment.cpp:175: with an m/z or intensity range set, the indexed path copies only the SpectrumSettings base; RT, MS level, name and all float/string/int data arrays (incl. ion mobility) are lost; chromatogram overload loses name and data arrays; tests assert only peak counts; from #10292; fix: copy the whole spectrum, use MSSpectrum::select | bug | Review 10413 | spawned | session_01M6AHDXanQaXQA1vwts2r81 |
| 30 | ParamCTDFile and ParamJSONFile throw std::ios::failure that TOPPBase does not catch (not a crash today: outputFileWritable_ checks first) | minor | Bug: write_cwl | open | — |
| 31 | Percolator 3.07.1 stops with "median decoy score <= score at 1% FDR" on the ProSE_6 test data and ProSE falls back to HyperScores; the vendored in-process Percolator logs the same error but continues and rescores | minor (behaviour difference) | Prose in-process percolator | open | — |
| 32 | bigbio/andes: `--lfq-min-cosine` is parsed and logged but never applied | bug (external: bigbio/andes) | PR #119 review | owned (reviewing PR #119) | PR #119 review |
| 33 | bigbio/andes: default MS3 tolerance too wide for SPS-MS3; at 0.002 Da / 20 ppm raw MS3 reporter values match OpenMS IsobaricAnalyzer on all 52 joined scans | bug (external: bigbio/andes) | PR #119 review | owned (reviewing PR #119) | PR #119 review |
| 34 | Environment network policy blocks github.com archive downloads (403): vcpkg cannot fetch, the CLAUDE.md build route fails; allow `github.com` and `codeload.github.com` | environment | Bug: write_cwl | open (needs you, environment settings) | — |

Closed (fixed, kept for reference): IsobaricWorkflow purity tolerance (#10448, finding 6, merged 10-08),
IDConflictResolver lower-is-better (#10444), AccurateMassSearch signed ppm (#10446),
OpenSWATH/TSV scoreless hits (#10446), IBSpectraFile empty-list read (7d3ed05), package_sdk.sh BSD awk (#10435),
macOS notarization agreement (resolved 10-06), Debian 13 Qt deps (develop), macOS pkg relocation (#8479, #10385),
ARM HyperScore abs (#10391), test-lab tag name and Thermo detection (6fab10c, e15db10).
