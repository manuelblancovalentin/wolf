# WOLF White-Paper Outline

This outline organizes the existing technical documentation for a future
paper or artifact description; it is not a claim of production maturity.

1. **Motivation** — preserve implementation history and make experiments
   portable across designs, technologies, and flow ecosystems.
2. **Design goals** — location-independent resolution, explicit backends,
   reproducibility, and incremental compatibility with legacy environments.
3. **System model** — registries, packages, environments, resolver,
   RunContext, backend, executor, and numbered run.
4. **Environment model** — mutable partial profiles versus complete resolved
   run configuration; canonical semantics and backend-native escape hatches.
5. **Package and registry model** — pinned reusable assets, local/Git registries,
   and credential boundaries.
6. **Backend abstraction** — Cadence Flowtool compatibility and ORFS translation
   without reimplementing synthesis or place-and-route.
7. **Reproducibility and provenance** — frozen resolved manifests, snapshots,
   run numbering, and latest links.
8. **Execution lifecycle** — planning, allocation, stage execution, artifacts,
   mutable status, and backend-owned metrics.
9. **Case study** — package-backed Ibex/ASAP7/ORFS at 1050 ps under Podman.
10. **Limitations and future work** — second-design validation, broader backend
    coverage, richer status inspection, dependency solving, and packaging.

Supporting detail lives in [Architecture](ARCHITECTURE.md),
[Environments](ENVIRONMENTS.md), [Packages](PACKAGES.md), [ORFS](ORFS.md), and
[Testing](TESTING.md).
