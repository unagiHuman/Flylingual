#!/usr/bin/env python3
"""Inspect Arrow IPC/Feather v2 metadata and a small sample; never build a graph.
Requires pyarrow. Default reads at most the first record batch for samples.
--count-rows scans all batches sequentially, not all rows as Python objects.
"""
from __future__ import annotations
import argparse
import gc
import json
from pathlib import Path
import sys

def safe_value(value):
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2 ** 53 - 1:
        return str(value)
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    if isinstance(value, dict):
        return {str(k): safe_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_value(v) for v in value]
    return value

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('paths', nargs='+', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--sample-rows', type=int, default=3)
    ap.add_argument('--count-rows', action='store_true')
    args = ap.parse_args()
    if not 0 <= args.sample_rows <= 20:
        ap.error('--sample-rows must be between 0 and 20')
    try:
        import pyarrow as pa
        import pyarrow.ipc as ipc
    except ImportError:
        raise RuntimeError('pyarrow is required. Use the cloned, verified brian2 environment; do not upgrade the original environment.')
    reports = []
    for path in args.paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        with pa.memory_map(str(path), 'r') as mapped:
            reader = ipc.open_file(mapped)
            metadata = reader.schema.metadata or {}
            item = {
                'path': str(path.resolve()), 'fileBytes': path.stat().st_size,
                'format': 'arrow-ipc-file/feather-v2',
                'schema': [{'name': f.name, 'type': str(f.type), 'nullable': f.nullable} for f in reader.schema],
                'schemaMetadata': safe_value({k.decode('utf-8', errors='replace'): v for k, v in metadata.items()}),
                'recordBatchCount': reader.num_record_batches,
                'rowCount': None,
                'sample': [],
            }
            if reader.num_record_batches and args.sample_rows:
                batch = reader.get_batch(0)
                item['sample'] = safe_value(batch.slice(0, args.sample_rows).to_pylist())
                del batch
            if args.count_rows:
                count = 0
                for i in range(reader.num_record_batches):
                    batch = reader.get_batch(i)
                    count += batch.num_rows
                    del batch
                item['rowCount'] = count
            reports.append(item)
            del reader
        gc.collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'files': reports}, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    print(f'Wrote {args.output}')
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
