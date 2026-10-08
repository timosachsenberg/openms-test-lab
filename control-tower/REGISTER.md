# Control tower register

Last digest: 2026-10-08T14:46Z (first digest; findings recovered from sessions that predate the protocol)

## Sessions (not archived)

| Session | Title | State | Waiting on |
| --- | --- | --- | --- |
| session_01B51nRFoHvZuVXD7cT8XZav | OpenMS idparquet native migration | working, has asks | issue for #2; answers on AccurateMassSearch score 0, OpenSWATH protein_refs |
| session_0116xbaQQJpHtmofZc5FirfT | LFQ and TMT quantification in Andes | working | likely push access to bigbio/andes; OpenMS/OpenMS#10448 review |
| session_017NKmtH6KB6Rx2Cb33o7fLg | QPX Parquet export dedup logic bug | working | first turn running |
| session_01K3MCaqfvWzQtRBZSaR1Qvh | OpenMS PR #10402 review | needs you | open issues for #4, #5? |
| session_018qJSdc5YtixGge8Fk5XEiv | OpenMS issue #10110 resolution | needs you | why #10409 was closed; #10110 closed but fix not on develop |
| session_01Qn2mxnL5DMVinM7h53JMm9 | ProSE speed optimizations | needs you | reopen #10407 or new PR from claude/vibrant-edison-n57o3w |
| session_01D1N3pC2AqJt57Q3v87bWxz | ProSE improvement PRs untangling | needs you | approve/merge or close #9975 |
| session_013WpJU7kvPs7wZymufRtjuZ | Review 10413 | failed (weekly limit, 10-04) | "continue" to deliver its finished review |
| session_01MmskqjZ8rz3sdTKoACxbqz | Nightly test lab analysis | review ready | maintainer approval on #10442 |
| session_015y74VhdLraCwu7JxgvGwd9 | OpenMS issue #10326 status | done | — (#10396 merged; 10-08 macOS nightly green) |
| session_016mhkk96UKnN229owYHC75b | Pyopenms bioconda recipe revert | done | you: edit description of bioconda/bioconda-recipes#69770 |
| session_013vafYuimyKzwjxdeqBKob5 | Static linking GUI applications to OpenMS | done | maintainers on #10384 (okohlbacher replied 10-02, session never saw it) |

## Findings

Status: open = nobody owns it; owned = an existing session is on it or asking about it;
spawn? = bug recovered from a pre-protocol session, waits for confirmation; closed = fixed.

| # | Finding | Kind | Source | Status | Owner |
| --- | --- | --- | --- | --- | --- |
| 1 | OpenMS vcpkg.json:60 pins OpenSSL 3.6.4, bundled in all wheels/packages; session cites a High advisory; no open PR | bug (security) | Nightly test lab analysis | spawned | session_015XZxMxzXdp9KCpUSpQL9EF |
| 2 | ConsensusXMLHandler.cpp:899 default-inserts accession_to_id_ and writes wrong PH_0 protein ref; FeatureXMLHandler may share the pattern | bug | idparquet migration | owned (asks to open issue + fix PR) | idparquet migration |
| 3 | FragmentIndex tied-peptide sort order depends on the standard library, results differ by platform; fix 834e2ca only on closed #10407's branch | bug | ProSE speed optimizations | owned (asks reopen/new PR) | ProSE speed optimizations |
| 4 | MRMDecoy.cpp:913/:367 shuffle decoys seeded from time(nullptr): libraries differ between runs | bug | PR #10402 review | owned (asks to open issue) | PR #10402 review |
| 5 | IPF/UIS transition generation: ~200 transitions/precursor, ~14 GB for 8.7k precursors | bug (perf) | PR #10402 review | owned (asks to open issue) | PR #10402 review |
| 6 | IsobaricWorkflow.cpp:337 purity tolerance declared bool (10 ppm becomes 1) | bug | Andes quant | owned, fix in OpenMS/OpenMS#10448 | Andes quant |
| 7 | TOPP `-write_cwl` crashes instead of printing an error (3.6.0 too) | bug | Nightly test lab analysis | spawned | session_017T36hh5UMDeyMRwLiBVkbi |
| 8 | SimpleSearchEngineAlgorithm calls deisotopeAndSingleCharge with start_intensity_check=2, deleting real fragments (21% on TMTpro in ProSE) | bug | ProSE PRs untangling | spawned | session_01DtWvvGGZSyZtVEvxGcPBGc |
| 9 | ToolHandler.cpp:93: OpenMS-GUI.tsv next to a full install's tool list gives "Duplicate tool name", no tool starts (read from code, not reproduced) | bug | Static linking GUI | spawn? | — |
| 10 | FragmentIonLikelihoodModel_test.cpp:121-122 `T(quiet_NaN())` parsed as a declaration under clang; fix was in closed #10378, unclear if on develop | bug | ProSE PRs untangling | spawn? (check develop first) | — |
| 11 | Windows installer unsigned (readiness blocker 10-03 and 10-07) | release blocker | Nightly test lab analysis | open (needs a signing certificate, not a code session) | — |
| 12 | quantms Sage: decoy_string_position defaults to prefix, test DB uses suffix _rev, Sage searches without decoys | bug (external: quantms) | QPX dedup (your prompt) | owned? (in that session's prompt, not acted on) | QPX dedup |
| 13 | sdrf-pipelines sdrf_schema.py: 'float' object has no attribute 'strip' with -profile test_lfq_sage | bug (external) | QPX dedup (your prompt) | owned? (in that session's prompt, not acted on) | QPX dedup |
| 14 | Release workflow: one failing macOS job blocks publishing every platform | minor | Nightly test lab analysis | open | — |
| 15 | MzMLSpectrumDecoder.cpp:142: indexed/on-disc access returns spectra unsorted/unfiltered, unlike MzMLHandler | minor | Review 10413 (undelivered review) | open | — |
| 16 | IsobaricWorkflow: isotope_correction, normalization, min_precursor_purity, min_precursor_intensity never read | minor | Andes quant | open | — |
| 17 | ProteomicsLFQ.cpp:1722: Seeding:charge, Seeding:traceRTTolerance registered but unused | minor | Andes quant | open | — |
| 18 | TOPPBase.cpp:731: nightly tools link to a stale docs copy, 3 tool pages 404 | minor | Nightly test lab analysis | open | — |
| 19 | DEB conflicts with Ubuntu's OpenMS 2.6 `topp` packages | minor | Nightly test lab analysis | open | — |
| 20 | tools/ci/deps-windows.sh: choco 504 reported as success, cache restore then fails | minor (flaky CI) | Nightly test lab analysis | open (retry snippet on #10442) | — |
| 21 | ci-tools rsync-cache "reading from write-only server" in every PR run | minor | Nightly test lab analysis | open | — |
| 22 | CHANGELOG lacks OpenDIA; OpenMS/OpenMS#10387 conflicted since 10-01 | minor | Nightly test lab analysis | open | — |
| 23 | Bundled Comet/MaRaCluster/Sage carry old zlib/SQLite | minor | Nightly test lab analysis | open | — |
| 24 | featureXML writes a list with one empty string as [] | minor | idparquet migration | open (worked around in e90db72) | — |
| 25 | ControlledVocabulary::getPSIMSCV(): repeated loadFromOBO() adds spurious name+description keys | minor | issue #10110 | open (fix only in closed #10409) | — |
| 26 | File.cpp resolveOpenMSDataPath_: compiled-in prefixes probed before exe-relative path | minor | Static linking GUI (okohlbacher on #10384) | open | — |
| 27 | TOPP_ProSE_DDA Bruker tests run in no CI workflow (ENABLE_OPENTIMS_TESTS off); floors may be stale | minor | ProSE PRs untangling | open | — |
| 28 | Docs: Sage DOCS.md integration enum, Philosopher --tol default, ANDES TRAIN.md flags | minor (external docs) | Andes quant, ProSE PRs untangling | open | — |

Closed (fixed, kept for reference): IDConflictResolver lower-is-better (#10444), AccurateMassSearch signed ppm (#10446),
OpenSWATH/TSV scoreless hits (#10446), IBSpectraFile empty-list read (7d3ed05), package_sdk.sh BSD awk (#10435),
macOS notarization agreement (resolved 10-06), Debian 13 Qt deps (develop), macOS pkg relocation (#8479, #10385),
ARM HyperScore abs (#10391), test-lab tag name and Thermo detection (6fab10c, e15db10).
