"""Thin re-export — SAM 3.1 handling (HF gating, checkpoint download)
lives in the gimpsam package (pierspad/GIMPSAM, pinned via GIMPSAM_REF);
LazyGimp only aggregates it. Import surface kept identical so every
existing call site still works."""

from __future__ import annotations

from .gimpsam_dep import load as _load

_sam3 = _load().sam3

download_sam3 = _sam3.download_sam3
remove_sam3 = _sam3.remove_sam3
sam3_failure_message = _sam3.sam3_failure_message
classify_sam3_failure = _sam3.classify_sam3_failure

SAM3_HF_REPO_ID = _load().constants.SAM3_HF_REPO_ID
SAM3_HF_PAGE = _load().constants.SAM3_HF_PAGE
