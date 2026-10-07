"""Generación del conjunto de entrenamiento.

FASE 1 (este avance) — datos sintéticos con base física
--------------------------------------------------------
Aún no se dispone de un inventario etiquetado de eventos para las zonas de
estudio, así que se simulan condiciones hidrometeorológicas realistas para la
región andina/pacífica de Nariño y se etiquetan con una función de riesgo
latente inspirada en la literatura sobre umbrales de lluvia detonante de
deslizamientos (lluvia antecedente + lluvia detonante + saturación del suelo +
susceptibilidad del terreno) y en el aumento de caudal para crecientes.

Se añade ruido a la etiqueta para que el modelo no memorice una fórmula exacta.

FASE 2 (hoja de ruta) — datos reales
-------------------------------------
Reemplazar ``SyntheticDatasetGenerator`` por un constructor que cruce el
inventario de movimientos en masa del SGC (SIMMA) y DesInventar con la serie
histórica de Open-Meteo (Archive API) en la fecha y lugar de cada evento. El
script ``train.py`` ya acepta un CSV externo con las mismas columnas.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.domain.value_objects import FEATURE_ORDER, RiskLevel

LEVELS = [RiskLevel.BAJO, RiskLevel.MODERADO, RiskLevel.ALTO, RiskLevel.MUY_ALTO]


@dataclass(frozen=True)
class Dataset:
    X: np.ndarray
    y: np.ndarray
    feature_names: tuple[str, ...] = FEATURE_ORDER


class SyntheticDatasetGenerator:
    # Umbrales de la puntuación latente que separan los niveles de riesgo.
    THRESHOLDS = (3.6, 5.5, 8.5)

    def __init__(self, seed: int = 42) -> None:
        self._rng = np.random.default_rng(seed)

    def generate(self, n_samples: int = 20_000) -> Dataset:
        rng = self._rng
        # Régimen de lluvias: mezcla de días secos, normales y temporadas invernales.
        regime = rng.choice([0, 1, 2], size=n_samples, p=[0.45, 0.40, 0.15])
        scale_24h = np.array([2.0, 10.0, 30.0])[regime]
        rain_24h = rng.gamma(shape=1.2, scale=scale_24h)
        rain_72h = rain_24h + rng.gamma(shape=1.5, scale=scale_24h * 1.1)
        rain_7d = rain_72h + rng.gamma(shape=2.0, scale=scale_24h * 1.3)
        forecast_24h = rng.gamma(shape=1.1, scale=scale_24h * 0.9)
        soil = np.clip(0.18 + 0.0018 * rain_7d + rng.normal(0, 0.035, n_samples), 0.05, 0.60)
        discharge = np.clip(
            np.exp(rng.normal(0, 0.25, n_samples)) * (1 + 0.012 * rain_72h), 0.2, 8.0
        )
        slope = np.clip(rng.gamma(shape=2.2, scale=8.0, size=n_samples), 0, 60)
        susceptibility = rng.integers(1, 6, size=n_samples)

        score = (
            0.030 * rain_72h
            + 0.008 * (rain_7d - rain_72h)  # lluvia antecedente
            + 0.035 * forecast_24h
            + 6.0 * np.maximum(soil - 0.25, 0)  # saturación del suelo
            + 0.55 * susceptibility
            + 0.035 * slope
            + 1.4 * np.log(discharge)  # crecientes: caudal sobre lo normal
        )
        # Interacción: lluvia intensa sobre suelo muy susceptible es desproporcionadamente peor.
        score += 0.010 * rain_72h * (susceptibility >= 4)
        score += rng.normal(0, 0.45, n_samples)  # ruido de etiquetado

        labels = np.digitize(score, self.THRESHOLDS)
        X = np.column_stack(
            [rain_24h, rain_72h, rain_7d, forecast_24h, soil, discharge, slope, susceptibility]
        ).round(3)
        y = np.array([LEVELS[i].value for i in labels])
        return Dataset(X=X, y=y)
