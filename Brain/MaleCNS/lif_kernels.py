"""Compiled kernels for the Shiu-compatible MaleCNS LIF runtime.

The strict per-neuron update and the ordered delayed CSR scatter live here.
The scalar scatter order deliberately matches the prior ``np.add.at`` behavior
for duplicate targets.
"""
import sys
from pathlib import Path

# Numba's on-disk cache retains the importing module name. Both the package
# API and standalone Brain scripts use this file, so a cache written by either
# entry point must remain importable when the other entry point restores it.
_module_directory = Path(__file__).resolve().parent
for _import_directory in (_module_directory, _module_directory.parents[1]):
    if str(_import_directory) not in sys.path:
        sys.path.insert(0, str(_import_directory))

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


@njit(cache=True, fastmath=False, nogil=True)
def run_window(v, g, last, rfc, indptr, post, weights, tick, ticks, a, b, c,
               active, fired, pending_indices, pending_counts, event_offsets,
               event_indices, observed, count, sums):
    """Run ordered LIF ticks plus delayed CSR delivery and observed sums.

    Each scalar statement intentionally preserves the old update and scatter
    order.  ``pending_indices`` is a 19-slot firing ring; its per-slot count
    permits duplicate entries supplied through the public pending lists.
    """
    for row in range(sums.shape[0]):
        for column in range(sums.shape[1]):
            sums[row, column] = 0.0
    for local_tick in range(ticks):
        k = tick + local_tick
        fired_count = 0
        for neuron in range(v.size):
            is_active = (k - last[neuron]) >= rfc[neuron]
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
        schedule_slot = (k + 18) % 19
        schedule_count = pending_counts[schedule_slot]
        for fired_offset in range(fired_count):
            neuron = fired[fired_offset]
            last[neuron] = k
            count[neuron] += 1
            pending_indices[schedule_slot, schedule_count + fired_offset] = neuron
        pending_counts[schedule_slot] = schedule_count + fired_count
        delivery_slot = k % 19
        delivery_count = pending_counts[delivery_slot]
        for pending_offset in range(delivery_count):
            pre = pending_indices[delivery_slot, pending_offset]
            lo = indptr[pre]
            hi = indptr[pre + 1]
            for edge in range(lo, hi):
                target = post[edge]
                if active[target]:
                    g[target] = g[target] + weights[edge]
        pending_counts[delivery_slot] = 0
        for event_offset in range(event_offsets[local_tick], event_offsets[local_tick + 1]):
            target = event_indices[event_offset]
            v[target] = v[target] + 68.75
        for fired_offset in range(fired_count):
            neuron = fired[fired_offset]
            v[neuron] = -52
            g[neuron] = 0.0
        for observed_offset in range(observed.size):
            neuron = observed[observed_offset]
            sums[0, observed_offset] = sums[0, observed_offset] + v[neuron]
            sums[1, observed_offset] = sums[1, observed_offset] + g[neuron]
