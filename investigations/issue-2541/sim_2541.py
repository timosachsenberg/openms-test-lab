"""Does OpenMS/OpenMS#2541 still reproduce with today's MapAlignmentAlgorithmIdentification?

Simulates N LC-MS/MS runs of the same sample with known, smooth RT distortions and
DDA-like partial ID overlap, aligns them with the nightly pyOpenMS in several modes and
measures how well the runs end up on one common RT scale.
"""
import sys
import numpy as np
import pyopenms as oms

AA = "ADEFGHILMNPQSTVWY"  # no K/R inside, no C (avoid fixed-mod questions)


def make_sequences(rng, n):
    seqs = set()
    while len(seqs) < n:
        length = rng.integers(7, 20)
        seqs.add("".join(rng.choice(list(AA), size=length)) + rng.choice(["K", "R"]))
    return sorted(seqs)


def simulate(seed, n_runs, n_pep, spread, warp, noise):
    rng = np.random.default_rng(seed)
    seqs = make_sequences(rng, n_pep)
    t_true = rng.uniform(600, 6600, n_pep)
    # per-peptide "detectability": gives realistic heterogeneous overlap
    detect = rng.beta(1.5, 1.2, n_pep)
    shifts = rng.permutation(np.linspace(-spread, spread, n_runs))
    scales = rng.uniform(-0.01, 0.01, n_runs)
    amps = rng.uniform(-warp, warp, n_runs)
    phases = rng.uniform(0, 2 * np.pi, n_runs)

    def distort(r, t):
        return t + shifts[r] + scales[r] * (t - 3600) + amps[r] * np.sin(2 * np.pi * (t - 600) / 6000 + phases[r])

    runs, obs = [], []  # obs[r][seq] = list of observed RTs
    for r in range(n_runs):
        plist = oms.PeptideIdentificationList()
        o = {}
        seen = rng.random(n_pep) < detect
        for i in np.flatnonzero(seen):
            for _ in range(1 + rng.poisson(0.5)):
                rt = float(distort(r, t_true[i]) + rng.normal(0, noise))
                pid = oms.PeptideIdentification()
                pid.setRT(rt)
                pid.setScoreType("q-value")
                pid.setHigherScoreBetter(False)
                hit = oms.PeptideHit()
                hit.setSequence(oms.AASequence.fromString(seqs[i]))
                hit.setScore(0.001)
                hit.setRank(1)
                hit.setCharge(2)
                pid.setHits([hit])
                plist.push_back(pid)
                o.setdefault(seqs[i], []).append(rt)
        runs.append(plist)
        obs.append(o)
    return runs, obs, distort, shifts


def bspline_params():
    prm = oms.Param()
    oms.TransformationModelBSpline.getDefaultParameters(prm)
    return prm


def align(runs, ref_index=-1, min_run_occur=2):
    algo = oms.MapAlignmentAlgorithmIdentification()
    prm = algo.getDefaults()
    prm.setValue("min_run_occur", min_run_occur)
    algo.setParameters(prm)
    trafos = algo.align(runs, ref_index)
    for t in trafos:
        t.fitModel("b_spline", bspline_params())
    return trafos


def transformed_runs(runs, trafos):
    out = []
    for plist, t in zip(runs, trafos):
        new = oms.PeptideIdentificationList()
        for pid in plist:
            q = oms.PeptideIdentification(pid)
            q.setRT(t.apply(pid.getRT()))
            new.push_back(q)
        out.append(new)
    return out


class Composed:
    def __init__(self, first, second):
        self.first, self.second = first, second

    def apply(self, x):
        return self.second.apply(self.first.apply(x))


def evaluate(trafos, obs, distort, n_runs):
    """pairwise residuals on shared peptides + noise-free spread of the common scale"""
    res = []
    for r in range(n_runs):
        for s in range(r + 1, n_runs):
            for seq in obs[r].keys() & obs[s].keys():
                a = trafos[r].apply(float(np.median(obs[r][seq])))
                b = trafos[s].apply(float(np.median(obs[s][seq])))
                res.append(abs(a - b))
    grid = np.linspace(900, 6300, 200)
    g = np.array([[trafos[r].apply(float(distort(r, t))) for t in grid] for r in range(n_runs)])
    spread = g.max(axis=0) - g.min(axis=0)
    res = np.array(res)
    return np.median(res), np.percentile(res, 95), np.median(spread), spread.max()


class Identity:
    def apply(self, x):
        return x


def main():
    scenarios = [  # (label, n_runs, spread [s], warp [s])
        ("5 runs, shifts +-60 s", 5, 60, 20),
        ("5 runs, shifts +-180 s", 5, 180, 40),
        ("10 runs, shifts +-180 s", 10, 180, 40),
    ]
    seeds = [1, 2, 3]
    print("metric per cell: median |pairwise diff| / 95th pct / median spread of common scale / max spread (s), mean over seeds")
    for label, n_runs, spread, warp in scenarios:
        acc = {}
        for seed in seeds:
            runs, obs, distort, _ = simulate(seed, n_runs, 3000, spread, warp, noise=8.0)
            n_ids = [len(r) for r in runs]
            most = int(np.argmax(n_ids))
            modes = {}
            modes["before (identity)"] = [Identity()] * n_runs
            modes["no reference (default)"] = align(runs, -1)
            first = modes["no reference (default)"]
            second = align(transformed_runs(runs, first), -1)
            modes["no reference, run twice"] = [Composed(a, b) for a, b in zip(first, second)]
            modes["no reference, min_run_occur=N"] = align(runs, -1, min_run_occur=n_runs)
            modes["reference = run with most IDs"] = align(runs, most)
            for name, tr in modes.items():
                acc.setdefault(name, []).append(evaluate(tr, obs, distort, n_runs))
        print(f"\n## {label}")
        for name, vals in acc.items():
            v = np.mean(np.array(vals), axis=0)
            print(f"  {name:32s} {v[0]:7.1f} {v[1]:7.1f} {v[2]:7.1f} {v[3]:7.1f}")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
