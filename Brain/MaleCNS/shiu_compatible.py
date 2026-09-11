"""Experimental Shiu-compatible LIF dynamics applied to the MaleCNS connectome.

Not an official MaleCNS simulator. Float64 exact linear state update; Brian2
schedule: state update, threshold, delayed synapses, reset. Fixed external
events are applied during synapses, hence affect thresholds on the next tick.
"""
import numpy as np


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
        self.tick = 0
        self.pending = [[] for _ in range(19)]

    def step(self, ticks, events=None, record=False):
        events = events or {}
        spikes, states = [], []
        count = np.zeros(len(self.v), dtype=np.int64)
        a, b = np.exp(-self.dt / 20), np.exp(-self.dt / 5)
        c = (a-b)/3
        for _ in range(ticks):
            k = self.tick
            active = (k-self.last) >= self.rfc
            self.v[active] = -52 + (self.v[active]+52)*a + self.g[active]*c
            self.g[active] *= b
            fired = np.flatnonzero(active & (self.v > -45))
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
