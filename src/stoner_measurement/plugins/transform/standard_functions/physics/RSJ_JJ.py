"""An RSJ Josephson Junction fit with asymmetric Ic."""
import numpy as np

def fit(I, Ic_p, Ic_n, Rn, V_offset):
    r"""Implement a simple noiseless RSJ model."""
    normal_p = np.sign(I) * np.sqrt(np.abs(I**2 - Ic_p**2)) * Rn
    normal_n = np.sign(I) * np.real(np.sqrt(I**2 - Ic_n**2)) * Rn
    p_branch = np.where(I > Ic_p, normal_p, np.zeros_like(I))
    n_branch = np.where(I < Ic_n, normal_n, p_branch)
    return n_branch + V_offset

def p0(I, V):
    """Guess parameters as gamma=2, H_k=0, M_s~(pi.f)^2/(mu_0^2.H)-H."""

    v_offset = V[np.abs(I)<I.max()/10].mean()
    v = V - v_offset
    I=np.where(np.isclose(I,0),1E-12,I)
    Rn=(V/I)[np.abs(v)>v.max()/2].mean()
    Ic=I[np.abs(v)<v.max()/20]
    Ic=0.5*(Ic.max()-Ic.min())
    return Ic,-Ic,Rn,v_offset
