from brain.alphas import alpha
import numpy as np
import numpy.typing as npt

# ---------- helpers (must live in the same file) ----------
def pasteurize(a, u):
    a = a.copy()
    a[~u.astype(bool)] = np.nan
    return a

def neutralize(a):
    a0 = np.nan_to_num(a, nan=0.0, posinf=0.0, neginf=0.0)
    return a - np.mean(a0)

def scale(a):
    a0 = np.nan_to_num(a, nan=0.0, posinf=0.0, neginf=0.0)
    norm = np.linalg.norm(a0, ord=1)
    return a / norm if norm > 0 else a

# ---------- alpha ----------
TS_RANK_WINDOW = 20

@alpha(
    data=["returns"],
    store=[],
)
def ts_rank_rank_returns(data, store) -> npt.NDArray[np.float32]:
    returns = data.returns
    T, N = returns.shape

    # Step 1: cross-sectional rank of returns each day -> [0,1]
    ranked = np.full((T, N), np.nan, dtype=np.float64)
    for t in range(T):
        row = returns[t]
        valid = ~np.isnan(row)
        n_valid = int(valid.sum())
        if n_valid > 1:
            order = np.argsort(np.argsort(row[valid]))
            ranked[t, valid] = order.astype(np.float64) / (n_valid - 1)
        elif n_valid == 1:
            ranked[t, valid] = 0.5

    # Step 2: ts_rank of today within the window
    d = min(T, TS_RANK_WINDOW)
    window = ranked[-d:]
    today = window[-1]

    valid_mask = ~np.isnan(window)
    below = np.sum((window < today[np.newaxis, :]) & valid_mask, axis=0)
    total = np.sum(valid_mask, axis=0)
    signal = np.where(total > 1, below.astype(np.float64) / (total - 1), np.nan)

    # Step 3: post-processing
    signal = signal.astype(np.float32)
    signal = pasteurize(signal, data.universe[-1])
    signal = scale(neutralize(signal))
    return (-signal).astype(np.float32)
