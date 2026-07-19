"""Thin re-export — the SAM model registry lives in the gimpsam package
(pierspad/GIMPSAM, pinned via GIMPSAM_REF); LazyGimp only aggregates it.
Import surface kept identical so every existing call site still works."""

from __future__ import annotations

from .gimpsam_dep import load as _load

_models = _load().models

ModelSpec = _models.ModelSpec
MODEL_REGISTRY = _models.MODEL_REGISTRY
MODEL_BY_KEY = _models.MODEL_BY_KEY
model_path = _models.model_path
model_installed = _models.model_installed
any_model_installed = _models.any_model_installed
