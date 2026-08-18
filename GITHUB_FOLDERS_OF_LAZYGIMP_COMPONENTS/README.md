# Upstream component clones

Read-only clones of every project LazyGimp installs or integrates with, kept
so the code we integrate against can actually be read. **Not part of this
repository**: everything in here except this file is in `.gitignore`.

| Component | Upstream | How LazyGimp uses it |
| --- | --- | --- |
| GIMPSAM | `pierspad/GIMPSAM` | The SAM source of truth. LazyGimp re-exports its package (`lazygimp/sam3.py`, `models.py`, `sam_backend.py` are thin shims) and ships its `gimpsam-src.zip` release asset. |
| batcher | `kamilburda/batcher` | Release asset installed into GIMP's plug-ins directory. |
| PhotoGIMP | `Diolinux/PhotoGIMP` | Release zip unpacked over GIMP's config. |
| gmic | `GreycLab/gmic` | Installed as the Flatpak extension `org.gimp.GIMP.Plugin.GMic` — LazyGimp never builds from this source. Cloned for reading only. |

## Two supported layouts, and which one you want

The scripts find the clones in either place, and say which they picked:

**Sibling** — the clones sit next to the LazyGimp checkout:

```
GIMP_STUFF/
├── LazyGimp/      ← this repo
├── GIMPSAM/
├── batcher/
├── PhotoGIMP/
└── gmic/
```

**In-repo** — the clones sit inside this folder. Self-contained, and what
you get by following the clone commands below.

**Prefer sibling if you contribute to any of these projects**, and it is what
the scripts choose when both exist. One clone per project then serves every
purpose: reading it, branching in it, opening a PR from it. Keeping a second
"read-only" copy in here as well buys nothing and costs correctness — the
`gimpsam_dep.py` resolver loads `../GIMPSAM`, so an in-repo GIMPSAM is *not*
the code that runs, and it will quietly drift behind the one that does. That
has already happened once, by thirteen commits.

The fork case does not justify a second clone either. A fork wants one clone
with two remotes, which is the ordinary git arrangement:

```bash
git remote add upstream https://github.com/Diolinux/PhotoGIMP.git
```

`origin` is then your fork (push, PRs) and `upstream` is where releases come
from. `update-components.sh` fetches both, so release checks stay accurate on
a fork.

## Populating the in-repo layout

```bash
cd GITHUB_FOLDERS_OF_LAZYGIMP_COMPONENTS && \
  git clone https://github.com/pierspad/GIMPSAM.git && \
  git clone https://github.com/kamilburda/batcher.git && \
  git clone https://github.com/Diolinux/PhotoGIMP.git && \
  git clone https://github.com/GreycLab/gmic.git
```

`gmic` is large; `--depth 50` is plenty if you only mean to read recent code.
Point the scripts somewhere else entirely with `LAZYGIMP_COMPONENTS_DIR`.

## Why keep clones at all

LazyGimp resolves versions **at runtime** from the GitHub API — it never
reads these clones, and deleting them breaks nothing. What they buy is the
difference between "this API probably behaves like this" and knowing.
Concrete cases from real debugging sessions:

- GIMP's own source settled whether `Gegl.Buffer.get()` is introspectable,
  and its signature, before the plug-in was rewritten to depend on it.
- GIMP's bundled Python plug-ins settled the menu-path convention when a
  menu entry wasn't appearing.
- SAM1's and SAM2's mask generators revealed that both expose a
  `_process_batch` hook — which is what the determinate progress bar counts.

None of that is in any documentation.

## Keeping it current

```bash
./scripts/update-components.sh
```

Fast-forwards every clone and prints the new commits. Skips anything with
local changes, a detached HEAD, a local-only branch, or a diverged branch —
and never touches the LazyGimp checkout itself. It cannot lose work.

```bash
./scripts/check-component-releases.sh
```

Asks GitHub for the newest **published release** of each component and
compares it with the local clone. A different question: LazyGimp installs
from releases, not from `main`, so a component can be months ahead in source
while the installer sees nothing new — and a release we don't handle yet is
the case worth catching early.

Run both at the start of a working session.
