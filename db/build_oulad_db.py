# Construye db/oulad_proyecto.db y data/processed/oulad_analitico.parquet a partir de OULAD.
# Ventana de observacion: primeros 60 dias del curso (alerta temprana).

import os
import sqlite3

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
PROCESSED_DIR = os.path.join(BASE_DIR, "data", "processed")
DB_DIR = os.path.join(BASE_DIR, "db")
DB_PATH = os.path.join(DB_DIR, "oulad_proyecto.db")
PARQUET_PATH = os.path.join(PROCESSED_DIR, "oulad_analitico.parquet")

VENTANA_DIAS = 60
KEYS = ["code_module", "code_presentation", "id_student"]
NA_VALUES = ["", "?"]


def raw(nombre: str) -> str:
    return os.path.join(RAW_DIR, nombre)


def cargar_base() -> pd.DataFrame:
    info = pd.read_csv(raw("studentInfo.csv"), na_values=NA_VALUES)
    info["target_aprobado"] = info["final_result"].isin(["Pass", "Distinction"]).astype(int)

    reg = pd.read_csv(raw("studentRegistration.csv"), na_values=NA_VALUES,
                      usecols=KEYS + ["date_registration"])
    return info.merge(reg, on=KEYS, how="left")


def features_evaluaciones() -> pd.DataFrame:
    sa = pd.read_csv(raw("studentAssessment.csv"), na_values=NA_VALUES)
    asm = pd.read_csv(raw("assessments.csv"), na_values=NA_VALUES,
                      usecols=["id_assessment", "code_module", "code_presentation", "date"])
    df = sa.merge(asm, on="id_assessment", how="inner")
    df = df[df["date_submitted"] <= VENTANA_DIAS].copy()
    df["retraso"] = df["date_submitted"] - df["date"]
    return (
        df.groupby(KEYS)
        .agg(promedio_notas_60d=("score", "mean"),
             entregas_60d=("id_assessment", "count"),
             retraso_promedio_60d=("retraso", "mean"))
        .reset_index()
    )


def features_vle(chunksize: int = 500_000) -> pd.DataFrame:
    clics, dias = [], []
    lector = pd.read_csv(raw("studentVle.csv"), chunksize=chunksize,
                         usecols=KEYS + ["date", "sum_click"])
    for chunk in lector:
        chunk = chunk[chunk["date"] <= VENTANA_DIAS]
        if chunk.empty:
            continue
        clics.append(chunk.groupby(KEYS)["sum_click"].sum())
        dias.append(chunk[KEYS + ["date"]].drop_duplicates())

    total_clics = (pd.concat(clics).groupby(level=KEYS).sum()
                   .rename("total_clics_60d").reset_index())
    # Deduplicacion global: un mismo dia puede aparecer en varios chunks.
    dias_activos = (pd.concat(dias, ignore_index=True).drop_duplicates()
                    .groupby(KEYS)["date"].count()
                    .rename("dias_activos_60d").reset_index())
    return total_clics.merge(dias_activos, on=KEYS, how="outer")


def imputar(df: pd.DataFrame) -> pd.DataFrame:
    cols_cero = ["promedio_notas_60d", "entregas_60d", "retraso_promedio_60d",
                 "total_clics_60d", "dias_activos_60d"]
    faltantes = [c for c in cols_cero if c not in df.columns]
    if faltantes:
        raise KeyError(f"Columnas esperadas no generadas: {faltantes}")
    df[cols_cero] = df[cols_cero].fillna(0)
    for c in ["entregas_60d", "total_clics_60d", "dias_activos_60d"]:
        df[c] = df[c].astype(int)
    df["date_registration"] = df["date_registration"].fillna(df["date_registration"].median())
    # imd_band tiene faltantes en origen; se conserva como categoria explicita.
    df["imd_band"] = df["imd_band"].fillna("Desconocido")
    return df


def crear_tablas_gobernanza(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS consent_receipts (
            receipt_id TEXT PRIMARY KEY,
            id_student INTEGER,
            finalidad TEXT,
            base_legal TEXT,
            otorgado INTEGER,
            timestamp TEXT,
            revocado_en TEXT
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_analista TEXT,
            consulta TEXT,
            epsilon_gastado REAL,
            timestamp TEXT
        );
    """)


def main() -> None:
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    df = cargar_base()
    df = df.merge(features_evaluaciones(), on=KEYS, how="left")
    df = df.merge(features_vle(), on=KEYS, how="left")
    df = imputar(df)

    df.to_parquet(PARQUET_PATH, index=False)
    with sqlite3.connect(DB_PATH) as con:
        df.to_sql("oulad_analitico", con, if_exists="replace", index=False)
        crear_tablas_gobernanza(con)

    print(f"Filas: {len(df)}")
    print(f"Columnas: {list(df.columns)}")
    nulos = df.isna().sum()
    print(f"Nulos totales: {int(nulos.sum())}")
    if nulos.any():
        print(nulos[nulos > 0])


if __name__ == "__main__":
    main()
