"""Persistent game-facing controller for the FlyWire whole-brain model.

The controller owns one Brian2 network for its lifetime. Actions only change
the rates of the fixed upstream Poisson inputs; they never rebuild the model
or reset neuron, synapse, or refractory state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import random
import time
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd
from brian2 import (
    Hz,
    Network,
    PoissonGroup,
    SpikeMonitor,
    Synapses,
    defaultclock,
    ms,
    prefs,
    second,
    start_scope,
)

from model import create_model, default_params
from poc_config import DESCENDING_NEURON_IDS, MOTOR_DN_STIMULUS_GROUPS, get_dataset


class Action(str, Enum):
    """The six game-level input states exposed by the controller."""

    STOP = "STOP"
    FORWARD = "FORWARD"
    TURN_R = "TURN_R"
    TURN_L = "TURN_L"
    FORWARD_R = "FORWARD_R"
    FORWARD_L = "FORWARD_L"


ACTION_TO_GROUPS: Mapping[Action, tuple[str, ...]] = {
    Action.STOP: (),
    Action.FORWARD: ("F",),
    Action.TURN_R: ("R",),
    Action.TURN_L: ("L",),
    Action.FORWARD_R: ("F", "R"),
    Action.FORWARD_L: ("F", "L"),
}

GROUP_TO_CONFIG_KEY = {
    "R": "top5_DNa02_R",
    "L": "top5_DNa02_L",
    "F": "top5_DNp09",
}
TARGET_NAMES = ("DNa02_R", "DNa02_L", "DNp09")


@dataclass(frozen=True)
class BrainFrame:
    """One measured brain window and its raw descending-neuron activity."""

    sequence: int
    brain_simulation_time_ms: float
    window_ms: float
    requested_action: str
    active_stimulus_groups: tuple[str, ...]
    active_stimulus_ids: tuple[str, ...]
    d_na02_r_hz: float
    d_na02_l_hz: float
    d_np09_hz: float
    d_na02_difference_hz: float
    d_na02_r_spike_count: int
    d_na02_l_spike_count: int
    d_np09_spike_count: int
    whole_brain_spike_count: int
    step_wall_time_ms: float
    backend: str

    def firing_rates(self) -> dict[str, float]:
        return {
            "DNa02_R": self.d_na02_r_hz,
            "DNa02_L": self.d_na02_l_hz,
            "DNp09": self.d_np09_hz,
        }

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "brainSimulationTimeMs": self.brain_simulation_time_ms,
            "windowMs": self.window_ms,
            "requestedAction": self.requested_action,
            "activeStimulusGroups": list(self.active_stimulus_groups),
            "activeStimulusIds": list(self.active_stimulus_ids),
            "DNa02_R_Hz": self.d_na02_r_hz,
            "DNa02_L_Hz": self.d_na02_l_hz,
            "DNp09_Hz": self.d_np09_hz,
            "DNa02Difference_Hz": self.d_na02_difference_hz,
            "DNa02_R_spikeCount": self.d_na02_r_spike_count,
            "DNa02_L_spikeCount": self.d_na02_l_spike_count,
            "DNp09_spikeCount": self.d_np09_spike_count,
            "wholeBrainSpikeCount": self.whole_brain_spike_count,
            "stepWallTimeMs": self.step_wall_time_ms,
            "backend": self.backend,
        }


class BrainController:
    """Persistent whole-brain emulator with a small action-based interface."""

    def __init__(
        self,
        dataset: str = "v783",
        backend: str = "cython",
        seed: int = 20260910,
        stimulus_frequency_hz: float = 100.0,
        window_ms: float = 50.0,
        repo_root: Path | None = None,
    ) -> None:
        if backend not in {"numpy", "cython"}:
            raise ValueError("backend must be numpy or cython")
        if stimulus_frequency_hz <= 0:
            raise ValueError("stimulus_frequency_hz must be positive")
        if window_ms <= 0:
            raise ValueError("window_ms must be positive")
        self.dataset_name = dataset
        self.backend = backend
        self.seed = int(seed)
        self.stimulus_frequency_hz = float(stimulus_frequency_hz)
        self.window_ms = float(window_ms)
        self.repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parent
        self._dataset = get_dataset(dataset)
        self._network: Network | None = None
        self._stimulus_source = None
        self._count_monitor = None
        self._source_index_by_root_id: dict[int, int] = {}
        self._source_ids: tuple[int, ...] = ()
        self._target_ids = {
            name: int(DESCENDING_NEURON_IDS[name]) for name in TARGET_NAMES
        }
        self._previous_target_counts = {name: 0 for name in TARGET_NAMES}
        self._previous_whole_count = 0
        self._action = Action.STOP
        self._sequence = 0
        self._initialized = False
        self.initialization_seconds: float | None = None
        self.network_rebuild_count = 0
        self.state_reset_count = 0

    @property
    def dt_ms(self) -> float:
        return float(defaultclock.dt / ms)

    @property
    def action(self) -> Action:
        return self._action

    @property
    def sequence(self) -> int:
        return self._sequence

    @property
    def target_ids(self) -> dict[str, str]:
        return {name: str(root_id) for name, root_id in self._target_ids.items()}

    @property
    def stimulus_groups(self) -> dict[str, tuple[str, ...]]:
        return {
            group: tuple(str(root_id) for root_id in MOTOR_DN_STIMULUS_GROUPS[key])
            for group, key in GROUP_TO_CONFIG_KEY.items()
        }

    def initialize(self) -> "BrainController":
        if self._initialized:
            raise RuntimeError("BrainController is already initialized")

        prefs.codegen.target = self.backend
        if self.backend == "cython":
            prefs.codegen.runtime.cython.cache_dir = str(
                self.repo_root / "results" / "codex_run" / "cython_cache"
            )
        start_scope()
        np.random.seed(self.seed)
        random.seed(self.seed)

        completeness = pd.read_csv(self._dataset.completeness_path, index_col=0)
        flywire_ids = [int(value) for value in completeness.index]
        flywire_to_index = {root_id: index for index, root_id in enumerate(flywire_ids)}
        all_source_ids = sorted(
            {
                int(root_id)
                for group_key in GROUP_TO_CONFIG_KEY.values()
                for root_id in MOTOR_DN_STIMULUS_GROUPS[group_key]
            }
        )
        missing = [
            root_id
            for root_id in list(all_source_ids) + list(self._target_ids.values())
            if root_id not in flywire_to_index
        ]
        if missing:
            raise RuntimeError(f"IDs missing from {self.dataset_name} completeness: {missing}")
        if set(all_source_ids).intersection(self._target_ids.values()):
            raise RuntimeError("a stimulus group directly contains a target DN")

        started = time.perf_counter()
        params = dict(default_params)
        params["r_poi"] = self.stimulus_frequency_hz * Hz
        params["n_run"] = 1
        neurons, synapses, unused_monitor = create_model(
            self._dataset.completeness_path,
            self._dataset.connectivity_path,
            params,
        )
        del unused_monitor

        source_indices = [flywire_to_index[root_id] for root_id in all_source_ids]
        for index in source_indices:
            neurons[index].rfc = 0 * ms
        stimulus_source = PoissonGroup(
            len(source_indices),
            rates=np.zeros(len(source_indices)) * Hz,
            name="game_controller_stimulus_source",
        )
        stimulus_synapses = Synapses(
            stimulus_source,
            neurons,
            model="w_ext : volt (constant)",
            on_pre="v_post += w_ext",
            name="game_controller_stimulus_synapses",
        )
        stimulus_synapses.connect(
            i=np.arange(len(source_indices), dtype=int),
            j=np.asarray(source_indices, dtype=int),
        )
        stimulus_synapses.w_ext = params["w_syn"] * params["f_poi"]
        count_monitor = SpikeMonitor(
            neurons, record=False, name="game_controller_count_monitor"
        )
        self._network = Network(
            neurons,
            synapses,
            stimulus_source,
            stimulus_synapses,
            count_monitor,
        )
        self._stimulus_source = stimulus_source
        self._count_monitor = count_monitor
        self._source_ids = tuple(all_source_ids)
        self._source_index_by_root_id = {
            root_id: index for index, root_id in enumerate(all_source_ids)
        }
        target_indices = {
            name: flywire_to_index[root_id]
            for name, root_id in self._target_ids.items()
        }
        self._target_indices = target_indices
        self._previous_target_counts, self._previous_whole_count = self._counts()
        self.initialization_seconds = time.perf_counter() - started
        self.network_rebuild_count = 1
        self.state_reset_count = 0
        self._initialized = True
        self.set_action(Action.STOP)
        return self

    def _require_initialized(self) -> None:
        if not self._initialized or self._network is None:
            raise RuntimeError("call initialize() before using BrainController")

    def _counts(self) -> tuple[dict[str, int], int]:
        counts = np.asarray(self._count_monitor.count[:], dtype=np.int64)
        target_counts = {
            name: int(counts[index]) for name, index in self._target_indices.items()
        }
        return target_counts, int(counts.sum())

    @staticmethod
    def _coerce_action(action: Action | str) -> Action:
        if isinstance(action, Action):
            return action
        try:
            return Action(str(action))
        except ValueError as exc:
            choices = ", ".join(item.value for item in Action)
            raise ValueError(f"unknown action {action!r}; choose one of: {choices}") from exc

    def set_action(self, action: Action | str) -> None:
        """Change input rates without resetting the persistent network."""

        self._require_initialized()
        selected = self._coerce_action(action)
        active_groups = ACTION_TO_GROUPS[selected]
        active_ids = {
            root_id
            for group in active_groups
            for root_id in MOTOR_DN_STIMULUS_GROUPS[GROUP_TO_CONFIG_KEY[group]]
        }
        rate_vector = np.zeros(len(self._source_ids), dtype=float)
        for root_id in active_ids:
            rate_vector[self._source_index_by_root_id[root_id]] = self.stimulus_frequency_hz
        self._stimulus_source.rates = rate_vector * Hz
        self._action = selected

    def step(self) -> BrainFrame:
        """Advance one window, then return measured cumulative-count deltas."""

        self._require_initialized()
        brain_start = float(self._network.t / second)
        started = time.perf_counter()
        self._network.run(self.window_ms * ms)
        wall_seconds = time.perf_counter() - started
        brain_end = float(self._network.t / second)
        current_target_counts, current_whole_count = self._counts()
        target_deltas = {
            name: current_target_counts[name] - self._previous_target_counts[name]
            for name in TARGET_NAMES
        }
        whole_delta = current_whole_count - self._previous_whole_count
        duration_seconds = brain_end - brain_start
        duration_ms = duration_seconds * 1000.0
        active_groups = ACTION_TO_GROUPS[self._action]
        active_ids = tuple(
            str(root_id)
            for group in active_groups
            for root_id in MOTOR_DN_STIMULUS_GROUPS[GROUP_TO_CONFIG_KEY[group]]
        )
        frame = BrainFrame(
            sequence=self._sequence,
            brain_simulation_time_ms=brain_end * 1000.0,
            window_ms=duration_ms,
            requested_action=self._action.value,
            active_stimulus_groups=tuple(active_groups),
            active_stimulus_ids=active_ids,
            d_na02_r_hz=target_deltas["DNa02_R"] / duration_seconds,
            d_na02_l_hz=target_deltas["DNa02_L"] / duration_seconds,
            d_np09_hz=target_deltas["DNp09"] / duration_seconds,
            d_na02_difference_hz=(
                target_deltas["DNa02_R"] - target_deltas["DNa02_L"]
            )
            / duration_seconds,
            d_na02_r_spike_count=target_deltas["DNa02_R"],
            d_na02_l_spike_count=target_deltas["DNa02_L"],
            d_np09_spike_count=target_deltas["DNp09"],
            whole_brain_spike_count=whole_delta,
            step_wall_time_ms=wall_seconds * 1000.0,
            backend=self.backend,
        )
        self._previous_target_counts = current_target_counts
        self._previous_whole_count = current_whole_count
        self._sequence += 1
        return frame

    def close(self) -> None:
        """Release references; this does not rewrite or reset a saved result."""

        self._network = None
        self._stimulus_source = None
        self._count_monitor = None
        self._initialized = False
