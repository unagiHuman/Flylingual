# Mac M1-M3 report

Captured 2026-09-11 JST. This is a dataset and structural-graph audit only; no MaleCNS LIF network or motor backend was run.

## Environment

- macOS 15.6 arm64, 8 logical CPUs, 16 GiB RAM.
- Python 3.10.21, Brian2 2.5.1, Cython 0.29.37, NumPy 1.24.3, PyArrow 24.0.0.
- `flybrain-malecns` was cloned from the protected `brian2` environment.
- The isolated Cython one-neuron compile/run test passed with Apple clang 17.0.0.
- Initial work-memory ceiling: min(50% of RAM, 8 GiB) = 8 GiB. Available memory at the environment probe was about 4.49 GiB, so the dataset scan used record batches and the graph builder used disk-backed arrays.

## Official inputs

The three files were resolved from `https://male-cns.janelia.org/download/` and downloaded from the official `storage.googleapis.com/flyem-male-cns/v1.0/` bucket. Exact URLs, response metadata, byte counts, and local SHA-256 hashes are in `Brain/MaleCNS/results/download_manifest.json`. Publisher checksum/signature verification was not available; the SHA-256 values are local reproducibility hashes.

## Schema and selection

- Annotation ID: `bodyId` int64. 211,577 rows, no null IDs and no duplicate IDs.
- NT ID: `body` int64. 1,835,518 rows and IDs, no duplicates. The selected annotation set lacks NT rows for 24,561 IDs.
- Connections: `body_pre` int64 -> `body_post` int64, with `weight` int64 synapse count.
- Selection is every annotated body ID, including 47,071 empty `type` values. Both brain and VNC classes are retained.
- Major superclass counts include ol_intrinsic 89,403, cb_intrinsic 32,164, vnc_intrinsic 13,161, descending_neuron 1,314, and vnc_motor 708; superclass is null for 44,877 rows.

## Structural graph

- Raw table: 151,856,684 rows and 311,833,243 synapses.
- Both endpoints selected: 26,028,386 rows and 125,365,933 synapses.
- Outside selected endpoint set: 125,828,298 rows and 186,467,310 synapses.
- Exact 256-partition pair aggregation found zero duplicate selected pairs, so structural E remains 26,028,386.
- Selected incident neurons: 188,778; selected isolated neurons: 22,799.
- Raw table self rows: 123 (542 synapses); selected structural graph contains 112 self edges.
- Zero-weight raw rows: 0.
- Full audit scan peak RSS: about 1.47 GiB. Graph build peak RSS: about 1.51 GiB. The disk-backed structural graph is stored under ignored `artifacts/malecns_structural_graph/`.

## NT and ID status

The selected set contains 104,173 acetylcholine, 22,186 GABA, 29,443 glutamate, 8,024 histamine, 396 dopamine, 101 octopamine, 48 serotonin, 22,645 unclear, and 24,561 missing NT assignments.

No transmitter category is assigned a signed LIF weight at M3. In particular, unclear/missing are not treated as excitatory and modulators are not collapsed into a fast excitatory synapse. Consequently the effective dynamic edge count is not yet defined and `signedDynamicsReady=false`.

Annotation search finds candidate names without reusing old FlyWire IDs: MaleCNS body IDs 10360 (`DNa02_R`), 523769 (`DNa02_L`), 10783 (`DNp09_L`), and 11177 (`DNp09_R`). Two DNp71 rows include DNp09 only in an alias-like instance string and are not accepted as DNp09. These are candidates for M4 evidence review, not verified readouts or motor mappings.

## Gate status

- M0: complete locally, commit `89d1791`, tag `baseline-shiu-physx-source`; no remote or push.
- M1: complete.
- M2: complete for download, local hashes, and schema inspection.
- M3: complete for selection and structural sparse graph. Signed/effective graph remains intentionally blocked by unresolved NT/receptor policy.
- M4-M6: not started.

## M3 source/config SHA-256

- `schema_map.json`: `18625e74eb7aca57fcb5fee2aec3a1a934a9e4089a5441a6f02056617fdf29c4`
- `selection_policy.json`: `4890c575f50517a597bb51ebdd5acd04c4e746b3571d42530322b9651b2255dd`
- `nt_policy.json`: `266be9a3734fb1cfea33228987ab71d6f21ae29b97ef33fd83f45c7325ca1055`
- `inspect_dataset.py`: `075e32e8f7cf5efe93d2efc10f29752e804650597fe924aada208f71a175b23a`
- `build_sparse_graph.py`: `78665fca8cd8b53f001b6600a11433e049c1928d5092df10bdbd1e9ca04ea06e`
