"""Adaptador del modelo de clasificación de riesgo entrenado con scikit-learn."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np

from app.domain.exceptions import ModelIntegrityError
from app.domain.ports import RiskModel
from app.domain.value_objects import FEATURE_ORDER, RiskFeatures, RiskLevel, RiskPrediction


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SklearnRiskModel(RiskModel):
    def __init__(self, estimator: object, version: str) -> None:
        self._estimator = estimator
        self._version = version
        self._classes = [RiskLevel(c) for c in estimator.classes_]  # type: ignore[attr-defined]

    @property
    def version(self) -> str:
        return self._version

    @classmethod
    def load(cls, model_path: Path, metadata_path: Path) -> SklearnRiskModel:
        """Carga el modelo SOLO si su huella SHA-256 coincide con la de los metadatos.

        ``joblib``/``pickle`` puede ejecutar código arbitrario al deserializar;
        verificar la integridad impide cargar un archivo alterado o sustituido.
        """
        if not model_path.is_file() or not metadata_path.is_file():
            raise ModelIntegrityError(
                "Modelo no encontrado. Entrénelo con: python -m ml.train"
            )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if sha256_of(model_path) != metadata.get("sha256"):
            raise ModelIntegrityError("La huella SHA-256 del modelo no coincide")
        if tuple(metadata.get("feature_order", ())) != FEATURE_ORDER:
            raise ModelIntegrityError("El modelo fue entrenado con otras variables")
        return cls(joblib.load(model_path), version=metadata["version"])

    def predict(self, features: RiskFeatures) -> RiskPrediction:
        vector = np.asarray([features.as_vector()], dtype=float)
        probabilities = self._estimator.predict_proba(vector)[0]  # type: ignore[attr-defined]
        best = int(np.argmax(probabilities))
        pairs = zip(self._classes, probabilities, strict=True)
        return RiskPrediction(
            level=self._classes[best],
            probability=float(probabilities[best]),
            probabilities={level.value: float(p) for level, p in pairs},
        )
