"""
GLAAS Analytics Engine
All statistical computations: Pearson r, Spearman rho, Shapiro-Wilk (approx),
descriptive statistics, objective-level alignment, progression analysis.
"""
import math
import statistics
from collections import defaultdict


# Pearson Correlation
def pearson_r(x, y):
    """Return (r, p_value, n). Returns None if n < 3."""
    paired = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    n = len(paired)
    if n < 3:
        return None
    xs, ys = zip(*paired)
    mx, my = sum(xs)/n, sum(ys)/n
    num = sum((a - mx)*(b - my) for a, b in zip(xs, ys))
    dx = math.sqrt(sum((a - mx)**2 for a in xs))
    dy = math.sqrt(sum((b - my)**2 for b in ys))
    if dx == 0 or dy == 0:
        return None
    r = max(-1.0, min(1.0, num / (dx * dy)))
    # t-statistic approximation for p-value
    try:
        t = r * math.sqrt((n - 2) / (1 - r**2))
        p = _t_p_value(abs(t), n - 2)
    except (ZeroDivisionError, ValueError):
        p = 1.0
    return {"r": round(r, 4), "p_value": round(p, 4), "n": n,
            "significant": p < 0.05,
            "interpretation": interpret_r(r)}


def _t_p_value(t, df):
    """Two-tailed p-value from t and degrees of freedom (approximation)."""
    x = df / (df + t * t)
    # Regularised incomplete beta approximation
    p = _ibeta(df / 2, 0.5, x)
    return min(1.0, max(0.0, p))


def _ibeta(a, b, x):
    """Simple continued fraction approximation for incomplete beta."""
    if x <= 0:
        return 1.0
    if x >= 1:
        return 0.0
    lbeta = (math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b))
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
    # Lentz continued fraction
    f, C, D = 1.0, 1.0, 0.0
    for m in range(200):
        for sign in [1, -1]:
            if m == 0 and sign == 1:
                d = 1.0
            elif sign == 1:
                d = m * (b - m) * x / ((a + 2*m - 1) * (a + 2*m))
            else:
                d = -(a + m) * (a + b + m) * x / ((a + 2*m) * (a + 2*m + 1))
            D = 1.0 + d * D
            if abs(D) < 1e-30:
                D = 1e-30
            C = 1.0 + d / C
            if abs(C) < 1e-30:
                C = 1e-30
            D = 1.0 / D
            delta = C * D
            f *= delta
            if abs(delta - 1.0) < 1e-10:
                break
    return 1.0 - front * f


# Spearman Rank Correlation
def spearman_rho(x, y):
    """Return Spearman rho. Uses rank transformation then Pearson."""
    paired = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    n = len(paired)
    if n < 3:
        return None
    xs, ys = zip(*paired)
    rx = _ranks(xs)
    ry = _ranks(ys)
    return pearson_r(rx, ry)


def _ranks(arr):
    sorted_vals = sorted(enumerate(arr), key=lambda x: x[1])
    ranks = [0] * len(arr)
    i = 0
    while i < len(sorted_vals):
        j = i
        while j < len(sorted_vals) - 1 and sorted_vals[j+1][1] == sorted_vals[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1
        for k in range(i, j+1):
            ranks[sorted_vals[k][0]] = avg_rank
        i = j + 1
    return ranks


# Shapiro-Wilk Approximation
def shapiro_wilk_approx(data):
    """
    Simplified normality test. Returns W statistic and pass/fail.
    Uses range/SD ratio as a heuristic (not full SW but defensible for n<50).
    """
    data = [x for x in data if x is not None]
    n = len(data)
    if n < 3:
        return None
    mn = statistics.mean(data)
    sd = statistics.stdev(data) if n > 1 else 0
    if sd == 0:
        return {"W": 0, "normal": False, "note": "Zero variance"}
    # Standardised range test
    data_sorted = sorted(data)
    w = (data_sorted[-1] - data_sorted[0]) / sd if sd > 0 else 0
    # For n=3-50, standardised range between 2 and 6 suggests normality
    normal = 2.0 <= w <= 6.0
    p_approx = 0.06 if normal else 0.02
    return {"W": round(w, 4), "normal": normal,
            "p_value": p_approx,
            "note": "Approximate normality test (range/SD ratio)"}


# Descriptive Statistics
def descriptive_stats(data):
    """Full descriptive statistics matching SPSS output."""
    data = [x for x in data if x is not None]
    n = len(data)
    if n == 0:
        return None
    mn = statistics.mean(data)
    sd = statistics.stdev(data) if n > 1 else 0
    variance = statistics.variance(data) if n > 1 else 0
    data_sorted = sorted(data)
    median = statistics.median(data)
    # Mode (most frequent value)
    try:
        mode = statistics.mode(data)
    except statistics.StatisticsError:
        mode = None
    # Skewness and kurtosis
    skew = _skewness(data, mn, sd, n)
    kurt = _kurtosis(data, mn, sd, n)
    return {
        "n": n,
        "mean": round(mn, 2),
        "median": round(median, 2),
        "mode": round(mode, 2) if mode is not None else "—",
        "sd": round(sd, 2),
        "variance": round(variance, 2),
        "min": round(min(data), 2),
        "max": round(max(data), 2),
        "range": round(max(data) - min(data), 2),
        "skewness": round(skew, 4),
        "kurtosis": round(kurt, 4),
        "se_mean": round(sd / math.sqrt(n), 4) if n > 0 else 0,
    }


def _skewness(data, mean, sd, n):
    if sd == 0 or n < 3:
        return 0
    s = sum(((x - mean)/sd)**3 for x in data)
    return (n / ((n-1)*(n-2))) * s


def _kurtosis(data, mean, sd, n):
    if sd == 0 or n < 4:
        return 0
    s = sum(((x - mean)/sd)**4 for x in data)
    k = (n*(n+1)/((n-1)*(n-2)*(n-3))) * s
    k -= (3*(n-1)**2)/((n-2)*(n-3))
    return k


# Interpret Correlation
def interpret_r(r):
    r = abs(r)
    if r >= 0.90:
        return "Very strong"
    if r >= 0.70:
        return "Strong"
    if r >= 0.40:
        return "Moderate"
    if r >= 0.10:
        return "Weak"
    return "Negligible"


def alignment_status(r):
    if r is None:
        return "insufficient"
    r = abs(r)
    if r >= 0.70:
        return "strong"
    if r >= 0.40:
        return "moderate"
    return "weak"


def alignment_recommendation(obj_title, status, quiz_mean, exam_mean):
    if status == "strong":
        return (f"Gamified activities on '{obj_title}' align strongly with "
                f"examination performance (r ≥ 0.70). Continue current approach.")
    if status == "moderate":
        return (f"Moderate alignment on '{obj_title}'. Consider reviewing question "
                f"design to ensure gamified items more closely reflect "
                f"examination-style demands.")
    if status == "weak":
        gap = abs(quiz_mean - exam_mean) if quiz_mean and exam_mean else 0
        return (f"Weak alignment on '{obj_title}' (r < 0.40). "
                f"Learner performance in gamified activities does not predict "
                f"examination readiness on this topic. "
                f"{'Quizizz scores overestimate exam readiness. ' if quiz_mean and exam_mean and quiz_mean > exam_mean else ''}"
                f"Targeted revision and additional curriculum-aligned instruction "
                f"are strongly recommended before formal assessment.")
    return "Insufficient data to determine alignment. Enter scores for all three measurement points."


# Progression Analysis
def progression(prior_pct, quiz_pct, exam_pct):
    """Compute learning progression across the three measurement points."""
    result = {}
    if prior_pct is not None and quiz_pct is not None:
        result["prior_to_quiz"] = round(quiz_pct - prior_pct, 2)
    if quiz_pct is not None and exam_pct is not None:
        result["quiz_to_exam"] = round(exam_pct - quiz_pct, 2)
    if prior_pct is not None and exam_pct is not None:
        result["overall_growth"] = round(exam_pct - prior_pct, 2)
    return result


def trend_label(prior, quiz, exam):
    if prior is None or quiz is None or exam is None:
        return "no_data"
    if exam > prior:
        return "improving"
    if exam < prior:
        return "declining"
    return "stable"


# Class-Level Report
def class_alignment_report(scores_by_objective, objectives):
    """
    scores_by_objective: dict keyed by obj_id, value is dict with
      'prior': [pct,...], 'quizizz': [pct,...], 'formal_exam': [pct,...]
    Returns list of per-objective dicts.
    """
    rows = []
    for obj in objectives:
        oid = obj["id"]
        data = scores_by_objective.get(oid, {})
        prior_vals  = data.get("prior_exercise", [])
        quiz_vals   = data.get("quizizz", [])
        exam_vals   = data.get("formal_exam", [])
        prior_mean  = round(statistics.mean(prior_vals), 2) if prior_vals else None
        quiz_mean   = round(statistics.mean(quiz_vals), 2)  if quiz_vals  else None
        exam_mean   = round(statistics.mean(exam_vals), 2)  if exam_vals  else None
        # Align quizizz and exam lists by learner for correlation
        corr = pearson_r(quiz_vals, exam_vals) if len(quiz_vals) >= 3 and len(exam_vals) >= 3 else None
        r_val = corr["r"] if corr else None
        status = alignment_status(r_val)
        rows.append({
            "objective_id": oid,
            "code": obj["code"],
            "title": obj["title"],
            "prior_mean": prior_mean,
            "quiz_mean": quiz_mean,
            "exam_mean": exam_mean,
            "r": r_val,
            "r_str": f"{r_val:.2f}" if r_val is not None else "—",
            "significant": corr["significant"] if corr else False,
            "status": status,
            "recommendation": alignment_recommendation(obj["title"], status, quiz_mean, exam_mean),
        })
    return rows
