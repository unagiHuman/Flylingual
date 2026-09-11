"""Persistent exploratory LIF dynamics over a MaleCNS CSR graph.

This adapts the Shiu-style LIF constants to MaleCNS connectivity. It is not a
physiologically validated MaleCNS model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class LifConfig:
    dt_ms: float = 0.1
    resting_mv: float = -52.0
    reset_mv: float = -52.0
    threshold_mv: float = -45.0
    membrane_tau_ms: float = 20.0
    synapse_tau_ms: float = 5.0
    refractory_ms: float = 2.2
    delay_ms: float = 1.8
    weight_per_synapse_mv: float = 0.275
    recurrent_weight_scale: float = 1.0
    external_weight_multiplier: float = 250.0


class MaleCNSBrain:
    """One-owner persistent controller with explicit stimulation and readouts."""

    def __init__(self, graph_path: Path, config: LifConfig | None = None, seed: int = 20260911):
        self.graph_path = Path(graph_path)
        self.config = config or LifConfig()
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)
        self.initialized = False
        self.body_ids: np.ndarray | None = None
        self.indptr: np.ndarray | None = None
        self.post: np.ndarray | None = None
        self.signed_count: np.ndarray | None = None
        self.v: np.ndarray | None = None
        self.g: np.ndarray | None = None
        self.refractory_steps: np.ndarray | None = None
        self.pending: np.ndarray | None = None
        self._delay_cursor = 0
        self._stimulus_indices = np.empty(0, dtype=np.int32)
        self._stimulus_rates_hz = np.empty(0, dtype=np.float64)
        self._readout_indices = np.empty(0, dtype=np.int32)
        self._readout_names: tuple[str, ...] = ()
        self._last_readout: dict[str, int] = {}
        self._blocked_posts_by_pre: dict[int, np.ndarray] = {}
        self.simulated_ms = 0.0
        self.initialization_wall_ms = 0.0

    def initialize(self) -> "MaleCNSBrain":
        if self.initialized:
            raise RuntimeError("MaleCNSBrain is already initialized")
        started = time.perf_counter()
        self.body_ids = np.load(self.graph_path / "body_ids.npy", mmap_mode="r")
        self.indptr = np.load(self.graph_path / "indptr.npy", mmap_mode="r")
        self.post = np.load(self.graph_path / "post_index.npy", mmap_mode="r")
        self.signed_count = np.load(self.graph_path / "signed_synapse_count.npy", mmap_mode="r")
        n = len(self.body_ids)
        if len(self.indptr) != n + 1 or int(self.indptr[-1]) != len(self.post):
            raise RuntimeError("invalid CSR graph")
        self.v = np.full(n, self.config.resting_mv, dtype=np.float32)
        self.g = np.zeros(n, dtype=np.float32)
        self.refractory_steps = np.zeros(n, dtype=np.int16)
        delay_slots = max(1, int(round(self.config.delay_ms / self.config.dt_ms)))
        self.pending = np.zeros((delay_slots, n), dtype=np.float32)
        self.initialized = True
        self.initialization_wall_ms = (time.perf_counter() - started) * 1000.0
        return self

    def index_for_body_id(self, body_id: int) -> int:
        if not self.initialized or self.body_ids is None:
            raise RuntimeError("call initialize() first")
        position = int(np.searchsorted(self.body_ids, int(body_id)))
        if position >= len(self.body_ids) or int(self.body_ids[position]) != int(body_id):
            raise KeyError(str(body_id))
        return position

    def set_stimulation(self, body_ids: Iterable[int], rates_hz: float | Iterable[float]) -> None:
        indices = np.asarray([self.index_for_body_id(value) for value in body_ids], dtype=np.int32)
        if np.isscalar(rates_hz):
            rates = np.full(len(indices), float(rates_hz), dtype=np.float64)
        else:
            rates = np.asarray(list(rates_hz), dtype=np.float64)
        if len(indices) != len(rates) or np.any(rates < 0):
            raise ValueError("stimulation IDs and non-negative rates must align")
        self._stimulus_indices = indices
        self._stimulus_rates_hz = rates

    def set_readouts(self, mapping: dict[str, int]) -> None:
        self._readout_names = tuple(mapping)
        self._readout_indices = np.asarray(
            [self.index_for_body_id(mapping[name]) for name in self._readout_names], dtype=np.int32
        )
        self._last_readout = {name: 0 for name in self._readout_names}

    def set_blocked_edges(self, body_id_pairs: Iterable[tuple[int, int]]) -> None:
        blocked: dict[int, list[int]] = {}
        for pre_body_id, post_body_id in body_id_pairs:
            pre_index = self.index_for_body_id(pre_body_id)
            post_index = self.index_for_body_id(post_body_id)
            blocked.setdefault(pre_index, []).append(post_index)
        self._blocked_posts_by_pre = {
            pre_index: np.asarray(post_indices, dtype=np.int32)
            for pre_index, post_indices in blocked.items()
        }

    def get_readout(self) -> dict[str, int]:
        return dict(self._last_readout)

    def step(self, duration_ms: float) -> dict[str, object]:
        if not self.initialized:
            raise RuntimeError("call initialize() first")
        steps_float = float(duration_ms) / self.config.dt_ms
        steps = int(round(steps_float))
        if duration_ms <= 0 or not np.isclose(steps, steps_float):
            raise ValueError("duration_ms must be a positive multiple of dt_ms")
        started = time.perf_counter()
        readout_counts = np.zeros(len(self._readout_indices), dtype=np.int64)
        whole_count = 0
        for _ in range(steps):
            self.g += self.pending[self._delay_cursor]
            self.pending[self._delay_cursor].fill(0)
            active = self.refractory_steps == 0
            self.g[active] += (-self.g[active] / self.config.synapse_tau_ms) * self.config.dt_ms
            self.v[active] += (
                (self.config.resting_mv - self.v[active] + self.g[active])
                / self.config.membrane_tau_ms
            ) * self.config.dt_ms
            self.g[~active] = 0.0
            self.refractory_steps[~active] -= 1
            if len(self._stimulus_indices):
                probability = self._stimulus_rates_hz * self.config.dt_ms / 1000.0
                hits = self.rng.random(len(probability)) < probability
                self.v[self._stimulus_indices[hits]] += (
                    self.config.weight_per_synapse_mv * self.config.external_weight_multiplier
                )
            spiking = np.flatnonzero((self.refractory_steps == 0) & (self.v > self.config.threshold_mv))
            if len(spiking):
                whole_count += len(spiking)
                self.v[spiking] = self.config.reset_mv
                self.g[spiking] = 0.0
                self.refractory_steps[spiking] = int(round(self.config.refractory_ms / self.config.dt_ms))
                if len(self._readout_indices):
                    readout_counts += np.isin(self._readout_indices, spiking).astype(np.int64)
                delivery_slot = self._delay_cursor
                target = self.pending[delivery_slot]
                for pre_index in spiking:
                    left = int(self.indptr[pre_index]); right = int(self.indptr[pre_index + 1])
                    if right > left:
                        posts = self.post[left:right]
                        signed_counts = self.signed_count[left:right]
                        blocked_posts = self._blocked_posts_by_pre.get(int(pre_index))
                        if blocked_posts is not None:
                            keep = ~np.isin(posts, blocked_posts)
                            posts = posts[keep]
                            signed_counts = signed_counts[keep]
                        np.add.at(
                            target,
                            posts,
                            signed_counts
                            * self.config.weight_per_synapse_mv
                            * self.config.recurrent_weight_scale,
                        )
            self._delay_cursor = (self._delay_cursor + 1) % len(self.pending)
        self.simulated_ms += steps * self.config.dt_ms
        self._last_readout = {
            name: int(readout_counts[index]) for index, name in enumerate(self._readout_names)
        }
        wall_ms = (time.perf_counter() - started) * 1000.0
        return {
            "simulatedMs": steps * self.config.dt_ms,
            "totalSimulatedMs": self.simulated_ms,
            "wallMs": wall_ms,
            "wholeNetworkSpikeCount": int(whole_count),
            "readoutSpikeCounts": self.get_readout(),
        }
