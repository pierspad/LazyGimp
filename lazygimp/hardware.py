"""Thin re-export — hardware detection (used only to recommend a SAM
model and PyTorch wheel index) lives in the gimpsam package
(pierspad/GIMPSAM, resolved from its latest release by gimpsam_dep); LazyGimp only aggregates it.
Import surface kept identical so every existing call site still works."""

from __future__ import annotations

from .gimpsam_dep import load as _load

_hardware = _load().hardware

Hardware = _hardware.Hardware
detect_gpu = _hardware.detect_gpu
detect_hardware = _hardware.detect_hardware
def recommended_model_key(hw) -> str:
    return "sam2_hiera_small"
recommended_torch_index = _hardware.recommended_torch_index
