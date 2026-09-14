"""Read-only MaleCNS annotation/CSR audit; never runs a neural simulation.

Candidate labels are search results, not validated affective input mappings.
Only the selected presynaptic CSR weight slices are inspected.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import sys

import numpy as np
import pyarrow
import pyarrow.feather as feather

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ['bodyId', 'type', 'instance', 'superclass', 'supertype', 'subclass',
           'class', 'receptorType', 'hemibrainType', 'flywireType', 'synonyms']
SELECTIONS = {
    'PAM_type': ('type regex ^PAM\\d', lambda row: bool(re.match(r'^PAM\d', row['type'] or ''))),
    'PPL1_type': ('type regex ^PPL1\\d', lambda row: bool(re.match(r'^PPL1\d', row['type'] or ''))),
    'gustatory_class': ('class == gustatory', lambda row: row['class'] == 'gustatory'),
    'sugar_synonym': ('synonyms case-insensitive literal sugar', lambda row: 'sugar' in (row['synonyms'] or '').lower()),
    'bitter_synonym': ('synonyms case-insensitive literal bitter', lambda row: 'bitter' in (row['synonyms'] or '').lower()),
}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def validate_graph(ids, indptr, weights):
    if ids.ndim != 1 or ids.dtype.kind not in 'iu' or len(ids) == 0:
        raise ValueError('body_ids must be a nonempty integer vector')
    if np.any(ids[1:] <= ids[:-1]):
        raise ValueError('body_ids must be strictly increasing and unique')
    if indptr.ndim != 1 or indptr.dtype.kind not in 'iu' or len(indptr) != len(ids) + 1:
        raise ValueError('indptr must be an integer vector of neuronCount + 1')
    if weights.ndim != 1 or weights.dtype.kind not in 'fi':
        raise ValueError('weights must be a real numeric vector')
    if (int(indptr[0]) != 0 or int(indptr[-1]) != len(weights)
            or np.any(indptr[1:] < indptr[:-1]) or np.any(indptr < 0)
            or np.any(indptr > len(weights))):
        raise ValueError('indptr ranges must partition the weights array monotonically')


def audit(annotations, graph_dir):
    manifest_path = ROOT / 'Brain/MaleCNS/results/download_manifest.json'
    policy_path = ROOT / 'Brain/MaleCNS/config/nt_policy_exploratory_lif_v1.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    expected = manifest['files']['annotations']
    annotation_hash = digest(annotations)
    if annotation_hash != expected['sha256']:
        raise ValueError('annotation SHA-256 does not match the checked-in download manifest')
    rows = feather.read_table(annotations, columns=COLUMNS).to_pylist()
    ids = np.load(graph_dir / 'body_ids.npy', mmap_mode='r', allow_pickle=False)
    indptr = np.load(graph_dir / 'indptr.npy', mmap_mode='r', allow_pickle=False)
    weights = np.load(graph_dir / 'weights.npy', mmap_mode='r', allow_pickle=False)
    validate_graph(ids, indptr, weights)
    records, groups = {}, {}
    for name, (selection, predicate) in SELECTIONS.items():
        selected = [row for row in rows if predicate(row)]
        for row in selected:
            body_id = row['bodyId']
            if type(body_id) is not int:
                raise ValueError('candidate has no integer body ID')
            if str(body_id) in records:
                continue
            index = int(np.searchsorted(ids, body_id))
            present = index < len(ids) and int(ids[index]) == body_id
            record = dict(row)
            record.update(consensus_nt=None,
                          ntEvidence='not queried: annotations contain no NT column; separate per-body NT evidence required',
                          graphIncluded=present, effectiveOutgoingEdges=None)
            if present:
                start, end = int(indptr[index]), int(indptr[index + 1])
                local = weights[start:end]
                if not np.all(np.isfinite(local)):
                    raise ValueError('non-finite candidate weight: bodyId=' + str(body_id))
                record.update(storedOutgoingEdges=end - start,
                              effectiveOutgoingEdges=int(np.count_nonzero(local)),
                              positiveOutgoingEdges=int(np.count_nonzero(local > 0)),
                              negativeOutgoingEdges=int(np.count_nonzero(local < 0)),
                              zeroWeightOutgoingEdges=int(np.count_nonzero(local == 0)))
            records[str(body_id)] = record
        group = [records[str(row['bodyId'])] for row in selected]
        groups[name] = {'selection': selection, 'count': len(group),
                        'inGraph': sum(row['graphIncluded'] for row in group),
                        'withEffectiveOutgoingEdges': sum(bool(row['effectiveOutgoingEdges']) for row in group),
                        'totalEffectiveOutgoingEdges': sum(row['effectiveOutgoingEdges'] or 0 for row in group),
                        'typeCounts': dict(Counter(row['type'] or 'unannotated' for row in group)),
                        'bodyIds': [row['bodyId'] for row in group]}
    gustatory = [records[str(body_id)] for body_id in groups['gustatory_class']['bodyIds']]
    return {
        'capturedAtUtc': datetime.now(timezone.utc).isoformat(),
        'dataset': manifest['dataset'], 'mode': 'read_only_annotation_and_selected_CSR_slices',
        'dependencies': {'python': platform.python_version(), 'numpy': np.__version__, 'pyarrow': pyarrow.__version__},
        'invocation': sys.argv,
        'annotation': {'path': str(annotations), 'bytes': annotations.stat().st_size,
                       'sha256': annotation_hash, 'manifestSha256': expected['sha256'],
                       'matchesDownloadManifest': True, 'downloadManifestFileSha256': digest(manifest_path),
                       'publisherChecksumVerified': expected.get('publisherChecksumVerified', False),
                       'source': expected['url'], 'rows': len(rows), 'queriedColumns': COLUMNS},
        'graph': {'path': str(graph_dir), 'neuronCount': len(ids), 'storedEdgeCount': len(weights),
                  'bodyIdsSha256': digest(graph_dir / 'body_ids.npy'), 'indptrSha256': digest(graph_dir / 'indptr.npy'),
                  'weightsRead': 'candidate outgoing CSR slices only; no whole weights read or hash',
                  'candidateSliceTotalEdgesRead': sum(row.get('storedOutgoingEdges', 0) for row in records.values()),
                  'indexValidation': 'strictly increasing unique IDs; monotonic bounded complete indptr; finite candidate weights',
                  'policyPath': str(policy_path), 'policySha256': digest(policy_path)},
        'groups': groups, 'candidateRecords': records, 'uniqueCandidateCount': len(records),
        'gustatoryDetails': {
            **{field + 'Counts': dict(Counter(row[field] or 'unannotated' for row in gustatory))
               for field in ('receptorType', 'superclass', 'subclass')},
            'untypedCount': sum(row['type'] is None for row in gustatory),
            'outgoingSignCounts': {key: sum(row.get(key, 0) for row in gustatory)
                                   for key in ('positiveOutgoingEdges', 'negativeOutgoingEdges', 'zeroWeightOutgoingEdges')}},
        'literalTermCounts': {term: sum(any(term in str(row.get(key) or '').lower()
                                          for key in COLUMNS if key != 'bodyId') for row in rows)
                              for term in ('sweet', 'sugar', 'bitter', 'avers', 'nocicep')},
        'limitations': [
            'Annotation matches are candidates, not validated reward/aversion input mappings.',
            'No per-body consensus_nt was verified; neither type names nor weight signs establish transmitter identity.',
            'The recorded policy hash identifies a source file, not an independent proof that these arrays were built from it.',
            'Effective CSR omits disabled structural edges; zero outgoing degree is not anatomical disconnection.',
            'Only candidate outgoing weights were checked for finiteness; other weights and targets were not scanned.',
            'No neural simulation, stimulus, server, Unity or network operation was performed.',
            'No emotion, motivation or causal reward response follows from these annotations.'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--annotations', type=Path, default=ROOT / 'Data/malecns/v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather')
    parser.add_argument('--graph-dir', type=Path, default=ROOT / 'artifacts/neuron_checkpoint')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/neural-feedback/affective-candidate-audit-reproduced.json')
    args = parser.parse_args()
    report = audit(args.annotations.resolve(), args.graph_dir.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output.resolve()), 'uniqueCandidates': report['uniqueCandidateCount'],
                      'groups': {name: {key: group[key] for key in ('count', 'inGraph', 'totalEffectiveOutgoingEdges')}
                                 for name, group in report['groups'].items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
