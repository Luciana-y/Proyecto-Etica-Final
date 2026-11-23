# API FastAPI: consultas ε-DP con privacy accountant, prediccion explicable, consentimiento y ARCO.

# Ejecutar desde la raiz del proyecto:  uvicorn backend.main:app --reload

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import pandas as pd
from fastapi import FastAPI, HTTPException, Query

from . import dp_engine
from .models import (
    Agrupacion, AuditoriaRespuesta, ConsentimientoSolicitud, ConsentReceipt, ConsultaPrivatizadaRespuesta,
    EnlaceSolicitud, PrediccionRespuesta, PrediccionSolicitud, RegistroAuditoria, RevocacionRespuesta,
    RevocacionSolicitud,
)

MAX_EPSILON = 10.0
MAX_EPSILON_POR_CONSULTA = 5.0
# Devuelve valores reales junto a los privatizados y habilita /demo. Desactivar en produccion.
MODO_PEDAGOGICO = os.getenv("MODO_PEDAGOGICO", "1") == "1"

CONSULTA_STATS = "GET /stats/privatized"
MARCA_PERIODO = "RESET_PERIODO_PRESUPUESTO"
BASES_LEGALES = {
    "alerta_temprana_academica": "relacion_contractual_educativa",
    "investigacion_externa": "consentimiento_expreso",
}
CONTROLADOR = [{"piiController": "Universidad (entorno de demostración)", "contact": "Oficial de Datos Personales",
                "address": "Lima, Perú", "email": "odp@universidad-demo.edu.pe"}]
POLITICA_URL = "https://universidad-demo.edu.pe/privacidad/v1.0"
AVISO_ART23 = ("Esta estimación es orientativa y no produce efectos por sí sola: un tutor revisa cada alerta "
               "antes de cualquier acción. Tienes derecho a solicitar revisión humana, expresar tu punto de vista "
               "e impugnar el resultado (Ley 29733, Art. 23; DS 016-2024-JUS).")


def ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def registrar_auditoria(usuario: str, consulta: str, epsilon: float = 0.0) -> None:
    with dp_engine.conectar() as con:
        con.execute("INSERT INTO audit_logs (usuario_analista, consulta, epsilon_gastado, timestamp) "
                    "VALUES (?, ?, ?, ?)", (usuario, consulta, epsilon, ahora()))


def presupuesto_consumido() -> float:
    """Suma de ε de consultas agregadas desde el ultimo inicio de periodo."""
    with dp_engine.conectar() as con:
        ultimo = con.execute("SELECT COALESCE(MAX(log_id), 0) FROM audit_logs WHERE consulta = ?",
                             (MARCA_PERIODO,)).fetchone()[0]
        total = con.execute("SELECT COALESCE(SUM(epsilon_gastado), 0) FROM audit_logs "
                            "WHERE log_id > ? AND consulta LIKE ?", (ultimo, CONSULTA_STATS + "%")).fetchone()[0]
    return float(total)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if dp_engine.inicializar():
        registrar_auditoria("sistema", f"ENTRENAMIENTO modelo DP-LogReg (presupuesto propio, "
                                       f"ε={dp_engine.EPSILON_MODELO})", 0.0)
    yield


app = FastAPI(title="Alerta Temprana con Analítica Privatizada", version="1.0", lifespan=lifespan)


# Consultas privatizadas
@app.get("/stats/privatized", response_model=ConsultaPrivatizadaRespuesta)
def stats_privatizadas(
    epsilon: float = Query(gt=0, le=MAX_EPSILON_POR_CONSULTA),
    analista: str = Query(min_length=1, max_length=64),
    agrupar_por: Agrupacion = "region",
):
    consumido = presupuesto_consumido()
    if consumido + epsilon > MAX_EPSILON + 1e-9:
        raise HTTPException(403, detail=f"Presupuesto de privacidad agotado: consumido {consumido:.2f}, "
                                        f"solicitado {epsilon:.2f}, máximo {MAX_EPSILON:.2f}.")
    tabla, mecanismo, n = dp_engine.consulta_privatizada(epsilon, agrupar_por)
    registrar_auditoria(analista, f"{CONSULTA_STATS} agrupar_por={agrupar_por}", epsilon)
    consumido += epsilon

    filas = []
    for r in tabla.itertuples():
        fila = {"grupo": r.grupo, "conteo_dp": round(r.conteo_dp, 2), "promedio_dp": round(r.promedio_dp, 2)}
        if MODO_PEDAGOGICO:
            fila |= {"conteo_real": int(r.conteo_real), "promedio_real": round(r.promedio_real, 2)}
        filas.append(fila)
    return {
        "analista": analista, "agrupar_por": agrupar_por,
        "n_estudiantes_con_consentimiento": n if MODO_PEDAGOGICO else None,
        "mecanismo": mecanismo, "presupuesto_consumido": round(consumido, 4),
        "presupuesto_restante": round(MAX_EPSILON - consumido, 4), "presupuesto_maximo": MAX_EPSILON,
        "modo_pedagogico": MODO_PEDAGOGICO, "filas": filas,
    }


# Prediccion de riesgo
@app.post("/predict/student", response_model=PrediccionRespuesta)
def predecir_estudiante(sol: PrediccionSolicitud):
    if sol.id_student is not None:
        with dp_engine.conectar() as con:
            d = pd.read_sql("SELECT * FROM oulad_analitico WHERE id_student = ? "
                            "ORDER BY code_presentation DESC LIMIT 1", con, params=(sol.id_student,))
        if d.empty:
            raise HTTPException(404, detail="Estudiante no encontrado.")
        datos = d.iloc[0].to_dict()
    else:
        datos = sol.perfil.model_dump()

    prob = float(dp_engine.MODELO.probabilidad(pd.DataFrame([datos]))[0])
    registrar_auditoria(f"estudiante:{sol.id_student}" if sol.id_student else "perfil_anonimo",
                        "POST /predict/student", 0.0)
    return {
        "id_student": sol.id_student,
        "probabilidad_aprobar": round(prob, 4),
        "nivel_alerta": dp_engine.nivel_alerta(prob),
        "explicaciones": dp_engine.generar_explicacion_accionable(datos, prob),
        "epsilon_modelo": dp_engine.MODELO.epsilon,
        "aviso_art23": AVISO_ART23,
    }


# Consentimiento (Kantara)
def _recibo(fila) -> dict:
    receipt_id, id_student, finalidad, base_legal, otorgado, ts, revocado = fila
    return ConsentReceipt(
        consentReceiptID=receipt_id, consentTimestamp=ts, piiPrincipalId=id_student,
        piiControllers=CONTROLADOR, policyUrl=POLITICA_URL, purpose=finalidad, legalBasis=base_legal,
        granted=bool(otorgado), revokedAt=revocado,
    ).model_dump()


@app.get("/consent/{id_student}", response_model=list[ConsentReceipt])
def consultar_consentimientos(id_student: int):
    with dp_engine.conectar() as con:
        filas = con.execute("""
            SELECT receipt_id, id_student, finalidad, base_legal, otorgado, timestamp, revocado_en
            FROM consent_receipts c WHERE id_student = ? AND rowid = (
                SELECT MAX(rowid) FROM consent_receipts WHERE id_student = c.id_student AND finalidad = c.finalidad)
            ORDER BY finalidad""", (id_student,)).fetchall()
    if not filas:
        raise HTTPException(404, detail="Estudiante sin recibos de consentimiento.")
    return [_recibo(f) for f in filas]


@app.post("/consent", response_model=ConsentReceipt)
def registrar_consentimiento(sol: ConsentimientoSolicitud):
    if BASES_LEGALES[sol.finalidad] != "consentimiento_expreso":
        raise HTTPException(422, detail="Esta finalidad no se basa en consentimiento (Ley 29733, Art. 14).")
    ts = ahora()
    receipt_id = str(uuid.uuid4())
    with dp_engine.conectar() as con:
        con.execute("UPDATE consent_receipts SET revocado_en = ? WHERE id_student = ? AND finalidad = ? "
                    "AND revocado_en IS NULL", (ts, sol.id_student, sol.finalidad))
        con.execute("INSERT INTO consent_receipts VALUES (?, ?, ?, ?, ?, ?, NULL)",
                    (receipt_id, sol.id_student, sol.finalidad, BASES_LEGALES[sol.finalidad], int(sol.otorgado), ts))
    registrar_auditoria(f"estudiante:{sol.id_student}",
                        f"CONSENTIMIENTO {'otorgado' if sol.otorgado else 'rechazado'} finalidad={sol.finalidad}")
    return _recibo((receipt_id, sol.id_student, sol.finalidad, BASES_LEGALES[sol.finalidad],
                    int(sol.otorgado), ts, None))


@app.post("/arco/revocar", response_model=RevocacionRespuesta)
def revocar(sol: RevocacionSolicitud):
    if BASES_LEGALES[sol.finalidad] != "consentimiento_expreso":
        raise HTTPException(422, detail="La alerta temprana se basa en la relación educativa, no en consentimiento: "
                                        "no se revoca, pero puedes ejercer tu derecho de oposición ante el "
                                        "Oficial de Datos Personales.")
    ts = ahora()
    with dp_engine.conectar() as con:
        fila = con.execute("SELECT receipt_id FROM consent_receipts WHERE id_student = ? AND finalidad = ? "
                           "AND otorgado = 1 AND revocado_en IS NULL", (sol.id_student, sol.finalidad)).fetchone()
        if fila is None:
            raise HTTPException(404, detail="No existe un consentimiento vigente que revocar.")
        con.execute("UPDATE consent_receipts SET otorgado = 0, revocado_en = ? WHERE receipt_id = ?", (ts, fila[0]))
    registrar_auditoria(f"estudiante:{sol.id_student}", f"ARCO revocacion finalidad={sol.finalidad}")
    return {"id_student": sol.id_student, "finalidad": sol.finalidad, "receipt_id": fila[0], "revocado_en": ts,
            "mensaje": "Consentimiento revocado. Tus datos se excluyen de las consultas de investigación desde ahora."}


# Auditoria
@app.get("/audit/logs", response_model=AuditoriaRespuesta)
def logs_auditoria(limite: int = Query(20, ge=1, le=200)):
    with dp_engine.conectar() as con:
        filas = con.execute("SELECT log_id, usuario_analista, consulta, epsilon_gastado, timestamp "
                            "FROM audit_logs ORDER BY log_id DESC LIMIT ?", (limite,)).fetchall()
    consumido = presupuesto_consumido()
    return {
        "presupuesto_consumido": round(consumido, 4), "presupuesto_restante": round(MAX_EPSILON - consumido, 4),
        "presupuesto_maximo": MAX_EPSILON,
        "registros": [RegistroAuditoria(log_id=f[0], usuario_analista=f[1], consulta=f[2],
                                        epsilon_gastado=f[3], timestamp=f[4]) for f in filas],
    }


@app.post("/audit/nuevo-periodo")
def nuevo_periodo(responsable: str = Query(min_length=1)):
    registrar_auditoria(responsable, MARCA_PERIODO, 0.0)
    return {"mensaje": "Nuevo periodo de presupuesto iniciado.", "presupuesto_restante": MAX_EPSILON}


# Demo pedagogica: ataque de enlace
QI_VALIDOS = ["region", "age_band", "gender", "highest_education", "imd_band", "code_module", "code_presentation"]


def _exigir_demo():
    if not MODO_PEDAGOGICO:
        raise HTTPException(404, detail="Endpoint deshabilitado fuera del modo pedagógico.")


@app.get("/demo/muestra")
def demo_muestra(n: int = Query(12, ge=1, le=50), semilla: int = 7):
    _exigir_demo()
    with dp_engine.conectar() as con:
        d = pd.read_sql("""
            SELECT i.nombre_completo, i.dni, i.correo_institucional, a.id_student, a.region, a.age_band, a.gender,
                   a.highest_education, a.imd_band, a.code_module, a.code_presentation, a.disability,
                   a.target_aprobado, a.promedio_notas_60d
            FROM oulad_analitico a JOIN estudiantes_identidad i USING (id_student)""", con)
    d["k"] = d.groupby(QI_VALIDOS)["id_student"].transform("size")
    # Muestra estratificada: mitad singularizables (k=1) y mitad protegidas (k>1), para contrastar ambos casos.
    unicos = d[d["k"] == 1].sample(n=n // 2, random_state=semilla)
    resto = d[d["k"] > 1].sample(n=n - n // 2, random_state=semilla)
    return pd.concat([unicos, resto]).sample(frac=1, random_state=semilla).to_dict(orient="records")


@app.post("/demo/enlace")
def demo_enlace(sol: EnlaceSolicitud):
    _exigir_demo()
    if not set(sol.qi) <= set(QI_VALIDOS):
        raise HTTPException(422, detail=f"QI permitidos: {QI_VALIDOS}")
    with dp_engine.conectar() as con:
        d = pd.read_sql("SELECT * FROM oulad_analitico", con)
        identidad = con.execute("SELECT nombre_completo, dni FROM estudiantes_identidad WHERE id_student = ?",
                                (sol.id_student,)).fetchone()
    objetivo = d[(d["id_student"] == sol.id_student) & (d["code_module"] == sol.code_module)
                 & (d["code_presentation"] == sol.code_presentation)]
    if objetivo.empty or identidad is None:
        raise HTTPException(404, detail="Registro objetivo no encontrado.")
    conocido = objetivo.iloc[0][sol.qi]
    publicada = d.drop(columns=["id_student"])  # vista sin identificadores
    coincidencias = publicada[(publicada[sol.qi] == conocido.values).all(axis=1)]
    registrar_auditoria("demo_ataque_enlace", f"POST /demo/enlace qi={'+'.join(sol.qi)}")
    unico = len(coincidencias) == 1
    return {
        "padron_externo": {"nombre_completo": identidad[0], "dni": identidad[1], **conocido.to_dict()},
        "n_coincidencias": int(len(coincidencias)),
        "re_identificado": unico,
        "valores_disability": coincidencias["disability"].value_counts().to_dict(),
        "valores_target": {str(k): int(v) for k, v in coincidencias["target_aprobado"].value_counts().items()},
        "coincidencias": coincidencias[sol.qi + ["disability", "final_result", "promedio_notas_60d",
                                                 "total_clics_60d"]].head(10).to_dict(orient="records"),
    }
