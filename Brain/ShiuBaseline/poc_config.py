"""Configuration shared by the v630/v783 motor-output PoC.

The upstream model remains unchanged.  Dataset paths, sensory IDs, and
descending-neuron IDs live here so they are not scattered through runners or
decoders.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict


REPO_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class DatasetConfig:
    """Filesystem configuration for one FlyWire materialization."""

    name: str
    completeness_path: Path
    connectivity_path: Path
    result_root: Path


DATASETS: Dict[str, DatasetConfig] = {
    "v630": DatasetConfig(
        name="v630",
        completeness_path=REPO_ROOT / "2023_03_23_completeness_630_final.csv",
        connectivity_path=REPO_ROOT / "2023_03_23_connectivity_630_final.parquet",
        result_root=REPO_ROOT / "results" / "codex_run" / "v630",
    ),
    "v783": DatasetConfig(
        name="v783",
        completeness_path=REPO_ROOT / "Completeness_783.csv",
        connectivity_path=REPO_ROOT / "Connectivity_783.parquet",
        result_root=REPO_ROOT / "results" / "codex_run" / "v783",
    ),
}


# The IDs used by the upstream example notebook.
SUGAR_SENSORY_NEURON_IDS = (
    720575940624963786,
    720575940630233916,
    720575940637568838,
    720575940638202345,
    720575940617000768,
    720575940630797113,
    720575940632889389,
    720575940621754367,
    720575940621502051,
    720575940640649691,
    720575940639332736,
    720575940616885538,
    720575940639198653,
    720575940620900446,
    720575940617937543,
    720575940632425919,
    720575940633143833,
    720575940612670570,
    720575940628853239,
    720575940629176663,
    720575940611875570,
)


DESCENDING_NEURON_IDS = {
    "DNa02_R": 720575940604737708,
    "DNa02_L": 720575940629327659,
    "DNa01_R": 720575940644438551,
    "DNa01_L": 720575940627787609,
    "DNp09": 720575940635872101,
}


# Fixed upstream groups from the completed motor-DN search. These are reused
# by the persistent-brain smoke test; no new candidate search is performed.
MOTOR_DN_STIMULUS_GROUPS = {
    "top5_DNa02_R": (
        720575940630085583,
        720575940614403178,
        720575940620686964,
        720575940623019544,
        720575940607982428,
    ),
    "top5_DNa02_L": (
        720575940620918789,
        720575940609097429,
        720575940611385806,
        720575940620842111,
        720575940639182424,
    ),
    "top5_DNp09": (
        720575940623953900,
        720575940613221585,
        720575940613039795,
        720575940615012667,
        720575940627239482,
    ),
}


def get_dataset(name: str) -> DatasetConfig:
    """Return a configured dataset or raise a useful error."""

    try:
        return DATASETS[name]
    except KeyError as exc:
        choices = ", ".join(sorted(DATASETS))
        raise ValueError(f"Unknown dataset {name!r}; choose one of: {choices}") from exc
