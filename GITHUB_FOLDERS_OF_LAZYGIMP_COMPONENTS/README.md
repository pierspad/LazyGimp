# Upstream component clones

Read-only clones of every project LazyGimp installs or integrates with.
**Not part of this repository** — the folder is in `.gitignore`, and nothing
here is ever committed, built or shipped.

| Clone | Upstream | How LazyGimp actually uses it |
| --- | --- | --- |
| `GIMPSAM/` | `pierspad/GIMPSAM` | The SAM source of truth. LazyGimp re-exports its package (`lazygimp/sam3.py`, `models.py`, `sam_backend.py` are thin shims) and ships its `gimpsam-src.zip` release asset. |
| `batcher/` | `kamilburda/batcher` | Release asset installed into GIMP's plug-ins directory. |
| `PhotoGIMP/` | `Diolinux/PhotoGIMP` | Release zip unpacked over GIMP's config. |
| `gmic/` | `GreycLab/gmic` | Installed as the Flatpak extension `org.gimp.GIMP.Plugin.GMic` — LazyGimp never touches this source. Cloned for reading only. |

## Is this folder still needed?

Yes, but not for the reason it looks like. LazyGimp already resolves
versions **at runtime**, from the GitHub API — it queries the latest release
of each component when it runs, so it never needs a local clone to know
what's current. Deleting this folder would not break the installer.

What the clones buy is the ability to *read the code we integrate against*.
That is the difference between "this API probably behaves like this" and
knowing. Concrete cases from actual debugging sessions:

- GIMP's own source settled whether `Gegl.Buffer.get()` is introspectable
  and what its signature is, before the plug-in was rewritten to depend
  on it.
- GIMP's bundled Python plug-ins settled the menu-path convention
  (`<Image>/Filters/...`) when a menu entry wasn't appearing.
- SAM1's and SAM2's mask generators are what revealed that both expose a
  `_process_batch` hook, which is what the determinate progress bar counts.

None of that is in any documentation. So: keep the clones, keep them
current, and don't confuse them with the working checkouts.

## Which copy is which

The `GIMPSAM/` clone here is **not** the one LazyGimp loads. `gimpsam_dep.py`
looks for a *sibling* checkout — `../../GIMPSAM` relative to the `lazygimp`
package, i.e. `GIMP_STUFF/GIMPSAM` — and that is the one being developed.
This clone tracks pristine upstream `main`, so the two will differ whenever
there is unreleased work. That is expected; do not "fix" it by syncing them.

The GIMP source checkout lives outside this folder (`GIMP_STUFF/gimp`) and is
deliberately left alone by these scripts: it carries in-progress merge-request
work, and a script that pulls it could disturb that.

## Recreating the folder from scratch

Only this README is committed; the clones themselves are ignored, so a
fresh checkout starts with an empty folder. Repopulate it with:

```bash
cd GITHUB_FOLDERS_OF_LAZYGIMP_COMPONENTS && \
  git clone https://github.com/pierspad/GIMPSAM.git && \
  git clone https://github.com/kamilburda/batcher.git && \
  git clone https://github.com/Diolinux/PhotoGIMP.git && \
  git clone https://github.com/GreycLab/gmic.git
```

`gmic` is large; `--depth 50` is plenty if you only mean to read recent
code.

## Keeping it current

Two scripts, in the repository root's `scripts/`:

```bash
./scripts/update-components.sh
```

Fast-forwards every clone and prints the new commits. Skips any clone with
local changes, a detached HEAD, or a diverged branch — it can't lose work.

```bash
./scripts/check-component-releases.sh
```

Asks GitHub for the newest **published release** of each component and
compares it with the local clone. Different question from the one above:
LazyGimp installs from releases, not from `main`, so a component can be
months ahead in source while the installer sees nothing new — and a release
we don't handle yet is the case worth catching early.

Run both at the start of a working session.
