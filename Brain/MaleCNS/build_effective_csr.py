"""Convert the signed structural arrays into a presynaptic CSR runtime graph."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import resource

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--signed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    body_ids = np.load(args.graph / "body_ids.npy", mmap_mode="r")
    pre = np.load(args.graph / "pre_index.npy", mmap_mode="r")
    post = np.load(args.graph / "post_index.npy", mmap_mode="r")
    count = np.load(args.graph / "synapse_count.npy", mmap_mode="r")
    sign = np.load(args.signed / "sign.npy", mmap_mode="r")
    if not (len(pre) == len(post) == len(count) == len(sign)):
        raise RuntimeError("structural and sign arrays differ in length")

    neuron_count = len(body_ids)
    effective = sign != 0
    edge_count = int(np.count_nonzero(effective))
    degree = np.bincount(np.asarray(pre[effective]), minlength=neuron_count).astype(np.int64)
    indptr = np.empty(neuron_count + 1, dtype=np.int64)
    indptr[0] = 0
    np.cumsum(degree, out=indptr[1:])

    args.output.mkdir(parents=True, exist_ok=True)
    np.save(args.output / "body_ids.npy", np.asarray(body_ids))
    np.save(args.output / "indptr.npy", indptr)
    post_out = np.lib.format.open_memmap(
        args.output / "post_index.npy", mode="w+", dtype=np.int32, shape=(edge_count,)
    )
    signed_count_out = np.lib.format.open_memmap(
        args.output / "signed_synapse_count.npy", mode="w+", dtype=np.int64, shape=(edge_count,)
    )
    cursor = indptr[:-1].copy()
    chunk = 2_000_000
    for start in range(0, len(pre), chunk):
        stop = min(start + chunk, len(pre))
        mask = np.asarray(effective[start:stop])
        pre_chunk = np.asarray(pre[start:stop])[mask]
        post_chunk = np.asarray(post[start:stop])[mask]
        signed_chunk = np.asarray(count[start:stop])[mask] * np.asarray(sign[start:stop])[mask]
        order = np.argsort(pre_chunk, kind="stable")
        pre_chunk = pre_chunk[order]
        post_chunk = post_chunk[order]
        signed_chunk = signed_chunk[order]
        unique_pre, starts = np.unique(pre_chunk, return_index=True)
        for index, pre_index in enumerate(unique_pre):
            left = starts[index]
            right = starts[index + 1] if index + 1 < len(starts) else len(pre_chunk)
            target = int(cursor[pre_index])
            size = right - left
            post_out[target:target + size] = post_chunk[left:right]
            signed_count_out[target:target + size] = signed_chunk[left:right]
            cursor[pre_index] += size
    post_out.flush(); signed_count_out.flush()
    if not np.array_equal(cursor, indptr[1:]):
        raise RuntimeError("CSR fill counts do not match degree scan")

    manifest = {
        "capturedAtUtc": datetime.now(timezone.utc).isoformat(),
        "datasetId": "male-cns:v1.0",
        "representation": "presynaptic CSR of dynamically effective PoC edges",
        "neuronCount": neuron_count,
        "effectiveEdgeCount": edge_count,
        "positiveEdgeCount": int(np.count_nonzero(sign == 1)),
        "negativeEdgeCount": int(np.count_nonzero(sign == -1)),
        "indptrDtype": "int64",
        "postIndexDtype": "int32",
        "signedSynapseCountDtype": "int64",
        "peakProcessRssBytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote CSR with N={neuron_count}, E={edge_count}")


if __name__ == "__main__":
    main()
