"""Esquemas Pydantic de la API: consultas privatizadas, prediccion, consentimiento (Kantara) y ARCO."""
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Finalidad = Literal["alerta_temprana_academica", "investigacion_externa"]
Agrupacion = Literal["region", "code_module"]


# --- Consultas privatizadas -------------------------------------------------
class FilaPrivatizada(BaseModel):
    grupo: str
    conteo_dp: float
    promedio_dp: float
    conteo_real: Optional[int] = None      # solo en modo pedagogico
    promedio_real: Optional[float] = None  # solo en modo pedagogico


class MecanismoLaplace(BaseModel):
    epsilon_total: float
    epsilon_por_estadistico: float
    delta_f_conteo: float
    delta_f_suma: float
    escala_conteo: float = Field(description="b = Δf / ε para el conteo")
    escala_suma: float = Field(description="b = Δf / ε para la suma acotada")
    dominio_promedio: tuple[float, float]
    composicion: str


class ConsultaPrivatizadaRespuesta(BaseModel):
    analista: str
    agrupar_por: Agrupacion
    n_estudiantes_con_consentimiento: Optional[int] = None
    mecanismo: MecanismoLaplace
    presupuesto_consumido: float
    presupuesto_restante: float
    presupuesto_maximo: float
    modo_pedagogico: bool
    filas: list[FilaPrivatizada]


# --- Prediccion de riesgo ----------------------------------------------------
class PerfilEstudiante(BaseModel):
    code_module: str
    code_presentation: str
    gender: str
    region: str
    highest_education: str
    imd_band: str
    age_band: str
    num_of_prev_attempts: int = Field(ge=0)
    studied_credits: int = Field(ge=0)
    date_registration: float
    promedio_notas_60d: float = Field(ge=0, le=100)
    entregas_60d: int = Field(ge=0)
    retraso_promedio_60d: float
    total_clics_60d: int = Field(ge=0)
    dias_activos_60d: int = Field(ge=0)


class PrediccionSolicitud(BaseModel):
    id_student: Optional[int] = None
    perfil: Optional[PerfilEstudiante] = None

    @model_validator(mode="after")
    def _uno_de_dos(self):
        if (self.id_student is None) == (self.perfil is None):
            raise ValueError("Indique exactamente uno: id_student o perfil.")
        return self


class ExplicacionAccionable(BaseModel):
    factor: str
    valor_actual: float
    valor_objetivo: float
    delta_pp: float = Field(description="Cambio estimado en la probabilidad de aprobar (puntos porcentuales)")
    mensaje: str


class PrediccionRespuesta(BaseModel):
    id_student: Optional[int]
    probabilidad_aprobar: float
    nivel_alerta: Literal["alta", "media", "baja"]
    explicaciones: list[ExplicacionAccionable]
    epsilon_modelo: float
    aviso_art23: str


# --- Consentimiento (Kantara Consent Receipt v1.1, subconjunto) --------------
class ConsentimientoSolicitud(BaseModel):
    id_student: int
    finalidad: Finalidad = "investigacion_externa"
    otorgado: bool


class ConsentReceipt(BaseModel):
    version: str = "KI-CR-v1.1.0"
    jurisdiction: str = "PE"
    consentReceiptID: str
    consentTimestamp: str
    collectionMethod: str = "Portal del Estudiante (acción afirmativa)"
    piiPrincipalId: int
    piiControllers: list[dict]
    policyUrl: str
    purpose: str
    legalBasis: str
    granted: bool
    revokedAt: Optional[str] = None
    sensitive: bool = True
    spiCat: list[str] = ["rendimiento_academico", "salud (disability)"]


# --- ARCO ---------------------------------------------------------------------
class RevocacionSolicitud(BaseModel):
    id_student: int
    finalidad: Finalidad


class RevocacionRespuesta(BaseModel):
    id_student: int
    finalidad: Finalidad
    receipt_id: str
    revocado_en: str
    mensaje: str


# --- Auditoria ----------------------------------------------------------------
class RegistroAuditoria(BaseModel):
    log_id: int
    usuario_analista: Optional[str]
    consulta: Optional[str]
    epsilon_gastado: Optional[float]
    timestamp: Optional[str]


class AuditoriaRespuesta(BaseModel):
    presupuesto_consumido: float
    presupuesto_restante: float
    presupuesto_maximo: float
    registros: list[RegistroAuditoria]


# --- Demo de ataque de enlace ---------------------------------------------------
class EnlaceSolicitud(BaseModel):
    id_student: int
    code_module: str
    code_presentation: str
    qi: list[str] = Field(min_length=1)
