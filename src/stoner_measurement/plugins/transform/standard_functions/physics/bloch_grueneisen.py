"""Calculate the BlochGrueneiseen Function for fitting R(T)."""

import numpy as np
from scipy.integrate import quad

def _bgintegrand(x, n):
    """Calculate the integrand for the Bloch Grueneisen model."""
    return x**n / ((np.exp(x) - 1) * (1 - np.exp(-x)))

def fit(T, thetaD, rho0, A):
    """Calculate the BlochGrueneiseen Function for fitting R(T)."""
    n=5
    ret = np.zeros(T.shape)
    for i, t in enumerate(T):
        intg = quad(_bgintegrand, 0, thetaD / (t), (n,))[0]
        ret[i] = rho0 + A * (t / thetaD) ** n * intg
    return ret

def p0(x,data):
    """Guess some starting values - not very clever."""
    rho0 = data.min()

    t = x / x.max()
    y = data - data.min()
    t = t[y > 0.05 * y.max()]
    y = y[y > 0.05 * y.max()]
    A = np.polyfit(t, y, 1)[0]

    return 500, rho0, A
