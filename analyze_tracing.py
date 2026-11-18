"""
analyze_tracing.py  --  delayed-feedback circle tracing: JSON -> CSV tables, figures, model report
=====================================================================================================

    python analyze_tracing.py data/                      # a folder of .json files (searched recursively)
    python analyze_tracing.py data/*.json --out results  # or a list of files

Reads the jsPsych JSON files written by index.html (task versions v1 and v2 are both understood) and writes
into the output folder (default ./results):

    trials.csv        one row per tracing stretch, paired with its agency rating, with all measures and QC flags
    participants.csv  one row per session: device, refresh rate, debrief, QC summary, inclusion decision,
                      per-person psychometric fit (PSE, slope), Spearman rho, within-session drift
    report.txt        everything printed to the screen: QC, agency table, per-person fits, the H1-H3 models
    figures/          fig1_agency_by_delay.png       group curve + every participant
                      fig2_participant_curves.png    one panel per participant with fit and PSE
                      fig3_quality.png               tracing error, pace, off-ring share per stretch
                      fig4_session_drift.png         agency at intermediate delays across the session
                      fig5_shadows.png               complexity shadows by delay and against pace
                      trajectories/<pid>.png         every stretch's hand path, for eyeballing compliance

Per-stretch measures (trials.csv)
  agency               0-100 rating after the stretch
  radial_error_px      mean |r - R| of the hand
  laps, laps_per_s     tracing amount and pace
  off_ring_frac        share of frames with |r - R| > ring tolerance (default 40 px)
  backward_frac        share of the angular path travelled against the main direction
  hand_dot_sep_px      mean hand-to-dot distance (the *spatial* size of the lag; grows with pace)
  sampen_speed         sample entropy of hand speed (complexity shadow 1; m = 2, r = 0.2 SD)
  rqa_det              determinism of the hand's angular-velocity dynamics at a FIXED recurrence rate
                       (complexity shadow 2; replaces v1 crqa_det -- see CHANGELOG.md)
  exclude_stretch      True if off ring, reversing, or scribbling (faster than the max pace)

Exclusion (defaults; change with the options below)
  stretch      off_ring_frac > 0.25, backward_frac > 0.15, or laps_per_s > 0.75.
               Slow tracing (laps_per_s < 0.15) is FLAGGED (flag_slow) but kept unless --exclude-slow.
  participant  fewer than 70% of main stretches kept; trackpad kept after the switch prompt
               (unless --keep-trackpad); dev/test sessions (unless --include-dev).

Requirements: numpy, pandas, scipy, matplotlib; statsmodels for the mixed models.
    pip install numpy pandas scipy matplotlib statsmodels
"""
import argparse, glob, json, os, sys, warnings
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

# ----------------------------------------------------------------------------------------------------- #
# signal measures
# ----------------------------------------------------------------------------------------------------- #
def resample(t, *sigs, hz=50.0):
    """Linear resampling onto a uniform grid, so frame-rate jitter (60 vs 120 Hz) does not look like complexity."""
    t = np.asarray(t, float)
    if len(t) < 4: return None
    tu = np.arange(t[0], t[-1], 1000.0 / hz)
    return (tu,) + tuple(np.interp(tu, t, np.asarray(s, float)) for s in sigs)

def sample_entropy(sig, m=2, r_frac=0.2):
    """Sample entropy (Richman & Moorman 2000): -ln(A/B). Higher = less regular."""
    sig = np.asarray(sig, float); sig = sig[np.isfinite(sig)]
    n = len(sig)
    if n < m + 20: return np.nan
    r = r_frac * sig.std()
    if r == 0: return np.nan
    def count(mm):
        emb = np.lib.stride_tricks.sliding_window_view(sig, mm)[: n - m]
        c = 0
        for i in range(len(emb) - 1):                          # row-wise keeps memory at O(n)
            c += int((np.max(np.abs(emb[i + 1:] - emb[i]), axis=1) <= r).sum())
        return c
    B, A = count(m), count(m + 1)
    return -np.log(A / B) if A > 0 and B > 0 else np.nan

def rqa_det(sig, dim=3, tau=3, rr=0.05, lmin=2, max_n=1000):
    """Determinism of a z-scored, delay-embedded signal at a FIXED recurrence rate `rr`.
    Fixing RR (rather than the radius) keeps DET comparable across stretches whose speed and
    amplitude differ; a Theiler window of dim*tau samples removes trivially close neighbours."""
    x = np.asarray(sig, float); x = x[np.isfinite(x)]
    if len(x) > max_n: x = x[np.linspace(0, len(x) - 1, max_n).astype(int)]
    if len(x) < 60 or x.std() == 0: return np.nan
    x = (x - x.mean()) / x.std()
    emb = np.column_stack([x[i * tau: len(x) - (dim - 1) * tau + i * tau] for i in range(dim)])
    n = len(emb)
    D = np.max(np.abs(emb[:, None, :] - emb[None, :, :]), axis=2)
    w = dim * tau
    iu = np.triu_indices(n, k=w + 1)
    eps = np.quantile(D[iu], rr)
    Rm = D <= eps
    rec = on_lines = 0
    for k in range(w + 1, n):
        v = np.diagonal(Rm, offset=k).astype(np.int8)
        rec += int(v.sum())
        if v.sum() < lmin: continue
        d = np.diff(np.concatenate(([0], v, [0])))
        runs = np.flatnonzero(d == -1) - np.flatnonzero(d == 1)
        on_lines += int(runs[runs >= lmin].sum())
    return on_lines / rec if rec else np.nan

def stretch_measures(traj, R, C, ring_tol, shadows=True):
    t = np.asarray(traj.get('t', []), float)
    hx, hy = np.asarray(traj.get('hx', []), float), np.asarray(traj.get('hy', []), float)
    cx, cy = np.asarray(traj.get('cx', []), float), np.asarray(traj.get('cy', []), float)
    out = dict(n_samples=len(t))
    if len(t) < 10: return out
    rad = np.hypot(hx - C, hy - C)
    ang = np.arctan2(hy - C, hx - C)
    dang = np.diff(ang); dang = (dang + np.pi) % (2 * np.pi) - np.pi
    pos, neg = dang[dang > 0].sum(), -dang[dang < 0].sum()
    dur = (t[-1] - t[0]) / 1000
    laps = abs(dang.sum()) / (2 * np.pi)
    out.update(duration_s=dur, frame_ms=np.diff(t).mean(), frame_ms_sd=np.diff(t).std(),
               radial_error_px=np.abs(rad - R).mean(), laps=laps, laps_per_s=laps / dur if dur else np.nan,
               off_ring_frac=(np.abs(rad - R) > ring_tol).mean(),
               backward_frac=min(pos, neg) / (pos + neg) if pos + neg else np.nan,
               direction='cw' if dang.sum() >= 0 else 'ccw',
               hand_dot_sep_px=np.hypot(hx - cx, hy - cy).mean())
    if shadows:
        rs = resample(t, hx, hy)
        if rs is not None:
            tu, x, y = rs
            speed = np.hypot(np.diff(x), np.diff(y))
            a = np.unwrap(np.arctan2(y - C, x - C))
            omega = np.diff(a) * 50.0                            # angular velocity, rad/s
            out['sampen_speed'] = sample_entropy(speed)
            out['rqa_det'] = rqa_det(omega)
    return out

# ----------------------------------------------------------------------------------------------------- #
# parsing
# ----------------------------------------------------------------------------------------------------- #
def parse_file(path, args):
    with open(path) as f: rows = json.load(f)
    if isinstance(rows, dict) and 'json' in rows: rows = json.loads(rows['json'])   # raw receiver payload
    first = next((r for r in rows if r.get('trial_type') == 'survey-text'
                  and isinstance(r.get('response'), dict) and 'pid' in r['response']), {})
    pid = str(first.get('response', {}).get('pid', rows[0].get('pid', os.path.basename(path))))
    session = str(rows[0].get('session', '')) or os.path.basename(path)
    study = rows[0].get('study', 'agency_tracing_v1')
    ans = lambda q: next((r.get('answer') for r in rows if r.get('question') == q), None)
    traces, pending, main_i = [], None, 0
    for r in rows:
        tt = r.get('trial_type')
        if tt == 'circle-trace': pending = r
        elif tt == 'html-slider-response' and pending is not None:
            tr, pending = pending, None
            if tr.get('phase') == 'main': main_i += 1
            R = tr.get('ring_radius_px', args.ring_radius); C = tr.get('canvas_px', args.canvas) / 2
            rec = dict(pid=pid, session=session, study=study, phase=tr.get('phase'), block=tr.get('block'),
                       stretch_index=tr.get('stretch_index') or (main_i if tr.get('phase') == 'main' else None),
                       delay_ms=tr.get('delay_ms'), flash=bool(tr.get('flash')),
                       agency=float(r.get('response')), rating_rt_ms=r.get('rt'),
                       feedback_shown=tr.get('qc_feedback'), stretch_ms=tr.get('duration_ms'))
            rec.update(stretch_measures(tr.get('traj') or {}, R, C, args.ring_tol, not args.no_shadows))
            traces.append(rec)
    deb = next((r for r in rows if r.get('phase') == 'debrief'), None)
    if deb is None: debrief = None
    elif 'answer' in deb: debrief = 'colour:' + str(deb['answer'])
    else:                                                     # v1 single 4-option question
        debrief = {0: 'lag_only', 1: 'colour_only', 2: 'lag_and_colour', 3: 'nothing'}.get(deb.get('response'))
    comment = next((r['response'].get('comment') for r in rows if r.get('question') == 'comment'
                    and isinstance(r.get('response'), dict)), None)
    stretch_ms = traces[0]['stretch_ms'] if traces else None
    sess = dict(pid=pid, session=session, study=study, file=os.path.basename(path), n_rows=len(rows),
                completed=deb is not None, dev=bool(rows[-1].get('dev', False)) or (stretch_ms is not None and stretch_ms < 20000),
                device=ans('device'), device_switch=ans('device_switch'), hand=ans('hand'),
                debrief=debrief, comment=comment, user_agent=rows[0].get('user_agent'),
                screen=f"{rows[0].get('screen_w')}x{rows[0].get('screen_h')}" if rows[0].get('screen_w') else None,
                session_min=round(rows[-1].get('time_elapsed', 0) / 60000, 1))
    return sess, traces

def _parse(a):
    path, args = a
    try: return parse_file(path, args)
    except Exception as e: return ('ERROR', path, repr(e))

# ----------------------------------------------------------------------------------------------------- #
# per-participant summaries
# ----------------------------------------------------------------------------------------------------- #
def logistic(d, pse, s): return 100 / (1 + np.exp((d - pse) / s))

def drift_slope(g):
    """Change in agency per stretch, holding delay constant (agency ~ delay dummies + stretch_index)."""
    if len(g) < 5: return np.nan
    X = pd.get_dummies(g.delay_ms.astype(int), dtype=float); X['k'] = g.stretch_index.astype(float)
    return np.linalg.lstsq(X.values, g.agency.values.astype(float), rcond=None)[0][-1]

def fit_logistic(d, y, boot=0, seed=0):
    from scipy.optimize import curve_fit
    d, y = np.asarray(d, float), np.asarray(y, float)
    kw = dict(p0=[150, 40], bounds=([-200, 3], [800, 500]), maxfev=5000)
    try: p = curve_fit(logistic, d, y, **kw)[0]
    except Exception: return np.nan, np.nan, np.nan, np.nan
    lo = hi = np.nan
    if boot:
        rng = np.random.default_rng(seed); bs = []
        for _ in range(boot):
            i = rng.integers(0, len(d), len(d))
            try: bs.append(curve_fit(logistic, d[i], y[i], **kw)[0][0])
            except Exception: pass
        if len(bs) > boot / 2: lo, hi = np.percentile(bs, [2.5, 97.5])
    return p[0], p[1], lo, hi

# ----------------------------------------------------------------------------------------------------- #
# figures
# ----------------------------------------------------------------------------------------------------- #
BLUE, ORANGE, GREY, INK, MUTED, GRID = '#2a78d6', '#eb6834', '#a9a9a2', '#222222', '#6b6b6b', '#e1e0d9'

def style():
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 10, 'axes.edgecolor': '#c3c2b7', 'axes.labelcolor': INK, 'xtick.color': MUTED,
                         'ytick.color': MUTED, 'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': True,
                         'grid.color': GRID, 'grid.linewidth': .6, 'axes.titlesize': 11, 'axes.titleweight': 'bold',
                         'axes.titlelocation': 'left', 'legend.frameon': False, 'savefig.dpi': 150})
    return plt

def ci_mean(x, n=2000, seed=0):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 2: return (np.nan, np.nan)
    b = np.random.default_rng(seed).choice(x, (n, len(x))).mean(1)
    return tuple(np.percentile(b, [2.5, 97.5]))

def make_figures(T, P, outdir, delays, ring_R, canvas, files):
    plt = style()
    fd = os.path.join(outdir, 'figures'); os.makedirs(os.path.join(fd, 'trajectories'), exist_ok=True)
    inc = P.loc[P.include, 'key'].tolist()
    good = T[(T.phase == 'main') & ~T.flash & ~T.exclude_stretch & T.key.isin(inc)]
    dd = np.linspace(0, max(delays), 200)

    # fig1 group curve
    fig, ax = plt.subplots(figsize=(7, 5))
    pm = good.groupby(['key', 'delay_ms']).agency.mean().unstack()
    for k, row in pm.iterrows(): ax.plot(row.index, row.values, color=GREY, lw=1, alpha=.7)
    if len(pm):
        g = pm.mean(); ci = np.array([ci_mean(pm[c]) for c in pm.columns])
        ax.fill_between(pm.columns, ci[:, 0], ci[:, 1], color=BLUE, alpha=.15, lw=0)
        ax.plot(g.index, g.values, 'o', color=BLUE, ms=8, mec='white', mew=1.5, zorder=5)
        pse, s, _, _ = fit_logistic(good.delay_ms, good.agency)
        if np.isfinite(pse):
            ax.plot(dd, logistic(dd, pse, s), color=BLUE, lw=2.2, label=f'pooled logistic fit, PSE = {pse:.0f} ms')
        ax.plot([], [], color=GREY, lw=1, label=f'individual participants (n = {len(pm)})')
        ax.plot([], [], 'o', color=BLUE, mec='white', label='group mean ± 95% CI')
    ax.axhline(50, color=MUTED, lw=.8, ls=':')
    ax.set(xlabel='Imposed delay (ms)', ylabel='Agency rating (0–100)', xticks=delays, ylim=(-3, 103),
           title='Sense of agency by visual-feedback delay')
    ax.legend(loc='lower left'); fig.tight_layout(); fig.savefig(os.path.join(fd, 'fig1_agency_by_delay.png')); plt.close(fig)

    # fig2 small multiples
    main = T[(T.phase == 'main') & ~T.flash]
    keys = P.key.tolist(); nc = min(5, max(1, len(keys))); nr = int(np.ceil(len(keys) / nc))
    fig, axs = plt.subplots(nr, nc, figsize=(3.2 * nc, 2.8 * nr), squeeze=False, sharex=True, sharey=True)
    for ax, k in zip(axs.ravel(), keys):
        p = P.set_index('key').loc[k]; g = main[main.key == k]
        col = BLUE if p.include else ORANGE
        kept, dropped = g[~g.exclude_stretch], g[g.exclude_stretch]
        ax.scatter(kept.delay_ms, kept.agency, s=14, color=col, alpha=.5, lw=0)
        ax.scatter(dropped.delay_ms, dropped.agency, s=14, facecolor='none', edgecolor=MUTED, lw=.8)
        m = kept.groupby('delay_ms').agency.mean(); ax.plot(m.index, m.values, 'o', color=col, ms=6, mec='white')
        if np.isfinite(p.pse_ms): ax.plot(dd, logistic(dd, p.pse_ms, p.slope_ms), color=col, lw=1.8)
        t = f"{p.pid}" + (f"  PSE {p.pse_ms:.0f}" if np.isfinite(p.pse_ms) else '')
        if not p.include: t += f"\nEXCLUDED: {p.exclude_reason}"
        ax.set_title(t, fontsize=9, color=INK if p.include else ORANGE)
        ax.axhline(50, color=MUTED, lw=.6, ls=':'); ax.set_xticks(delays); ax.set_ylim(-5, 105)
    for ax in axs.ravel()[len(keys):]: ax.axis('off')
    fig.supxlabel('Imposed delay (ms)'); fig.supylabel('Agency rating')
    fig.suptitle('Per participant (open circles = excluded stretches)', x=.01, ha='left', fontsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(fd, 'fig2_participant_curves.png')); plt.close(fig)

    # fig3 quality
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.3))
    for ax, y, lab, thr in [(axs[0], 'radial_error_px', 'Mean |r − R| of hand (px)', None),
                            (axs[1], 'laps_per_s', 'Laps per second', (QC['min_lps'], QC['max_lps'])),
                            (axs[2], 'off_ring_frac', 'Share of frames off the ring', (QC['max_off'],))]:
        for k in keys:
            g = T[(T.key == k) & (T.phase == 'main')].sort_values('stretch_index')
            inc_k = P.set_index('key').loc[k, 'include']
            ax.plot(g.stretch_index, g[y], '-', color=GREY if inc_k else ORANGE, lw=1, alpha=.8 if inc_k else 1)
        for v in (thr or ()): ax.axhline(v, color=INK, lw=.9, ls='--')
        ax.set(xlabel='Stretch number (main phase)', ylabel=lab)
    axs[0].plot([], [], color=GREY, label='included'); axs[0].plot([], [], color=ORANGE, label='excluded'); axs[0].legend()
    axs[0].set_title(f'Tracing error (ring radius {ring_R} px)'); axs[1].set_title('Pace (dashed = feedback limits)')
    axs[2].set_title('Off the ring (dashed = stretch exclusion)')
    fig.tight_layout(); fig.savefig(os.path.join(fd, 'fig3_quality.png')); plt.close(fig)

    # fig4 drift at intermediate delays
    fig, ax = plt.subplots(figsize=(7, 4.6))
    mid_d = [d for d in delays if 0 < d < max(delays)]
    mid = good[good.delay_ms.isin(mid_d)]
    for k, g in mid.groupby('key'):
        if len(g) > 3:
            z = np.polyfit(g.stretch_index, g.agency, 1); xs = np.array([g.stretch_index.min(), g.stretch_index.max()])
            ax.plot(xs, np.polyval(z, xs), color=GREY, lw=1)
    if len(mid):
        bins = pd.cut(mid.stretch_index, bins=6)
        bm = mid.groupby(bins, observed=True).agg(x=('stretch_index', 'mean'), y=('agency', 'mean'))
        ax.plot(bm.x, bm.y, '-o', color=BLUE, lw=2, ms=7, mec='white', label='all participants, binned mean')
        ax.plot([], [], color=GREY, label='each participant, linear trend')
    ax.set(xlabel='Stretch number (main phase)', ylabel='Agency rating', ylim=(-3, 103),
           title=f'Agency at intermediate delays ({", ".join(map(str, mid_d))} ms) across the session')
    ax.legend(loc='lower right'); fig.tight_layout(); fig.savefig(os.path.join(fd, 'fig4_session_drift.png')); plt.close(fig)

    # fig5 shadows
    if 'sampen_speed' in good:
        fig, axs = plt.subplots(2, 2, figsize=(11, 8))
        for row, y, lab in [(0, 'sampen_speed', 'SampEn of hand speed'), (1, 'rqa_det', 'RQA determinism (RR = 5%)')]:
            pm = good.groupby(['key', 'delay_ms'])[y].mean().unstack()
            a = axs[row, 0]
            for k, r in pm.iterrows(): a.plot(r.index, r.values, color=GREY, lw=1, alpha=.7)
            if len(pm):
                ci = np.array([ci_mean(pm[c]) for c in pm.columns])
                a.fill_between(pm.columns, ci[:, 0], ci[:, 1], color=BLUE, alpha=.15, lw=0)
                a.plot(pm.columns, pm.mean(), '-o', color=BLUE, lw=2, ms=7, mec='white')
            a.set(xlabel='Imposed delay (ms)', ylabel=lab, xticks=delays, title=f'{lab} by delay')
            a = axs[row, 1]
            a.scatter(good.laps_per_s, good[y], s=12, color=BLUE, alpha=.35, lw=0)
            a.set(xlabel='Laps per second', ylabel=lab, title='… and against pace (a confound to control)')
        fig.tight_layout(); fig.savefig(os.path.join(fd, 'fig5_shadows.png')); plt.close(fig)

    # trajectory sheets
    for k in keys:
        rows = json.load(open(files[k])); tr = [r for r in rows if r.get('trial_type') == 'circle-trace']
        nc = 8; nr = int(np.ceil(len(tr) / nc))
        fig, axs = plt.subplots(nr, nc, figsize=(2.1 * nc, 2.3 * nr), squeeze=False)
        sub = T[T.key == k].reset_index(drop=True)
        for i, (ax, r) in enumerate(zip(axs.ravel(), tr)):
            Rr = r.get('ring_radius_px', ring_R); Cc = r.get('canvas_px', canvas) / 2
            ax.add_patch(plt.Circle((Cc, Cc), Rr, fill=False, color='#d9d9d9', lw=5))
            bad = bool(sub.exclude_stretch.iloc[i]) if i < len(sub) else False
            ax.plot(r['traj']['hx'], r['traj']['hy'], lw=.5, color=ORANGE if bad else BLUE)
            ax.set(xlim=(0, 2 * Cc), ylim=(2 * Cc, 0), aspect='equal', xticks=[], yticks=[])
            ax.grid(False)
            ax.set_title(f"{(r.get('phase') or '')[:2]} {r['delay_ms']}ms{' F' if r.get('flash') else ''} "
                         f"a={sub.agency.iloc[i]:.0f}" if i < len(sub) else '', fontsize=7, loc='center', fontweight='normal')
        for ax in axs.ravel()[len(tr):]: ax.axis('off')
        fig.suptitle(f'{k}: hand paths (orange = excluded stretch; a = agency rating)', fontsize=10)
        fig.tight_layout(); fig.savefig(os.path.join(fd, 'trajectories', f'{k}.png'), dpi=70); plt.close(fig)

# ----------------------------------------------------------------------------------------------------- #
# models
# ----------------------------------------------------------------------------------------------------- #
def fit_models(T, P, say, min_n):
    try: import statsmodels.formula.api as smf
    except ImportError: say('statsmodels not installed: skipping models (pip install statsmodels)'); return
    warnings.simplefilter('ignore')          # statsmodels re-enables its own warnings on import
    inc = P.loc[P.include, 'key']
    d = T[(T.phase == 'main') & ~T.flash & ~T.exclude_stretch & T.key.isin(inc)].copy()
    d['delay_s'] = d.delay_ms / 1000
    d['stretch_c'] = d.stretch_index - d.stretch_index.mean()
    for c in ['radial_error_px', 'laps_per_s']: d[c + '_c'] = d[c] - d[c].mean()
    n = d.key.nunique()
    say(f'\n=== Models (main, non-flash, kept stretches; {n} included participant(s), {len(d)} stretches) ===')
    say('Covariates: tracing error and pace (centred), stretch number (centred) for within-session drift.')
    if n < min_n:
        say(f'Fewer than {min_n} included participants: mixed models are not identifiable (the random-effect '
            f'variance collapses), so only per-participant regressions are shown.')
        for k, g in d.groupby('key'):
            m = smf.ols('agency ~ delay_s + radial_error_px + laps_per_s + stretch_index', g).fit()
            say(f'\n[{k}] OLS  agency ~ delay + error + pace + stretch')
            say(m.summary2().tables[1].round(3).to_string())
        return

    def mixed(formula, data, slope=True):
        for re in (['~delay_s'] if slope else []) + [None]:
            try:
                kw = dict(groups=data['key']);
                if re: kw['re_formula'] = re
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    r = smf.mixedlm(formula, data, **kw).fit(reml=True, method=['lbfgs', 'powell'])
                if r.converged: return r, ('random intercept + delay slope' if re else 'random intercept')
            except Exception: pass
        return None, 'did not converge'

    rhs = 'delay_s + radial_error_px_c + laps_per_s_c + stretch_c'
    r, kind = mixed(f'agency ~ {rhs}', d)
    say(f'\nH1  agency ~ {rhs}   [{kind}]')
    if r is not None: say(r.summary().tables[1].to_string())
    for sh in ['sampen_speed', 'rqa_det']:
        if sh not in d or d[sh].notna().sum() < 20: continue
        dd = d.dropna(subset=[sh]).copy()
        r, kind = mixed(f'{sh} ~ {rhs}', dd, slope=False)
        say(f'\nH2  {sh} ~ {rhs}   [{kind}]')
        if r is not None: say(r.summary().tables[1].to_string())
        dd[sh + '_w'] = dd[sh] - dd.groupby('key')[sh].transform('mean')    # within-person component
        r, kind = mixed(f'agency ~ {sh}_w + {rhs}', dd)
        say(f'\nH3  agency ~ {sh}_w (person-centred) + {rhs}   [{kind}]')
        if r is not None: say(r.summary().tables[1].to_string())

# ----------------------------------------------------------------------------------------------------- #
QC = {}
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('inputs', nargs='+', help='JSON files and/or folders')
    ap.add_argument('--out', default='results', help='output folder (default: results)')
    ap.add_argument('--ring-radius', type=float, default=180, help='ring radius for v1 files (v2 records it)')
    ap.add_argument('--canvas', type=float, default=600, help='canvas size for v1 files (v2 records it)')
    ap.add_argument('--ring-tol', type=float, default=40, help='px from the ring that counts as off it')
    ap.add_argument('--max-off-ring', type=float, default=.25)
    ap.add_argument('--max-backward', type=float, default=.15)
    ap.add_argument('--min-laps-per-s', type=float, default=.15)
    ap.add_argument('--max-laps-per-s', type=float, default=.75)
    ap.add_argument('--exclude-slow', action='store_true', help='also exclude stretches slower than the min pace')
    ap.add_argument('--min-kept', type=float, default=.70, help='min share of main stretches kept per participant')
    ap.add_argument('--keep-trackpad', action='store_true')
    ap.add_argument('--include-dev', action='store_true', help='keep ?dev=1 / short-stretch test sessions')
    ap.add_argument('--no-shadows', action='store_true', help='skip SampEn/RQA (much faster)')
    ap.add_argument('--no-figures', action='store_true')
    ap.add_argument('--boot', type=int, default=500, help='bootstrap resamples for each PSE CI (0 = none)')
    ap.add_argument('--min-mixed', type=int, default=6, help='min included participants before mixed models')
    ap.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()
    QC.update(min_lps=args.min_laps_per_s, max_lps=args.max_laps_per_s, max_off=args.max_off_ring)
    os.makedirs(args.out, exist_ok=True)
    lines = []
    def say(s=''): print(s); lines.append(str(s))

    files = []
    for x in args.inputs:
        files += sorted(glob.glob(os.path.join(x, '**', '*.json'), recursive=True)) if os.path.isdir(x) else [x]
    files = [f for f in files if not os.path.basename(f).startswith('_')]
    if not files: sys.exit('no .json files found')
    print(f'reading {len(files)} file(s){"" if args.no_shadows else " (computing complexity shadows; --no-shadows to skip)"} ...')
    with ProcessPoolExecutor(args.jobs) as ex: res = list(ex.map(_parse, [(f, args) for f in files]))
    sessions, trials, src = [], [], {}
    for f, r in zip(files, res):
        if r[0] == 'ERROR': say(f'!! could not read {r[1]}: {r[2]}'); continue
        s, tr = r
        s['key'] = s['pid'] if s['pid'] not in [x['pid'] for x in sessions] else f"{s['pid']}_{s['session']}"
        if any(x['pid'] == s['pid'] and x['session'] == s['session'] for x in sessions):
            say(f'!! duplicate of {s["pid"]} session {s["session"]} in {f}: skipped'); continue
        for t in tr: t['key'] = s['key']
        sessions.append(s); trials += tr; src[s['key']] = f
    T = pd.DataFrame(trials); P = pd.DataFrame(sessions)
    if T.empty: sys.exit('no tracing stretches found')

    # ---- stretch QC ----
    T['flag_off_ring'] = T.off_ring_frac > args.max_off_ring
    T['flag_backward'] = T.backward_frac > args.max_backward
    T['flag_fast'] = T.laps_per_s > args.max_laps_per_s
    T['flag_slow'] = T.laps_per_s < args.min_laps_per_s
    T['exclude_stretch'] = T.flag_off_ring | T.flag_backward | T.flag_fast | (T.flag_slow & args.exclude_slow)

    # ---- participant summaries ----
    delays = sorted(T.loc[T.phase == 'main', 'delay_ms'].dropna().unique().astype(int).tolist())
    recs = []
    from scipy.stats import spearmanr
    for _, s in P.iterrows():
        g = T[(T.key == s.key) & (T.phase == 'main')]
        nf = g[~g.flash]; kept = nf[~nf.exclude_stretch]
        r = dict(key=s.key, n_main=len(g), kept_frac=(~g.exclude_stretch).mean() if len(g) else 0,
                 frame_ms=g.frame_ms.median(), refresh_hz=round(1000 / g.frame_ms.median()) if len(g) else np.nan,
                 radial_error_med=g.radial_error_px.median(), laps_per_s_med=g.laps_per_s.median(),
                 off_ring_med=g.off_ring_frac.median(), slow_frac=g.flag_slow.mean(),
                 feedback_frac=g.feedback_shown.mean() if g.feedback_shown.notna().any() else np.nan)
        for d in delays: r[f'agency_{d}'] = kept.loc[kept.delay_ms == d, 'agency'].mean()
        r['agency_0_flash'] = g.loc[g.flash & ~g.exclude_stretch, 'agency'].mean()
        if len(kept) >= 8 and kept.delay_ms.nunique() >= 3:
            r['pse_ms'], r['slope_ms'], r['pse_lo'], r['pse_hi'] = fit_logistic(kept.delay_ms, kept.agency, args.boot)
            r['spearman_rho'], r['spearman_p'] = spearmanr(kept.delay_ms, kept.agency)
            mid = kept[kept.delay_ms.isin([d for d in delays if 0 < d < max(delays)])]
            r['drift_per_stretch'] = drift_slope(mid)
        reasons = []
        if not s.completed: reasons.append('incomplete')
        if s.dev and not args.include_dev: reasons.append('dev/test session')
        if s.device_switch == 'kept_trackpad' and not args.keep_trackpad: reasons.append('trackpad')
        if r['kept_frac'] < args.min_kept: reasons.append(f"only {r['kept_frac']:.0%} stretches usable")
        r['include'] = not reasons; r['exclude_reason'] = '; '.join(reasons)
        recs.append(r)
    P = P.merge(pd.DataFrame(recs), on='key')
    for c in ['pse_ms', 'slope_ms', 'pse_lo', 'pse_hi', 'spearman_rho', 'spearman_p', 'drift_per_stretch']:
        if c not in P: P[c] = np.nan

    # ---- write tables ----
    tcols = ['key', 'pid', 'session', 'study', 'phase', 'block', 'stretch_index', 'delay_ms', 'flash', 'agency',
             'rating_rt_ms', 'radial_error_px', 'laps', 'laps_per_s', 'off_ring_frac', 'backward_frac', 'direction',
             'hand_dot_sep_px', 'sampen_speed', 'rqa_det', 'frame_ms', 'frame_ms_sd', 'n_samples', 'duration_s',
             'feedback_shown', 'flag_off_ring', 'flag_backward', 'flag_fast', 'flag_slow', 'exclude_stretch']
    T = T.merge(P[['key', 'include']].rename(columns={'include': 'participant_included'}), on='key')
    T[[c for c in tcols if c in T] + ['participant_included']].to_csv(os.path.join(args.out, 'trials.csv'), index=False)
    P.drop(columns=['user_agent']).to_csv(os.path.join(args.out, 'participants.csv'), index=False)

    # ---- report ----
    pd.set_option('display.width', 200); pd.set_option('display.max_columns', 30)
    say(f'\n=== {len(P)} session(s), {len(T)} stretches; {P.include.sum()} participant(s) included ===')
    say(P[['key', 'study', 'refresh_hz', 'device', 'hand', 'debrief', 'radial_error_med', 'laps_per_s_med',
           'kept_frac', 'include', 'exclude_reason']].round(3).to_string(index=False))
    slow = P.loc[P.slow_frac > .5, 'key'].tolist()
    if slow: say(f'\nNote: {", ".join(slow)} traced slower than {args.min_laps_per_s} laps/s on most stretches '
                 f'(kept; use --exclude-slow to drop). Slow tracing shrinks the visible hand-dot gap at every delay.')
    say('\n=== Mean agency by delay (main, non-flash, kept stretches) ===')
    say(P[['key'] + [f'agency_{d}' for d in delays] + ['agency_0_flash']].round(1).to_string(index=False))
    say('\n=== Per-participant psychometric fit: agency = 100 / (1 + exp((delay - PSE) / slope)) ===')
    say(P[['key', 'include', 'pse_ms', 'pse_lo', 'pse_hi', 'slope_ms', 'spearman_rho', 'spearman_p',
           'drift_per_stretch']].round(3).to_string(index=False))
    inc = P[P.include]
    if len(inc) > 1:
        say(f'\nIncluded participants: PSE median {inc.pse_ms.median():.0f} ms (IQR {inc.pse_ms.quantile(.25):.0f}–'
            f'{inc.pse_ms.quantile(.75):.0f}); drift at intermediate delays median {inc.drift_per_stretch.median():+.2f} points/stretch')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        fit_models(T, P, say, args.min_mixed)
    with open(os.path.join(args.out, 'report.txt'), 'w') as f: f.write('\n'.join(lines) + '\n')
    if not args.no_figures:
        make_figures(T, P, args.out, delays, args.ring_radius, args.canvas, src)
    print(f'\nwrote {args.out}/trials.csv, participants.csv, report.txt' + ('' if args.no_figures else ', figures/'))

if __name__ == '__main__':
    main()
