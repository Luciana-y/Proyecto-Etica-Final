"""Enriquece db/oulad_proyecto.db con identidades sinteticas y recibos de consentimiento.

- estudiantes_identidad: identificadores directos sinteticos (Faker es_PE), separados de la tabla analitica.
- consent_receipts: recibos estilo Kantara Initiative (Consent Receipt Specification v1.1).
  * alerta_temprana_academica -> base legal: relacion contractual educativa (Ley 29733, Art. 14), no consentimiento.
  * investigacion_externa     -> consentimiento expreso opt-in separado (~65% otorga, ~35% rechaza).
Datos 100% sinteticos; reproducibles mediante semilla fija.
"""
import os
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "db", "oulad_proyecto.db")

SEED = 42
TASA_OPT_IN_INVESTIGACION = 0.65
DOMINIO_CORREO = "alumnos.universidad-demo.edu.pe"
FECHA_BASE = datetime(2026, 3, 1)


def crear_faker() -> Faker:
    # Faker no incluye locale es_PE; se usan locales andinos/latinoamericanos cercanos como sustituto.
    try:
        return Faker("es_PE")
    except AttributeError:
        return Faker(["es_CO", "es_CL", "es_MX"])


def generar_identidades(ids: np.ndarray, fake: Faker, rng: np.random.Generator) -> pd.DataFrame:
    dnis = rng.choice(np.arange(10_000_000, 80_000_000), size=len(ids), replace=False)
    filas = []
    for id_student, dni in zip(ids, dnis):
        nombre = fake.first_name()
        apellido1, apellido2 = fake.last_name(), fake.last_name()
        usuario = unicodedata.normalize("NFKD", f"{nombre[0]}{apellido1}.{id_student}".lower())
        usuario = usuario.encode("ascii", "ignore").decode().replace(" ", "")
        filas.append({
            "id_student": int(id_student),
            "nombre_completo": f"{nombre} {apellido1} {apellido2}",
            "dni": f"{dni:08d}",
            "correo_institucional": f"{usuario}@{DOMINIO_CORREO}",
        })
    return pd.DataFrame(filas)


def generar_recibos(ids: np.ndarray, rng: np.random.Generator) -> pd.DataFrame:
    n = len(ids)
    offsets = rng.integers(0, 30 * 24 * 3600, size=n)
    ts = [(FECHA_BASE + timedelta(seconds=int(s))).isoformat(timespec="seconds") for s in offsets]
    def rid() -> str:
        # UUIDv4 determinista a partir del rng (reproducible)
        return str(uuid.UUID(bytes=rng.bytes(16), version=4))

    alerta = pd.DataFrame({
        "receipt_id": [rid() for _ in range(n)],
        "id_student": ids.astype(int),
        "finalidad": "alerta_temprana_academica",
        "base_legal": "relacion_contractual_educativa",
        "otorgado": 1,
        "timestamp": ts,
        "revocado_en": None,
    })
    investigacion = pd.DataFrame({
        "receipt_id": [rid() for _ in range(n)],
        "id_student": ids.astype(int),
        "finalidad": "investigacion_externa",
        "base_legal": "consentimiento_expreso",
        "otorgado": (rng.random(n) < TASA_OPT_IN_INVESTIGACION).astype(int),
        "timestamp": ts,
        "revocado_en": None,
    })
    return pd.concat([alerta, investigacion], ignore_index=True)


def main() -> None:
    rng = np.random.default_rng(SEED)
    fake = crear_faker()
    Faker.seed(SEED)

    with sqlite3.connect(DB_PATH) as con:
        ids = np.sort(pd.read_sql("SELECT DISTINCT id_student FROM oulad_analitico", con)["id_student"].to_numpy())

        identidades = generar_identidades(ids, fake, rng)
        con.execute("DROP TABLE IF EXISTS estudiantes_identidad")
        con.execute("""
            CREATE TABLE estudiantes_identidad (
                id_student INTEGER PRIMARY KEY,
                nombre_completo TEXT NOT NULL,
                dni TEXT UNIQUE NOT NULL,
                correo_institucional TEXT UNIQUE NOT NULL
            )""")
        identidades.to_sql("estudiantes_identidad", con, if_exists="append", index=False)

        recibos = generar_recibos(ids, rng)
        con.execute("DELETE FROM consent_receipts")
        recibos.to_sql("consent_receipts", con, if_exists="append", index=False)
        con.commit()

        print("estudiantes_identidad:", con.execute("SELECT COUNT(*) FROM estudiantes_identidad").fetchone()[0],
              "| ids unicos en oulad_analitico:", len(ids))
        print(pd.read_sql("""
            SELECT finalidad, base_legal, otorgado, COUNT(*) AS n,
                   ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY finalidad), 1) AS pct
            FROM consent_receipts GROUP BY finalidad, base_legal, otorgado""", con).to_string(index=False))
        print(pd.read_sql("SELECT * FROM estudiantes_identidad LIMIT 3", con).to_string(index=False))


if __name__ == "__main__":
    main()
