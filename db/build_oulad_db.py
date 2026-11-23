import sqlite3
import pandas as pd
import numpy as np

# 1. Cargar tabla base de estudiantes
info = pd.read_csv("studentInfo.csv")
info["target_aprobado"] = info["final_result"].isin(["Pass", "Distinction"]).astype(int)

# 2. Unir fecha de registro (evitando leakage de date_unregistration)
reg = pd.read_csv("studentRegistration.csv")[
    ["code_module", "code_presentation", "id_student", "date_registration"]
]
df = info.merge(reg, on=["code_module", "code_presentation", "id_student"], how="left")

# 3. Agregar evaluaciones tempranas (primeros 60 días)
assessments = pd.read_csv("assessments.csv")
st_assess = pd.read_csv("studentAssessment.csv").merge(
    assessments[["id_assessment", "code_module", "code_presentation", "date"]],
    on="id_assessment",
    how="left"
)
st_assess_60 = st_assess[st_assess["date_submitted"] <= 60].copy()
st_assess_60["retraso"] = st_assess_60["date_submitted"] - st_assess_60["date"]

agg_assess = st_assess_60.groupby(["code_module", "code_presentation", "id_student"]).agg(
    promedio_notas_60d=("score", "mean"),
    entregas_60d=("id_assessment", "count"),
    retraso_promedio_60d=("retraso", "mean")
).reset_index()

df = df.merge(agg_assess, on=["code_module", "code_presentation", "id_student"], how="left")

# 4. Agregar clics del VLE por chunks (primeros 60 días, sin saturar RAM)
vle_chunks = []
for chunk in pd.read_csv("studentVle.csv", chunksize=500_000):
    c60 = chunk[chunk["date"] <= 60]
    grouped = c60.groupby(["code_module", "code_presentation", "id_student"]).agg(
        total_clics_60d=("sum_click", "sum"),
        dias_activos_60d=("date", "nunique")
    ).reset_index()
    vle_chunks.append(grouped)

agg_vle = pd.concat(vle_chunks).groupby(
    ["code_module", "code_presentation", "id_student"]
).agg(
    total_clics_60d=("total_clics_60d", "sum"),
    dias_activos_60d=("dias_activos_60d", "sum")
).reset_index()

df = df.merge(agg_vle, on=["code_module", "code_presentation", "id_student"], how="left")

# Imputación básica de actividad nula en los primeros 60 días
for col in ["promedio_notas_60d", "entregas_60d", "retraso_promedio_dias", "total_clics_60d", "dias_activos_60d"]:
    if col in df.columns:
        df[col] = df[col].fillna(0)

# 5. Guardar en Base de Datos SQLite (requerimiento técnico del proyecto)
conn = sqlite3.connect("oulad_proyecto.db")
df.to_sql("oulad_analitico", conn, if_exists="replace", index=False)

# Crear tabla vacía de consent_receipts y audit_logs para el backend
conn.execute("""
CREATE TABLE IF NOT EXISTS consent_receipts (
    receipt_id TEXT PRIMARY KEY,
    id_student INTEGER,
    finalidad TEXT,
    base_legal TEXT,
    otorgado INTEGER,
    timestamp TEXT,
    revocado_en TEXT
)
""")
conn.execute("""
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_analista TEXT,
    consulta TEXT,
    epsilon_gastado REAL,
    timestamp TEXT
)
""")
conn.commit()
conn.close()
print(f"Base de datos creada con éxito. Registros consolidados: {len(df)}")