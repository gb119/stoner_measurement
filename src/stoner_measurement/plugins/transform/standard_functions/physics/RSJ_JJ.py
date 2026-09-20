"""An RSJ Josephson Junction fit with asymmetric Ic."""

import numpy as np


def fit(current, Ic_p, Ic_n, Rn, V_offset):
    r"""Implement a simple noiseless RSJ model."""
    normal_p = np.sign(current) * np.sqrt(np.abs(current**2 - Ic_p**2)) * Rn
    normal_n = np.sign(current) * np.real(np.sqrt(current**2 - Ic_n**2)) * Rn
    p_branch = np.where(current > Ic_p, normal_p, np.zeros_like(current))
    n_branch = np.where(current < Ic_n, normal_n, p_branch)
    return n_branch + V_offset


def p0(current, V):
    """Guess parameters as gamma=2, H_k=0, M_s~(pi.f)^2/(mu_0^2.H)-H."""

    v_offset = V[np.abs(current) < current.max() / 10].mean()
    v = V - v_offset
    current = np.where(np.isclose(current, 0), 1e-12, current)
    Rn = (V / current)[np.abs(v) > v.max() / 2].mean()
    Ic = current[np.abs(v) < v.max() / 20]
    Ic = 0.5 * (Ic.max() - Ic.min())
    return Ic, -Ic, Rn, v_offset
