"""
analyze_tracing.py
==================
Turn the jsPsych output (tracing_<ID>.json) into a trial-level table with the
measures named in the protocol, and (optionally) fit the pre-registered models.

    python analyze_tracing.py tracing_P01.json tracing_P02.json ...
    python analyze_tracing.py data/*.json --fit

Per stretch (one row per tracing stretch, paired with its agency rating):
  pid, phase, block, delay_ms, flash, agency (0-100),
  radial_error_px       mean |r - R| of the HAND  (error covariate)
  revolutions           how many laps (pacing check)
  sampen_speed          sample entropy of hand speed  (complexity shadow 1)
  crqa_det              cross-recurrence determinism hand vs lagged dot (shadow 2)
  crqa_rr               cross-recurrence rate
  n_samples, mean_frame_ms

Complexity shadows are computed on the trajectories resampled to a uniform
grid, so frame-rate jitter does not masquerade as complexity.
"""
import sys, json, argparse
import numpy as np
import pandas as pd


# ----------------------------------------------------------------------------- #
# measures
# ----------------------------------------------------------------------------- #
def resample(t, x, y, hz=50.0):
    """Uniform resampling by linear interpolation."""
    t = np.asarray(t, float); x = np.asarray(x, float); y = np.asarray(y, float)
    if len(t) < 4: return None
    tu = np.arange(t[0], t[-1], 1000.0 / hz)
    return tu, np.interp(tu, t, x), np.interp(tu, t, y)

def sample_entropy(sig, m=2, r_frac=0.2):
    """Sample entropy (Richman & Moorman): -ln(A/B). Higher = less regular."""
    sig = np.asarray(sig, float)
    sig = sig[np.isfinite(sig)]
    n = len(sig)
    if n < m + 20: return np.nan
    r = r_frac * sig.std()
    if r == 0: return np.nan
    def count(mm):
        emb = np.array([sig[i:i + mm] for i in range(n - mm)])
        d = np.max(np.abs(emb[:, None, :] - emb[None, :, :]), axis=2)
        np.fill_diagonal(d, np.inf)
        return (d <= r).sum()
    B, A = count(m), count(m + 1)
    if A == 0 or B == 0: return np.nan
    return -np.log(A / B)

def crqa(hx, hy, cx, cy, radius_frac=0.10, min_line=2, max_n=900):
    """Cross-recurrence between hand (x,y) and lagged-dot (x,y) trajectories.
    Returns (recurrence rate, determinism). Points on diagonal lines of
    length >= min_line count toward determinism."""
    H = np.column_stack([hx, hy]); C = np.column_stack([cx, cy])
    # subsample to bound the matrix size
    step = max(1, int(np.ceil(len(H) / max_n)))
    H, C = H[::step], C[::step]
    if len(H) < 50: return np.nan, np.nan
    D = np.sqrt(((H[:, None, :] - C[None, :, :]) ** 2).sum(-1))
    eps = radius_frac * np.nanmax(D)
    Rm = D <= eps
    rr = Rm.mean()
    if Rm.sum() == 0: return rr, np.nan
    # count points on diagonal lines >= min_line
    n = len(H); on_lines = 0
    for k in range(-(n - 1), n):
        diag = np.diagonal(Rm, offset=k)
        run = 0
        for v in diag:
            if v: run += 1
            else:
                if run >= min_line: on_lines += run
                run = 0
        if run >= min_line: on_lines += run
    det = on_lines / Rm.sum()
    return rr, det


# ----------------------------------------------------------------------------- #
# parsing
# ----------------------------------------------------------------------------- #
def load_one(path):
    with open(path) as f: rows = json.load(f)
    pid = None
    for r in rows:
        if r.get('trial_type') == 'survey-text':
            pid = (r.get('response') or {}).get('pid'); break
    out = []
    pending = None   # last circle-trace awaiting its rating
    for r in rows:
        tt = r.get('trial_type')
        if tt == 'circle-trace':
            pending = r
        elif tt == 'html-slider-response' and pending is not None:
            tr = pending; pending = None
            traj = tr.get('traj') or {}
            rec = dict(pid=pid, phase=tr.get('phase'), block=tr.get('block'),
                       delay_ms=tr.get('delay_ms'), flash=bool(tr.get('flash')),
                       agency=float(r.get('response')),
                       radial_error_px=tr.get('mean_radial_error_px'),
                       revolutions=tr.get('revolutions'),
                       n_samples=tr.get('n_samples'), mean_frame_ms=tr.get('mean_frame_ms'),
                       sampen_speed=np.nan, crqa_rr=np.nan, crqa_det=np.nan)
            rs = resample(traj.get('t', []), traj.get('hx', []), traj.get('hy', []))
            rc = resample(traj.get('t', []), traj.get('cx', []), traj.get('cy', []))
            if rs is not None and rc is not None:
                tu, hx, hy = rs; _, cx, cy = rc
                m = min(len(hx), len(cx)); hx, hy, cx, cy = hx[:m], hy[:m], cx[:m], cy[:m]
                speed = np.hypot(np.diff(hx), np.diff(hy))
                rec['sampen_speed'] = sample_entropy(speed)
                rec['crqa_rr'], rec['crqa_det'] = crqa(hx, hy, cx, cy)
            out.append(rec)
    return out


# ----------------------------------------------------------------------------- #
def fit_models(df):
    """The pre-registered mixed models (H1-H3). Requires statsmodels."""
    try:
        import statsmodels.formula.api as smf
    except ImportError:
        print("statsmodels not installed; skipping model fits."); return
    d = df[(df.phase == 'main') & (~df.flash)].dropna(subset=['agency', 'radial_error_px']).copy()
    d['delay_s'] = d.delay_ms / 1000.0
    print("\nH1  agency ~ delay + error   (random intercept per participant)")
    print(smf.mixedlm("agency ~ delay_s + radial_error_px", d, groups=d["pid"]).fit().summary().tables[1])
    for shadow in ['sampen_speed', 'crqa_det']:
        dd = d.dropna(subset=[shadow])
        if len(dd) > 10:
            print(f"\nH2  {shadow} ~ delay + error")
            print(smf.mixedlm(f"{shadow} ~ delay_s + radial_error_px", dd, groups=dd["pid"]).fit().summary().tables[1])
            print(f"\nH3  agency ~ {shadow} + delay + error   (does the shadow track agency within-person?)")
            print(smf.mixedlm(f"agency ~ {shadow} + delay_s + radial_error_px", dd, groups=dd["pid"]).fit().summary().tables[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--out', default='tracing_trials.csv')
    ap.add_argument('--fit', action='store_true', help='fit the pre-registered mixed models')
    a = ap.parse_args()
    rows = []
    for f in a.files: rows += load_one(f)
    df = pd.DataFrame(rows)
    df.to_csv(a.out, index=False)
    print(f"wrote {a.out}: {len(df)} stretches from {df.pid.nunique()} participant(s)")
    if len(df):
        print("\nmean agency by delay (main, no flash):")
        print(df[(df.phase == 'main') & (~df.flash)].groupby('delay_ms')[['agency', 'radial_error_px', 'sampen_speed', 'crqa_det']].mean().round(3))
    if a.fit: fit_models(df)

if __name__ == '__main__':
    main()
