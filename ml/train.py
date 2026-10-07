"""Entrena el clasificador de riesgo y guarda el modelo con sus metadatos.

Uso (desde la carpeta backend/):
    python -m ml.train                         # datos sintéticos (fase 1)
    python -m ml.train --data ml/data/eventos.csv   # datos reales (fase 2)
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split

from app.core.config import BASE_DIR
from app.domain.value_objects import FEATURE_ORDER
from app.infrastructure.ml.sklearn_model import sha256_of
from ml.dataset import LEVELS, Dataset, SyntheticDatasetGenerator

MODELS_DIR = BASE_DIR / "models"


def load_csv(path: Path) -> Dataset:
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    X = np.array([[float(r[f]) for f in FEATURE_ORDER] for r in rows])
    y = np.array([r["level"] for r in rows])
    return Dataset(X=X, y=y)


def train(dataset: Dataset, source: str, seed: int = 42) -> dict:
    X_train, X_test, y_train, y_test = train_test_split(
        dataset.X, dataset.y, test_size=0.2, stratify=dataset.y, random_state=seed
    )
    model = RandomForestClassifier(
        n_estimators=250,
        max_depth=12,
        min_samples_leaf=5,
        class_weight="balanced",  # las alertas altas son minoría: no deben ignorarse
        n_jobs=-1,
        random_state=seed,
    )
    cv = cross_val_score(
        model, X_train, y_train, cv=StratifiedKFold(5, shuffle=True, random_state=seed),
        scoring="f1_macro",
    )
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)

    labels = [lvl.value for lvl in LEVELS]
    report = classification_report(y_test, y_pred, labels=labels, output_dict=True, zero_division=0)
    print(classification_report(y_test, y_pred, labels=labels, zero_division=0))

    version = datetime.now(UTC).strftime("rf-%Y%m%d-%H%M")
    MODELS_DIR.mkdir(exist_ok=True)
    model_path = MODELS_DIR / "risk_model.joblib"
    joblib.dump(model, model_path, compress=3)

    metadata = {
        "version": version,
        "algorithm": "RandomForestClassifier",
        "trained_at": datetime.now(UTC).isoformat(),
        "data_source": source,
        "n_samples": int(len(dataset.y)),
        "feature_order": list(FEATURE_ORDER),
        "classes": list(model.classes_),
        "class_distribution": {lbl: int((dataset.y == lbl).sum()) for lbl in labels},
        "metrics": {
            "cv_f1_macro_mean": round(float(cv.mean()), 4),
            "cv_f1_macro_std": round(float(cv.std()), 4),
            "test_f1_macro": round(float(f1_score(y_test, y_pred, average="macro")), 4),
            "test_accuracy": round(float(report["accuracy"]), 4),
            # Recall de las clases que disparan SMS: el error más caro es no alertar.
            "recall_alto": round(report["ALTO"]["recall"], 4),
            "recall_muy_alto": round(report["MUY_ALTO"]["recall"], 4),
            "confusion_matrix": confusion_matrix(y_test, y_pred, labels=labels).tolist(),
        },
        "feature_importances": {
            name: round(float(imp), 4)
            for name, imp in sorted(
                zip(FEATURE_ORDER, model.feature_importances_, strict=True), key=lambda p: -p[1]
            )
        },
        "sha256": sha256_of(model_path),
    }
    (MODELS_DIR / "risk_model.meta.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Entrena el modelo de riesgo de AlertaSinRed")
    parser.add_argument("--data", type=Path, help="CSV con columnas de FEATURE_ORDER + level")
    parser.add_argument("--samples", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.data:
        dataset, source = load_csv(args.data), f"csv:{args.data.name}"
    else:
        dataset = SyntheticDatasetGenerator(args.seed).generate(args.samples)
        source = "sintetico-fisico-v1"

    meta = train(dataset, source, args.seed)
    print(json.dumps({k: meta[k] for k in ("version", "metrics", "feature_importances")},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
