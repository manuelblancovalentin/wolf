# WOLF registries

A registry is a collection of package manifests; it is not package content.
The committed `builtin` registry is always available. Phase 1 also supports
configured `local` trees and `git` checkouts:

```bash
wolf registry add lab /projects/eda/wolf-registry --type local
wolf registry add shared git@host:group/wolf-registry.git --type git
wolf registry sync shared
wolf registry list
wolf registry info lab
wolf registry remove lab
```

Git registries are cloned under WOLF's data registry store and only updated by
explicit `sync`. Local trees are read in place and never copied or modified.
The current Git revision is reported and included in package installation
metadata. Queries never contact the network. Duplicate package identifiers are
reported as ambiguous; use `shared::rtl/name` to qualify one. Registry
priority is recorded for future policy but does not silently resolve a
collision in this phase.

Registry URLs are stored as configured source references, never credentials.
WOLF does not store Git passwords, tokens, private keys, or credential-manager
state; SSH agents and Git's own HTTPS credential handling remain responsible
for authentication.
