"""Bounded effective-CSR path audit, not a stimulation or neural-response test."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re

import numpy as np
import pyarrow
import pyarrow.feather as feather
import pyarrow.compute as pc

if __package__:
    from .audit_affective_candidates import ROOT, COLUMNS, digest, validate_graph
else:
    from audit_affective_candidates import ROOT, COLUMNS, digest, validate_graph


def run(annotations, graph, max_intermediates=10000, max_edges=5000000, neurotransmitters=None):
    if max_intermediates < 0 or max_edges < 0:
        raise ValueError('budgets must be nonnegative')
    manifest_path = ROOT / 'Brain/MaleCNS/results/download_manifest.json'
    manifests = json.loads(manifest_path.read_text(encoding='utf-8'))['files']
    manifest = manifests['annotations']
    annotation_hash = digest(annotations)
    if annotation_hash != manifest['sha256']:
        raise ValueError('annotation does not match download manifest')
    rows = feather.read_table(annotations, columns=COLUMNS + ['somaSide']).to_pylist()
    by_id = {row['bodyId']: row for row in rows}
    ids = np.load(graph / 'body_ids.npy', mmap_mode='r', allow_pickle=False)
    ptr = np.load(graph / 'indptr.npy', mmap_mode='r', allow_pickle=False)
    weights = np.load(graph / 'weights.npy', mmap_mode='r', allow_pickle=False)
    targets = np.load(graph / 'targets.npy', mmap_mode='r', allow_pickle=False)
    validate_graph(ids, ptr, weights)
    if targets.ndim != 1 or targets.dtype.kind not in 'iu' or len(targets) != len(weights):
        raise ValueError('targets must be an integer vector matching stored weights')
    nt_by_body = {}
    nt_evidence = {'available': False, 'reason': 'not supplied; no type-based NT inference'}
    if neurotransmitters is not None:
        nt_hash = digest(neurotransmitters)
        if nt_hash != manifests['neurotransmitters']['sha256']:
            raise ValueError('neurotransmitter table does not match download manifest')
        table = feather.read_table(neurotransmitters, columns=['body', 'consensus_nt'])
        selected = table.filter(pc.is_in(table['body'], value_set=pyarrow.array(ids)))
        for row in selected.to_pylist():
            body_id, nt = row['body'], row['consensus_nt']
            if body_id in nt_by_body and nt_by_body[body_id] != nt:
                raise ValueError('conflicting consensus_nt rows for bodyId=' + str(body_id))
            nt_by_body[body_id] = nt
        nt_evidence = {'available': True, 'path': str(neurotransmitters), 'sha256': nt_hash,
                       'source': manifests['neurotransmitters']['url'], 'columns': ['body', 'consensus_nt'],
                       'graphBodiesWithRow': len(nt_by_body), 'missingNotImputed': True}
        del table, selected
    for row in rows:
        row['consensus_nt'] = nt_by_body.get(row['bodyId'])

    def index(body_id):
        at = int(np.searchsorted(ids, body_id))
        return at if at < len(ids) and int(ids[at]) == body_id else None

    def node(at):
        body_id = int(ids[at])
        row = by_id.get(body_id, {})
        return {'bodyId': body_id, 'type': row.get('type'), 'somaSide': row.get('somaSide'),
                'consensus_nt': nt_by_body.get(body_id)}

    groups = {'gustatory': [row for row in rows if row['class'] == 'gustatory']}
    for name in ('LC4', 'LC6', 'LPLC2', 'LC16', 'LPLC1', 'GF', 'DNp01'):
        groups[name] = [row for row in rows if row['type'] == name]
    dopamine_targets = {}
    for row in rows:
        if re.match(r'^(PAM\d|PPL1\d)', row['type'] or ''):
            at = index(row['bodyId'])
            if at is not None:
                dopamine_targets[at] = 'PAM' if row['type'].startswith('PAM') else 'PPL1'
    gf = {index(row['bodyId']) for row in groups['DNp01']} - {None}
    cache, edges_read, effective_read = {}, 0, 0
    truncated = []

    def adjacency(at):
        nonlocal edges_read, effective_read
        if at in cache:
            return cache[at]
        start, end = int(ptr[at]), int(ptr[at + 1])
        if edges_read + end - start > max_edges:
            return None
        dest, values = targets[start:end].copy(), weights[start:end].copy()
        edges_read += end - start
        if np.any(dest < 0) or np.any(dest >= len(ids)):
            raise ValueError('target index out of range for bodyId=' + str(int(ids[at])))
        if not np.all(np.isfinite(values)):
            raise ValueError('non-finite candidate weight for bodyId=' + str(int(ids[at])))
        mask = values != 0
        effective_read += int(np.count_nonzero(mask))
        cache[at] = (dest[mask], values[mask])
        return cache[at]

    def new_paths():
        return {target: {sign: {'count': 0, 'examples': [], 'targetBodyIds': set()}
                         for sign in ('positive', 'negative')} for target in ('PAM', 'PPL1')}

    def add_path(buckets, target, path_nodes, path_weights):
        # Product sign is only algebraic; it does not predict firing or affect.
        negative = sum(value < 0 for value in path_weights) % 2
        bucket = buckets[target]['negative' if negative else 'positive']
        bucket['count'] += 1
        bucket['targetBodyIds'].add(path_nodes[-1]['bodyId'])
        if len(bucket['examples']) < 20:
            bucket['examples'].append({'nodes': path_nodes, 'weights': path_weights,
                                       'edgeSigns': ['positive' if value > 0 else 'negative' for value in path_weights]})

    results, incoming = {}, defaultdict(list)
    for name, members in groups.items():
        result = {'candidateCount': len(members), 'inGraph': 0, 'candidateRowsScanned': 0,
                  'candidates': members, 'direct': new_paths(), 'twoHop': new_paths(),
                  'directDNp01': [], 'storedCandidateOutgoingEdges': 0, 'effectiveCandidateOutgoingEdges': 0}
        results[name] = result
        for row in members:
            at = index(row['bodyId'])
            if at is None:
                continue
            result['inGraph'] += 1
            adj = adjacency(at)
            if adj is None:
                truncated.append('candidate edge budget: ' + name + '/' + str(row['bodyId']))
                continue
            result['candidateRowsScanned'] += 1
            result['storedCandidateOutgoingEdges'] += int(ptr[at + 1] - ptr[at])
            result['effectiveCandidateOutgoingEdges'] += len(adj[0])
            for dest, weight in zip(*adj):
                dest, weight = int(dest), float(weight)
                if dest in gf:
                    result['directDNp01'].append({'nodes': [node(at), node(dest)], 'weights': [weight],
                                                  'edgeSigns': ['positive' if weight > 0 else 'negative']})
                if dest in dopamine_targets:
                    add_path(result['direct'], dopamine_targets[dest], [node(at), node(dest)], [weight])
                incoming[dest].append((name, at, weight))
    intermediate_ids = sorted(incoming)
    if len(intermediate_ids) > max_intermediates:
        truncated.append('intermediate limit: first %d of %d ascending body IDs' % (max_intermediates, len(intermediate_ids)))
    scanned = 0
    for mid in intermediate_ids[:max_intermediates]:
        adj = adjacency(mid)
        if adj is None:
            truncated.append('intermediate edge budget before bodyId=' + str(int(ids[mid])))
            break
        scanned += 1
        hits = [(int(dest), float(value)) for dest, value in zip(*adj) if int(dest) in dopamine_targets]
        for name, source, first in incoming[mid]:
            for dest, second in hits:
                if len({source, mid, dest}) != 3:
                    continue
                add_path(results[name]['twoHop'], dopamine_targets[dest],
                         [node(source), node(mid), node(dest)], [first, second])
    for result in results.values():
        for length in ('direct', 'twoHop'):
            for signs in result[length].values():
                for bucket in signs.values():
                    bucket['targetBodyIds'] = sorted(bucket['targetBodyIds'])
    config_path = ROOT / 'Brain/MaleCNS/config/analog_temporal_v1.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    existing = {name: {int(value) for value in values} for name, values in config['inputs'].items()}
    mapping = {}
    for name in ('LC4', 'LPLC2', 'DNp01'):
        members = groups[name]
        mapping[name] = {'role': 'candidate_input' if name != 'DNp01' else 'candidate_readout',
                         'neurons': [{key: row.get(key) for key in ('bodyId', 'type', 'somaSide', 'consensus_nt')} for row in members],
                         'existingInputIntersections': {group: sorted({row['bodyId'] for row in members} & values)
                                                        for group, values in existing.items()}}
    gustatory = {}
    for row in groups['gustatory']:
        key = row['type'] or 'unannotated'
        item = gustatory.setdefault(key, {'count': 0, 'subclassCounts': Counter(), 'receptorTypeCounts': Counter()})
        item['count'] += 1
        item['subclassCounts'][row['subclass'] or 'unannotated'] += 1
        item['receptorTypeCounts'][row['receptorType'] or 'unannotated'] += 1
    return {'capturedAtUtc': datetime.now(timezone.utc).isoformat(),
            'dependencies': {'python': platform.python_version(), 'numpy': np.__version__, 'pyarrow': pyarrow.__version__},
            'annotation': {'path': str(annotations), 'sha256': annotation_hash, 'source': manifest['url'],
                           'downloadManifestSha256': digest(manifest_path)},
            'neurotransmitters': nt_evidence,
            'graph': {'path': str(graph), 'neuronCount': len(ids), 'storedEdgeCount': len(weights),
                      'globalEffectiveEdgeCount': None, 'bodyIdsSha256': digest(graph / 'body_ids.npy'),
                      'indptrSha256': digest(graph / 'indptr.npy'), 'fullWeightsRead': False},
            'budget': {'maxEdges': max_edges, 'maxIntermediates': max_intermediates,
                       'storedEdgesRead': edges_read, 'effectiveEdgesRead': effective_read,
                       'intermediatesAvailable': len(intermediate_ids), 'intermediatesScanned': scanned,
                       'truncated': truncated, 'order': 'ascending graph index/body ID', 'exampleLimit': 20},
            'candidateMapping': mapping, 'existingInputs': config['inputs'], 'configSha256': digest(config_path),
            'gustatoryTypes': gustatory, 'candidateGroups': results,
            'targetSets': {name: [node(at) for at in sorted(dopamine_targets) if dopamine_targets[at] == name]
                           for name in ('PAM', 'PPL1')},
            'limitations': ['Exact type and synonym labels do not validate sweet, danger or affective stimulation.',
                            'Only finite nonzero weights form paths; sign product is not simulated transmission.',
                            'Path counts cover scanned rows only; examples are capped but discovered target ID sets are complete within that scope.',
                            'Stored global edges are not a global nonzero-edge count; no whole weights scan was performed.',
                            'Effective CSR omits inactive structural edges; absence does not imply anatomical disconnection.',
                            'No NT inference, neural stimulation, LIF, Unity or network operation.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--annotations', type=Path, default=ROOT / 'Data/malecns/v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather')
    parser.add_argument('--graph-dir', type=Path, default=ROOT / 'artifacts/neuron_checkpoint')
    parser.add_argument('--neurotransmitters', type=Path, default=ROOT / 'Data/malecns/v1.0/body-neurotransmitters-male-cns-v1.0.feather')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/neural-feedback/environment-path-audit-reproduced.json')
    parser.add_argument('--max-intermediates', type=int, default=10000)
    parser.add_argument('--max-edges', type=int, default=5000000)
    args = parser.parse_args()
    result = run(args.annotations.resolve(), args.graph_dir.resolve(), args.max_intermediates, args.max_edges,
                 args.neurotransmitters.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output.resolve()), 'budget': result['budget']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
