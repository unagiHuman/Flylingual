# M4 exploratory signed graph report

Captured 2026-09-11 JST. The strict `audit-only-unresolved-v1` NT policy remains unchanged.

With explicit user approval, a separate `exploratory-lif-ach-gaba-v1` policy was added:

- acetylcholine: sign `+1` as a PoC fast-excitatory assumption;
- GABA: sign `-1` as a PoC fast-inhibitory assumption;
- glutamate, histamine, dopamine, octopamine, serotonin, unclear, and missing: sign `0`, dynamically excluded rather than assigned an unsupported sign.

The structural graph remains 211,577 neurons and 26,028,386 edges. The edge-aligned signed representation contains:

- effective edges: 19,848,648;
- positive edges: 14,875,726;
- negative edges: 4,972,922;
- inactive structural edges: 6,179,738;
- sign-generation peak RSS: about 0.74 GiB;
- dense matrices: none.

Policy SHA-256: `21339444f5ba80eee0b6a9757a99d7cdacdd1d6da282a066e9e8dea1435a2569`.

The generated `sign.npy` SHA-256 is `e15bd13ec777db6728daccfa75c025cd99062c98758b7a2b29e5b802ca7ebc13`. Large generated arrays remain under ignored `artifacts/` and are rebuilt from the official data plus committed scripts/config. This result is an executable sign assignment, not evidence of stable LIF dynamics or biological validity.
