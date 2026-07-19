"""Thin re-export — the SAM Python backend (venv, PyTorch, checkpoints)
lives in the gimpsam package (pierspad/GIMPSAM, pinned via GIMPSAM_REF);
LazyGimp only aggregates it. Import surface kept identical so every
existing call site still works. gimpsam duck-types the Job it receives,
so LazyGimp's own Job (with its GUI/pty extras) drops straight in."""

from __future__ import annotations

from .gimpsam_dep import load as _load

_backend = _load().backend

venv_exists = _backend.venv_exists
backend_ready = _backend.backend_ready
install_sam_backend = _backend.install_sam_backend
remove_sam_backend = _backend.remove_sam_backend
install_sam3_transformers = _backend.install_sam3_transformers
bridge_self_test = _backend.bridge_self_test
write_sam_info = _backend.write_sam_info

TORCH_INDEX_URLS = _load().constants.TORCH_INDEX_URLS
