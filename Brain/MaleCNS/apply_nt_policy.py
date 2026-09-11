"""Apply an explicit transmitter policy to the disk-backed structural graph."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource

import numpy as np
import pyarrow.feather as feather


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--nt", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    category_sign = {
        name: entry["sign"] for name, entry in policy["categories"].items()
    }
    if any(value is None for value in category_sign.values()):
        raise RuntimeError("policy contains unresolved signs")
    if any(value not in (-1, 0, 1) for value in category_sign.values()):
        raise RuntimeError("signs must be -1, 0, or 1")

    body_ids = np.load(args.graph / "body_ids.npy", mmap_mode="r")
    pre = np.load(args.graph / "pre_index.npy", mmap_mode="r")
    weights = np.load(args.graph / "synapse_count.npy", mmap_mode="r")
    nt = feather.read_table(args.nt, columns=["body", policy["sourceColumn"]])
    nt_ids = nt["body"].to_numpy(zero_copy_only=False)
    nt_values = np.asarray(nt[policy["sourceColumn"]].to_pylist(), dtype=object)
    order = np.argsort(nt_ids)
    nt_ids = nt_ids[order]
    nt_values = nt_values[order]
    positions = np.searchsorted(nt_ids, body_ids)
    present = positions < len(nt_ids)
    matched = np.zeros(len(body_ids), dtype=bool)
    matched[present] = nt_ids[positions[present]] == body_ids[present]
    neuron_categories = np.full(len(body_ids), "missing", dtype=object)
    neuron_categories[matched] = nt_values[positions[matched]]

    unexpected = sorted(set(map(str, np.unique(neuron_categories))) - set(category_sign))
    if unexpected:
        raise RuntimeError(f"policy lacks categories: {unexpected}")
    neuron_signs = np.asarray([category_sign[str(value)] for value in neuron_categories], dtype=np.int8)

    args.output.mkdir(parents=True, exist_ok=True)
    signs = np.lib.format.open_memmap(
        args.output / "sign.npy", mode="w+", dtype=np.int8, shape=(len(pre),)
    )
    rows_by_category: Counter[str] = Counter()
    synapses_by_category: Counter[str] = Counter()
    chunk_size = 2_000_000
    for start in range(0, len(pre), chunk_size):
        stop = min(start + chunk_size, len(pre))
        pre_chunk = np.asarray(pre[start:stop])
        sign_chunk = neuron_signs[pre_chunk]
        signs[start:stop] = sign_chunk
        categories = neuron_categories[pre_chunk]
        weight_chunk = np.asarray(weights[start:stop])
        for category in np.unique(categories):
            mask = categories == category
            key = str(category)
            rows_by_category[key] += int(np.count_nonzero(mask))
            synapses_by_category[key] += int(weight_chunk[mask].sum(dtype=np.int64))
    signs.flush()

    positive = int(np.count_nonzero(signs == 1))
    negative = int(np.count_nonzero(signs == -1))
    inactive = int(np.count_nonzero(signs == 0))
    payload = {
        "capturedAtUtc": datetime.now(timezone.utc).isoformat(),
        "datasetId": policy["datasetId"],
        "policyId": policy["policyId"],
        "policySha256": sha256(args.policy),
        "structuralEdgeCount": int(len(pre)),
        "effectiveEdgeCount": positive + negative,
        "positiveEdgeCount": positive,
        "negativeEdgeCount": negative,
        "inactiveEdgeCount": inactive,
        "rowsByConsensusNt": dict(sorted(rows_by_category.items())),
        "synapseCountByConsensusNt": dict(sorted(synapses_by_category.items())),
        "representation": "structural pre/post/weight arrays plus per-edge int8 sign",
        "signedDynamicsReady": True,
        "physiologicallyValidated": False,
        "peakProcessRssBytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
    }
    (args.output / "signed_graph_manifest.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote signs for {len(pre)} edges; effective={positive + negative}")


if __name__ == "__main__":
    main()
