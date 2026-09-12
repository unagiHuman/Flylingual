"""Compiled kernels for the Shiu-compatible MaleCNS LIF runtime.

Only the independent per-neuron state update lives here.  Synaptic scatter
remains in ``shiu_compatible`` because its ``np.add.at`` ordering is part of
the validated behavior.
"""
from numba import njit


@njit(cache=True, fastmath=False, nogil=True)
def update_state_and_extract_fired(v, g, last, rfc, tick, a, b, c,
                                   active, fired):
    """Update active neurons and return the ascending fired-index count.

    ``active`` records the tick-start refractory decision for later delayed
    synapse delivery.  The scalar statements deliberately match the existing
    NumPy operation order.
    """
    fired_count = 0
    for neuron in range(v.size):
        is_active = (tick - last[neuron]) >= rfc[neuron]
        active[neuron] = is_active
        if is_active:
            x = v[neuron] + 52
            x = x * a
            x = -52 + x
            y = g[neuron] * c
            v[neuron] = x + y
            g[neuron] = g[neuron] * b
            if v[neuron] > -45:
                fired[fired_count] = neuron
                fired_count += 1
    return fired_count
