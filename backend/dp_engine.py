"""Motor de Privacidad Diferencial: consultas Laplace y modelo DP de alerta temprana.

Preprocesamiento identico a notebooks/02_experimentos_dp_y_equidad.ipynb:
limites de dominio publicos fijados a priori -> data_norm analitico = sqrt(8 + 7).
"""
import os
import sqlite3

import joblib
import numpy as np
import pandas as pd
from diffprivlib.mechanisms import Laplace
from diffprivlib.models import LogisticRegression as DPLogisticRegression

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "db", "oulad_proyecto.db")
ARTEFACTOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artifacts")
RUTA_MODELO = os.path.join(ARTEFACTOS, "modelo_dp.joblib")

EPSILON_MODELO = 5.0  # menor ε que cumple utilidad y equidad en el barrido del notebook 02
SEMILLA = 42

CAT = ["code_module", "code_presentation", "gender", "region", "highest_education", "imd_band", "age_band"]
LIMITES = {
    "num_of_prev_attempts": (0, 6, None),
    "studied_credits": (0, 400, None),
    "date_registration": (-300, 60, None),
    "promedio_notas_60d": (0, 100, None),
    "entregas_60d": (0, 15, None),
    "retraso_promedio_60d": (-60, 60, None),
    "total_clics_60d": (0, float(np.log1p(10_000)), np.log1p),
    "dias_activos_60d": (0, 90, None),
}
NUM = list(LIMITES)
DATA_NORM = float(np.sqrt(len(NUM) + len(CAT)))

# Dominio publico de promedio_notas_60d para la suma acotada.
NOTA_MIN, NOTA_MAX = 0.0, 100.0


def conectar() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


# --- Preprocesamiento ----------------------------------------------------------
def preparar(d: pd.DataFrame, categorias: dict) -> np.ndarray:
    partes = []
    for c, (lo, hi, f) in LIMITES.items():
        x = d[c].astype(float)
        x = f(x.clip(lower=0)) if f is not None else x
        partes.append(((x.clip(lo, hi) - lo) / (hi - lo)).rename(c))
    for c in CAT:
        partes.append(pd.get_dummies(pd.Categorical(d[c], categories=categorias[c]), prefix=c, dtype=float)
                      .set_index(d.index))
    return pd.concat(partes, axis=1).to_numpy()


# --- Modelo DP -----------------------------------------------------------------
class ModeloDP:
    def __init__(self, modelo: DPLogisticRegression, categorias: dict, epsilon: float):
        self.modelo = modelo
        self.categorias = categorias
        self.epsilon = epsilon

    def probabilidad(self, perfiles: pd.DataFrame) -> np.ndarray:
        return self.modelo.predict_proba(preparar(perfiles, self.categorias))[:, 1]


def entrenar_modelo(epsilon: float = EPSILON_MODELO) -> ModeloDP:
    with conectar() as con:
        df = pd.read_sql("SELECT * FROM oulad_analitico", con)
    categorias = {c: sorted(df[c].unique()) for c in CAT}
    # Acotamiento de contribucion: una matricula por estudiante -> garantia por persona.
    df = df.groupby("id_student", group_keys=False).sample(n=1, random_state=SEMILLA)
    modelo = DPLogisticRegression(epsilon=epsilon, data_norm=DATA_NORM, max_iter=3000, random_state=SEMILLA)
    modelo.fit(preparar(df, categorias), df["target_aprobado"].to_numpy())
    return ModeloDP(modelo, categorias, epsilon)


def cargar_o_entrenar() -> tuple[ModeloDP, bool]:
    """Devuelve (modelo, recien_entrenado). El entrenamiento consume ε una sola vez."""
    if os.path.exists(RUTA_MODELO):
        m = joblib.load(RUTA_MODELO)
        if isinstance(m, ModeloDP) and m.epsilon == EPSILON_MODELO:
            return m, False
    m = entrenar_modelo()
    os.makedirs(ARTEFACTOS, exist_ok=True)
    joblib.dump(m, RUTA_MODELO)
    return m, True


def nivel_alerta(prob: float) -> str:
    if prob < 0.40:
        return "alta"
    if prob < 0.60:
        return "media"
    return "baja"


# --- Explicaciones accionables (contrafactuales) --------------------------------
# Solo variables modificables por el estudiante; nunca atributos demograficos.
_ACCIONES = {
    "entregas_60d": (
        lambda v: min(v + 2, 15),
        "Aumentar tus entregas tempranas de {a:.0f} a {b:.0f}",
    ),
    "dias_activos_60d": (
        lambda v: min(v + 10, 60),
        "Conectarte al aula virtual {b:.0f} días (en lugar de {a:.0f}) en los primeros 60 días",
    ),
    "total_clics_60d": (
        lambda v: min(v * 1.5 + 100, 10_000),
        "Aumentar tu interacción con los materiales del curso de {a:.0f} a {b:.0f} clics",
    ),
    "retraso_promedio_60d": (
        lambda v: 0.0 if v > 0 else v,
        "Entregar a tiempo (bajar tu retraso promedio de {a:.1f} a {b:.0f} días)",
    ),
    "promedio_notas_60d": (
        lambda v: min(v + 10, 100),
        "Subir tu promedio de evaluaciones tempranas de {a:.0f} a {b:.0f} (p. ej., con tutoría)",
    ),
}


def generar_explicacion_accionable(datos_estudiante: dict, prob: float, modelo: ModeloDP | None = None,
                                   max_factores: int = 3) -> list[dict]:
    """Reason codes contrafactuales en lenguaje simple (sin valores SHAP crudos).

    Cada factor modifica una sola variable accionable, recalcula la probabilidad con el
    modelo DP (post-procesamiento: sin costo adicional de privacidad) y reporta el cambio.
    Son estimaciones asociativas del modelo, no efectos causales garantizados.
    """
    modelo = modelo or MODELO
    base = pd.DataFrame([datos_estudiante])
    candidatos = []
    for var, (objetivo, plantilla) in _ACCIONES.items():
        actual = float(datos_estudiante[var])
        nuevo = float(objetivo(actual))
        if np.isclose(nuevo, actual):
            continue
        p_nueva = float(modelo.probabilidad(base.assign(**{var: nuevo}))[0])
        delta = 100 * (p_nueva - prob)
        if delta >= 0.5:
            candidatos.append({
                "factor": var,
                "valor_actual": round(actual, 2),
                "valor_objetivo": round(nuevo, 2),
                "delta_pp": round(delta, 1),
                "mensaje": f"{plantilla.format(a=actual, b=nuevo)} elevaría tu probabilidad estimada "
                           f"de aprobar en +{delta:.0f} puntos porcentuales.",
            })
    candidatos.sort(key=lambda c: c["delta_pp"], reverse=True)
    if not candidatos:
        return [{
            "factor": "mantener_ritmo", "valor_actual": 0, "valor_objetivo": 0, "delta_pp": 0.0,
            "mensaje": "Tu actividad actual ya es favorable: mantener la regularidad de entregas y "
                       "conexiones es lo que más protege tu aprobación.",
        }]
    return candidatos[:max_factores]


# --- Consultas agregadas con Laplace ----------------------------------------------
def consulta_privatizada(epsilon: float, agrupar_por: str) -> tuple[pd.DataFrame, dict, int]:
    """Conteo y promedio acotado de promedio_notas_60d por grupo, solo con consentimiento activo.

    - Acotamiento de contribucion: 1 fila por estudiante (matricula mas reciente) -> Δf_conteo = 1.
    - Suma acotada a [0, 100] -> Δf_suma = 100. Promedio = suma_DP / conteo_DP (post-procesamiento).
    - Grupos disjuntos: composicion paralela. Conteo y suma: ε/2 cada uno (composicion secuencial).
    """
    if agrupar_por not in ("region", "code_module"):  # lista blanca: se interpola en SQL
        raise ValueError("agrupar_por no permitido")
    with conectar() as con:
        d = pd.read_sql(f"""
            SELECT a.id_student, a.{agrupar_por} AS grupo, a.code_presentation, a.promedio_notas_60d
            FROM oulad_analitico a
            WHERE a.id_student IN (
                SELECT id_student FROM consent_receipts
                WHERE finalidad = 'investigacion_externa' AND otorgado = 1 AND revocado_en IS NULL)
        """, con)
    d = d.sort_values("code_presentation").drop_duplicates("id_student", keep="last")
    d["nota"] = d["promedio_notas_60d"].clip(NOTA_MIN, NOTA_MAX)
    real = d.groupby("grupo").agg(conteo_real=("id_student", "size"), suma=("nota", "sum"))

    delta_conteo, delta_suma = 1.0, NOTA_MAX - NOTA_MIN
    m_conteo = Laplace(epsilon=epsilon / 2, sensitivity=delta_conteo)
    m_suma = Laplace(epsilon=epsilon / 2, sensitivity=delta_suma)
    real["conteo_dp"] = [max(m_conteo.randomise(float(v)), 1.0) for v in real["conteo_real"]]
    real["suma_dp"] = [min(max(m_suma.randomise(float(s)), 0.0), NOTA_MAX * c)
                       for s, c in zip(real["suma"], real["conteo_dp"])]
    real["promedio_real"] = real["suma"] / real["conteo_real"]
    real["promedio_dp"] = real["suma_dp"] / real["conteo_dp"]

    mecanismo = {
        "epsilon_total": epsilon,
        "epsilon_por_estadistico": epsilon / 2,
        "delta_f_conteo": delta_conteo,
        "delta_f_suma": delta_suma,
        "escala_conteo": delta_conteo / (epsilon / 2),
        "escala_suma": delta_suma / (epsilon / 2),
        "dominio_promedio": (NOTA_MIN, NOTA_MAX),
        "composicion": "paralela entre grupos disjuntos; secuencial (ε/2 + ε/2) entre conteo y suma",
    }
    return real.reset_index(), mecanismo, len(d)


MODELO: ModeloDP | None = None


def inicializar() -> bool:
    global MODELO
    MODELO, nuevo = cargar_o_entrenar()
    return nuevo
