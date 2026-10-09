# Control tower register

Last digest: 2026-10-09T05:35Z (fourth digest; all active sessions read, PR states checked live)

## Sessions (not archived)

| Session | Title | State | Waiting on |
| --- | --- | --- | --- |
| session_01B51nRFoHvZuVXD7cT8XZav | OpenMS idparquet native migration | needs you (idle) | confirm reorder in FeatureLinkerUnlabeled_1_output.consensusXML (asked 5 times); QC tool flow and MQ exporters moved to pipelines cluster (answered 05:06); draft #10423 conflicts with develop (dirty), CI skipped until develop is merged |
| session_0191LNr9sLGKAN6uGXdyH88H | PR #119 review and testing (bigbio/andes) | archived 20:48; fast-forward to 3495a43 done 20:22 | open offers: OpenMS PR for purity bug (#10467), review post |
| session_01UQCiwdbPoEkrebED8VQ2TJ | Difference between #10400 and #10403 | blocked (waiting for Oliver) | PR #10466 draft, green 31/31 on 5a916bd; Oliver (admin) has not pushed his 16-commit fix branch; open: name clash with #10378, breaking changes, deisotoping default, held-out confirmation; check-in 07:08Z |
| session_013WpJU7kvPs7wZymufRtjuZ | Review 10413 | working (rewriting the RFC issue body, as asked 15:42) | — |
| session_01MmskqjZ8rz3sdTKoACxbqz | Nightly test lab analysis | blocked (review) | #10442 green 31/31, no approving review, question to jpfeuffer/poshul unanswered, AUTHORS unticked |
| session_01M6AHDXanQaXQA1vwts2r81 | Bug: OnDiscMSExperiment range filter drops spectrum metadata | needs you | push fixes 1-3 on #10464 (recommended yes; restarts CI, clang++ ~1h40m); #10464 green 31/31 on 99efcfb, needs human review; AUTHORS box |
| session_015XZxMxzXdp9KCpUSpQL9EF | Bug: OpenSSL 3.6.4 pinned in vcpkg.json | blocked (review) | PR #10458 green 32/32, no reviews |
| session_01DtWvvGGZSyZtVEvxGcPBGc | Bug: SimpleSearchEngine deisotoping deletes fragments | not in active list (not re-read) | state unknown since 15:30 |
| session_01ALQq7vda2rp8XfU8Lj53e3 | Rusttims/mzpeak/mzdata code research | needs you | OpenMS/OpenMS#10469 (BrukerTimsFile m/z calibration) already opened 04:49Z, session unaware; post 31-file research comment on issue #10468? (never answered) |
| session_01Pxi3mzoptivbseUeJHjy2C | develop: strict protein-run contract for peptide identifications | needs you (idle, disconnected) | (1) copy new outputs over 20 expected featureXML files (FeatureFinderIdentification_5_candidates + 19 OpenSwathWorkflow_*), recommended yes; (2) make featureXML/consensusXML writers throw on missing protein_refs (writes PH_0 today), recommended yes as a separate step; branch pushed, no PR |
| session_01HJitekJKm6HFXbNXbrdeof | OpenMS-test lab release readiness | needs you | merge lab branch claude/openms-test-release-readiness-ks3twg (593c62d) to lab main (2-line conflict with wizardly-davinci-fg6gad); file OpenMS issue for OpenDIA Windows failure; Release readiness #13 failed (baseline tag release/3.6.0 vs v3.6.0), Windows lab #39: 2260/2261 TOPP tests, only TOPP_OpenDIA_auto_transition_list_sqlite fails |
| session_01WZ2mArNHq4sHgJEMJmn2zU | Prose in-process percolator usage | done | you: treat OpenMS/OpenMS#10449 as the vehicle; branch claude/vigilant-cori-lvoib0 can go |
| session_01D1N3pC2AqJt57Q3v87bWxz | ProSE improvement PRs untangling | done (idle since 10-03) | approve/merge or close #9975 |
| session_015y74VhdLraCwu7JxgvGwd9 | OpenMS issue #10326 status | done | — (#10396 merged; 10-08 macOS nightly green) |
| session_016mhkk96UKnN229owYHC75b | Pyopenms bioconda recipe revert | done | you: edit description of bioconda/bioconda-recipes#69770 |
| session_013vafYuimyKzwjxdeqBKob5 | Static linking GUI applications to OpenMS | done | maintainers on #10384 (okohlbacher replied 10-02, session never saw it) |

Archived (asks they left are orphaned until someone takes them): Bug: TOPP -write_cwl crashes (OpenMS/OpenMS#10459 merged 10-09 03:09, archived by the tower), :.
QPX Parquet export dedup (root cause is coincident target/decoy features; its own fix was dropped
for jpfeuffer's OpenMS/OpenMS#10453, branch reset to develop; findings 12 and 13 never filed),
LFQ and TMT quantification in Andes (OpenMS/OpenMS#10448 merged; Andes work on bigbio/andes branch
claude/intelligent-johnson-tk7099 at a52aece; PR bigbio/andes#119, head a52aece, state not checked, reviewed by session_0191LNr9sLGKAN6uGXdyH88H), OpenMS PR #10402 review (asked to open issues
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
| 35 | OpenMS #10459 and #10466 conflict with develop (6 commits ahead); their sessions do not know | process | digest 3 | open (tell the sessions to merge develop) | — |
| 36 | #10466 commit cc1ad59 is authored as Julianus Pfeuffer although a session wrote it (applied by hand after auto mode denied cherry-pick) | attribution | Difference between #10400 and #10403 | open (needs you: Co-authored-by instead?) | — |
| 37 | bigbio/andes: multi-run --output-parquet crashes (byte array offset overflow in psms.parquet writer, predates #119); QPX feature_id/psm_ids not QPX-conformant | bug (external: bigbio/andes) | PR #119 review (archived) | spawn? | — |
| 38 | OpenMS FileHandler.cpp:1542-1547 OMSSA load pushes an empty run then writes into additional_proteins[0] (overwrites run 0 when non-empty); MzTab.cpp:1136,1241 and IdentificationDataConverter.cpp:204 throw bare out_of_range after MzTabFile::store truncated the output | bug | strict protein-run contract | owned (likely in scope) | session_01Pxi3mzoptivbseUeJHjy2C |
| 39 | OpenMS #10467: isobaric precursor purity uses neutron mass and one-sided peak search, purity >= 0.75 for 2 of 2,419 scans; no fix PR yet | bug | PR #119 review | open (issue filed) | — |
| 40 | MapAlignmentAlgorithmIdentification::setReference treats a map with no features as empty even with unassigned IDs; RT-less IDs used to put NaN into medians | minor | idparquet migration | open | — |
| 41 | OpenMS BrukerTimsFile (opentims sqrt-linear default): m/z off by up to +1793 ppm on otofControl 5.x and -829 ppm on a 2021 fleX; partly fixed by OpenMS/OpenMS#10469 (ModelType 2 still up to 7.8 ppm) | bug | Rusttims research | owned | session_01ALQq7vda2rp8XfU8Lj53e3 |
| 42 | OpenMS src/topp/QualityControl sorts each feature's IDs by score descending regardless of direction, so the first (used by MQ exporters) is the worst for q-values | bug | idparquet migration | spawned | session_01QggJufF4E4Nw9bmMJaP36f |
| 43 | OpenMS KERNEL/OnDiscMSExperiment.cpp:116 getSpectrumByNativeId and getChromatogramByNativeId ignore PeakFileOptions range and MS-level filters; IndexedMzMLHandler.cpp:267,301 report unfiltered min/max after select() | bug | OnDisc bug session | owned (fixes 1-3 await your yes) | session_01M6AHDXanQaXQA1vwts2r81 |
| 44 | OpenMS TOPP_OpenDIA_auto_transition_list_sqlite fails on Windows (only failure of 2261 in the installed-package run) | bug | release readiness | open (no issue filed; AGENTS.md requires your explicit request) | — |
| 45 | Oliver's #10466 review: ASan hit in IDScoreGetterSetter.cpp:263 (end() dereference in applyPickedProteinFDR); single-file ProSE modification analysis ignores FDR:protein; data race in bundled Percolator on -rescore path; he files them himself | bug | #10400/#10403 | owned by Oliver | — |
| 46 | Windows CI deps step flakes on Chocolatey 504 (rclone in #10442, cmake in #10466); retry loop in tools/ci/deps-windows.sh proposed, not filed (see 20) | minor (flaky CI) | Nightly test lab, #10400/#10403 | open | — |
| 47 | mobiusklein/mzdata 0.67.4 and mzpeak_prototyping: ModelType 2 gives m/z about 18-40 instead of 120-1200 | bug (external) | Rusttims research | open | — |
| 48 | OpenMS #10423 draft conflicts with develop (dirty, base 420fccf); PR CI does not run until develop is merged | process | idparquet migration | open | idparquet migration |

Closed (fixed, kept for reference): IsobaricWorkflow purity tolerance (#10448, finding 6, merged 10-08),
IDConflictResolver lower-is-better (#10444), AccurateMassSearch signed ppm (#10446),
OpenSWATH/TSV scoreless hits (#10446), IBSpectraFile empty-list read (7d3ed05), package_sdk.sh BSD awk (#10435),
macOS notarization agreement (resolved 10-06), Debian 13 Qt deps (develop), macOS pkg relocation (#8479, #10385),
ARM HyperScore abs (#10391), test-lab tag name and Thermo detection (6fab10c, e15db10).
