"""Experimental Shiu-compatible LIF dynamics applied to the MaleCNS connectome.

Not an official MaleCNS simulator. Float64 exact linear state update; Brian2
schedule: state update, threshold, delayed synapses, reset. Fixed external
events are applied during synapses, hence affect thresholds on the next tick.
"""
import numpy as np

if __package__:
    from .lif_kernels import run_window, update_state_and_extract_fired
else:
    from lif_kernels import run_window, update_state_and_extract_fired


class MaleCNSShiuCompatibleLIF:
    def __init__(self, n, indptr, post, weights_mv, stimulated=(), dt=0.1):
        if dt != 0.1:
            raise ValueError('Validated variant requires dt=0.1 ms')
        self.indptr, self.post, self.weights = indptr, post, weights_mv
        self.dt = dt
        self.v = np.full(n, -52., dtype=np.float64)
        self.g = np.zeros(n, dtype=np.float64)
        self.last = np.full(n, -1000000, dtype=np.int64)
        self.rfc = np.full(n, 22, dtype=np.int64)
        self.rfc[list(stimulated)] = 0
        self._active = np.empty(n, dtype=np.bool_)
        self._fired = np.empty(n, dtype=np.int64)
        self._pending_indices = np.empty((19, n), dtype=np.int64)
        self._pending_counts = np.zeros(19, dtype=np.int64)
        self.tick = 0
        self.pending = [[] for _ in range(19)]

    def _load_pending_ring(self):
        matches_ring = True
        maximum = 0
        for slot, values in enumerate(self.pending):
            size = len(values)
            maximum = max(maximum, size)
            if size != self._pending_counts[slot]:
                matches_ring = False
            for offset, value in enumerate(values):
                if (not isinstance(value, (int, np.integer)) or isinstance(value, (bool, np.bool_))
                        or value < 0 or value >= len(self.v)):
                    raise ValueError('pending indices must be in-range integers')
                if matches_ring and value != self._pending_indices[slot, offset]:
                    matches_ring = False
        if matches_ring:
            return
        required = maximum + len(self.v)
        capacity = self._pending_indices.shape[1]
        if required > capacity:
            self._pending_indices = np.empty((19, max(required, capacity * 2)), dtype=np.int64)
        self._pending_counts.fill(0)
        for slot, values in enumerate(self.pending):
            size = len(values)
            if size:
                self._pending_indices[slot, :size] = values
            self._pending_counts[slot] = size

    def _store_pending_ring(self):
        for slot in range(19):
            size = int(self._pending_counts[slot])
            self.pending[slot] = self._pending_indices[slot, :size].tolist()

    def step_window(self, ticks, event_offsets, event_indices, observed, count_buffer=None):
        """Run a non-recording window with Python-generated flattened events.

        ``event_offsets`` has one entry per local tick plus the endpoint.  The
        public pending lists remain observable and settable between calls.
        """
        if not isinstance(ticks, (int, np.integer)) or isinstance(ticks, (bool, np.bool_)) or ticks < 0:
            raise ValueError('ticks must be a non-negative integer')
        ticks = int(ticks)
        for name, value in (('event_offsets', event_offsets), ('event_indices', event_indices), ('observed', observed)):
            if not isinstance(value, np.ndarray) or value.ndim != 1 or not np.issubdtype(value.dtype, np.integer):
                raise ValueError(f'{name} must be a one-dimensional integer ndarray')
        if len(event_offsets) != ticks + 1:
            raise ValueError('event offsets must cover exactly the requested ticks')
        if event_offsets[0] != 0 or event_offsets[-1] != len(event_indices):
            raise ValueError('event offsets do not match event indices')
        if (np.any(event_offsets < 0) or np.any(event_offsets > len(event_indices))
                or np.any(event_offsets[1:] < event_offsets[:-1])):
            raise ValueError('event offsets must be monotonic in range')
        if np.any(event_indices < 0) or np.any(event_indices >= len(self.v)):
            raise ValueError('event indices must be in range')
        if np.any(observed < 0) or np.any(observed >= len(self.v)):
            raise ValueError('observed indices must be in range')
        if count_buffer is not None and (not isinstance(count_buffer, np.ndarray)
                                         or count_buffer.dtype != np.int64
                                         or count_buffer.ndim != 1
                                         or len(count_buffer) != len(self.v)):
            raise ValueError('count_buffer must be an int64 vector matching neuron count')
        count = np.zeros(len(self.v), dtype=np.int64) if count_buffer is None else count_buffer
        sums = np.empty((2, len(observed)), dtype=np.float64)
        self._load_pending_ring()
        a, b = np.exp(-self.dt / 20), np.exp(-self.dt / 5)
        c = (a-b)/3
        run_window(self.v, self.g, self.last, self.rfc, self.indptr, self.post, self.weights,
                   self.tick, ticks, a, b, c, self._active, self._fired,
                   self._pending_indices, self._pending_counts, event_offsets, event_indices,
                   observed, count, sums)
        self.tick += ticks
        self._store_pending_ring()
        return count, sums

    def step(self, ticks, events=None, record=False, count_buffer=None):
        events = events or {}
        spikes, states = [], []
        count = np.zeros(len(self.v), dtype=np.int64) if count_buffer is None else count_buffer
        a, b = np.exp(-self.dt / 20), np.exp(-self.dt / 5)
        c = (a-b)/3
        for _ in range(ticks):
            k = self.tick
            fired_count = update_state_and_extract_fired(
                self.v, self.g, self.last, self.rfc, k, a, b, c,
                self._active, self._fired)
            active = self._active
            fired = self._fired[:fired_count]
            self.last[fired] = k
            count[fired] += 1
            if record:
                spikes.extend((int(i), k) for i in fired)
            self.pending[(k+18) % 19].extend(map(int, fired))
            for pre in self.pending[k % 19]:
                lo, hi = self.indptr[pre:pre+2]
                targets = self.post[lo:hi]
                enabled = active[targets]
                np.add.at(self.g, targets[enabled], self.weights[lo:hi][enabled])
            self.pending[k % 19].clear()
            if k in events:
                np.add.at(self.v, events[k], 68.75)
            self.v[fired] = -52
            self.g[fired] = 0
            if record:
                states.append((self.v.copy(), self.g.copy()))
            self.tick += 1
        return count, spikes, states
