"""Demo Streamlit: auditoria de re-identificacion, simulador ε-DP y portal del estudiante.

Ejecutar desde la raiz:  streamlit run frontend/app.py   (requiere el backend en API_URL)
Solo componentes nativos de Streamlit; sin CSS/HTML personalizado.
"""
import os
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
FIG_DIR = Path(__file__).resolve().parent.parent / "docs" / "figuras"
QI_BASE = ["region", "age_band", "gender", "highest_education", "imd_band"]
QI_CONTEXTO = ["code_module", "code_presentation"]
COLOR_REAL, COLOR_DP = "#2a78d6", "#eb6834"

st.set_page_config(page_title="Alerta Temprana Privatizada", page_icon="🛡️", layout="wide")


def api(metodo: str, ruta: str, **kwargs):
    """Llama al backend; devuelve (json, error)."""
    try:
        r = requests.request(metodo, f"{API_URL}{ruta}", timeout=30, **kwargs)
    except requests.ConnectionError:
        return None, f"No se pudo conectar con el backend en {API_URL}. ¿Está corriendo uvicorn?"
    if r.status_code >= 400:
        try:
            return None, r.json().get("detail", r.text)
        except ValueError:
            return None, r.text
    return r.json(), None


st.title("🛡️ Alerta temprana de deserción con analítica privatizada")
st.caption("Demo DS3031 · Datos OULAD (ventana de 60 días) con identidades sintéticas · Ley 29733 / DS 016-2024-JUS")

tab1, tab2, tab3 = st.tabs(["🔍 Auditoría de riesgo y ataque de enlace",
                            "🎚️ Simulador ε-DP y equidad",
                            "🎓 Portal del estudiante"])

# =====================================================================================
# Pestaña 1 — Auditoría de riesgo y ataque de enlace
# =====================================================================================
with tab1:
    st.subheader("¿Quitar el nombre y el DNI vuelve anónimos los datos?")
    st.write("A la izquierda está la vista interna, con identidad. A la derecha, la misma tabla tal como se "
             "\"publicaría\": sin nombre, DNI, correo ni `id_student`. La columna **k** indica cuántos registros "
             "comparten exactamente los mismos cuasi-identificadores (QI).")

    muestra, err = api("GET", "/demo/muestra", params={"n": 12})
    if err:
        st.error(err)
        st.stop()
    muestra = pd.DataFrame(muestra)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Vista interna (con identificadores directos)**")
        st.dataframe(muestra[["nombre_completo", "dni", "region", "age_band", "gender", "code_module",
                              "code_presentation", "disability", "target_aprobado"]], hide_index=True)
    with c2:
        st.markdown("**Vista publicada (sin identificadores directos)**")
        st.dataframe(muestra[QI_BASE + QI_CONTEXTO + ["disability", "target_aprobado", "k"]], hide_index=True)

    st.divider()
    st.markdown("#### Simular un ataque de enlace")
    st.write("El atacante tiene un **padrón externo** con nombre, DNI y algunos datos demográficos de la víctima "
             "(por ejemplo, una lista de clase filtrada). Cruza ese padrón con la vista publicada.")

    a1, a2 = st.columns([1, 1])
    with a1:
        opciones = {f"{r.nombre_completo} · {r.code_module}-{r.code_presentation} (k={r.k})": r
                    for r in muestra.itertuples()}
        victima = opciones[st.selectbox("Víctima (registro del padrón externo)", list(opciones))]
    with a2:
        qi_sel = st.multiselect("Cuasi-identificadores que conoce el atacante", QI_BASE + QI_CONTEXTO,
                                default=QI_BASE + QI_CONTEXTO,
                                help="Quita el curso y el semestre para ver cómo cambia el riesgo.")

    if st.button("Ejecutar ataque de enlace", type="primary", disabled=not qi_sel):
        with st.status("Ejecutando ataque de enlace…", expanded=True) as estado:
            st.write("1. Leyendo el padrón externo de la víctima…")
            res, err = api("POST", "/demo/enlace", json={
                "id_student": int(victima.id_student), "code_module": victima.code_module,
                "code_presentation": victima.code_presentation, "qi": qi_sel})
            if err:
                estado.update(label="Error en el ataque", state="error")
                st.error(err)
            else:
                st.write(f"2. Cruzando por {len(qi_sel)} QI contra la vista publicada…")
                st.write(f"3. Coincidencias encontradas: **{res['n_coincidencias']}**")
                estado.update(label="Ataque completado", state="complete", expanded=False)
                st.session_state["enlace"] = res

    res = st.session_state.get("enlace")
    if res:
        m1, m2, m3 = st.columns(3)
        m1.metric("Coincidencias (k)", res["n_coincidencias"])
        m2.metric("¿Re-identificada?", "Sí" if res["re_identificado"] else "No")
        homog = len(res["valores_disability"]) == 1
        m3.metric("¿Discapacidad inferible?", "Sí" if homog else "No",
                  help="Si todas las coincidencias comparten el mismo valor, el atacante lo deduce aunque k > 1 "
                       "(ataque de homogeneidad, l = 1).")
        p = res["padron_externo"]
        if res["re_identificado"]:
            fila = res["coincidencias"][0]
            st.error(f"**Re-identificación exacta.** El registro publicado corresponde a **{p['nombre_completo']}** "
                     f"(DNI {p['dni']}). Datos sensibles expuestos: discapacidad = **{fila['disability']}**, "
                     f"resultado = **{fila['final_result']}**, promedio a 60 días = {fila['promedio_notas_60d']:.1f}.")
        elif homog:
            st.warning(f"No se singulariza a {p['nombre_completo']} (k = {res['n_coincidencias']}), pero **todas** las "
                       f"coincidencias tienen discapacidad = **{next(iter(res['valores_disability']))}**: "
                       "el dato sensible se revela igualmente.")
        else:
            st.success(f"El registro de {p['nombre_completo']} queda oculto entre {res['n_coincidencias']} "
                       "registros con atributos sensibles diversos.")
        with st.expander("Ver padrón externo y registros coincidentes"):
            st.json(p)
            st.dataframe(pd.DataFrame(res["coincidencias"]), hide_index=True)

    with st.expander("¿Por qué importa? Resultados de la auditoría completa (notebook 01)"):
        st.write("- Con solo los 5 QI demográficos, OULAD cumple k ≥ 5: la institución que lo publicó ya lo anonimizó.\n"
                 "- Si se suman curso y semestre (datos que conoce cualquier compañero), 7 396 matrículas quedan con "
                 "k = 1 y el ataque re-identifica al 22 % de un padrón de 2 972 personas con 100 % de precisión.\n"
                 "- Generalizar hasta k ≥ 5 obliga a suprimir región y nivel socioeconómico, y con ello la auditoría "
                 "de equidad. Por eso se adopta **Privacidad Diferencial** para las consultas.")

# =====================================================================================
# Pestaña 2 — Simulador ε-DP y equidad
# =====================================================================================
with tab2:
    st.subheader("Consultas agregadas con Privacidad Diferencial (mecanismo de Laplace)")
    st.write("Las consultas usan **solo** a estudiantes con consentimiento vigente para investigación externa. "
             "Cada consulta gasta presupuesto ε y queda registrada; al agotarse el máximo, el sistema la bloquea.")

    f1, f2, f3 = st.columns([2, 1, 1])
    with f1:
        epsilon = st.slider("ε de esta consulta (menor = más privado, más ruido)", 0.1, 5.0, 0.5, 0.1)
    with f2:
        agrupar = st.selectbox("Agrupar por", ["region", "code_module"],
                               format_func=lambda v: {"region": "Región", "code_module": "Módulo"}[v])
    with f3:
        analista = st.text_input("Analista", value="analista_demo")

    estado_presupuesto, _ = api("GET", "/audit/logs", params={"limite": 1})
    if estado_presupuesto:
        restante = estado_presupuesto["presupuesto_restante"]
        st.caption(f"La consulta se ejecuta solo al pulsar el botón, para no gastar presupuesto al mover el "
                   f"deslizador. Disponible ahora: ε = {restante:.2f}.")

    if st.button("Ejecutar consulta privatizada", type="primary"):
        res, err = api("GET", "/stats/privatized",
                       params={"epsilon": epsilon, "analista": analista, "agrupar_por": agrupar})
        if err:
            st.error(err)
            st.toast("Consulta bloqueada por el privacy accountant", icon="⛔")
        else:
            st.session_state["stats"] = res
            st.toast(f"Consulta registrada: ε = {epsilon} gastado", icon="✅")

    res = st.session_state.get("stats")
    if res:
        m = res["mecanismo"]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("ε de la consulta", f"{m['epsilon_total']:.2f}")
        k2.metric("ε consumido", f"{res['presupuesto_consumido']:.2f}")
        k3.metric("ε restante", f"{res['presupuesto_restante']:.2f}")
        k4.metric("Estudiantes con consentimiento", f"{res['n_estudiantes_con_consentimiento']:,}"
                  if res["n_estudiantes_con_consentimiento"] else "—")
        st.progress(min(res["presupuesto_consumido"] / res["presupuesto_maximo"], 1.0),
                    text=f"Presupuesto usado: {res['presupuesto_consumido']:.2f} de {res['presupuesto_maximo']:.0f}")

        df = pd.DataFrame(res["filas"]).set_index("grupo")
        if res["modo_pedagogico"]:
            g1, g2 = st.columns(2)
            with g1:
                st.markdown("**Promedio de notas a 60 días: real vs. con ruido**")
                st.bar_chart(df[["promedio_real", "promedio_dp"]].rename(
                    columns={"promedio_real": "Real", "promedio_dp": "Privatizado (ε-DP)"}),
                    horizontal=True, stack=False, color=[COLOR_REAL, COLOR_DP], sort=False,
                    x_label="Promedio de notas")
            with g2:
                st.markdown("**Número de estudiantes: real vs. con ruido**")
                st.bar_chart(df[["conteo_real", "conteo_dp"]].rename(
                    columns={"conteo_real": "Real", "conteo_dp": "Privatizado (ε-DP)"}),
                    horizontal=True, stack=False, color=[COLOR_REAL, COLOR_DP], sort=False,
                    x_label="Estudiantes")
            df["error_promedio_%"] = (100 * (df["promedio_dp"] - df["promedio_real"]).abs() / df["promedio_real"]).round(2)
            df["error_conteo_%"] = (100 * (df["conteo_dp"] - df["conteo_real"]).abs() / df["conteo_real"]).round(2)
            e1, e2 = st.columns(2)
            e1.metric("Error relativo medio del promedio", f"{df['error_promedio_%'].mean():.2f} %")
            e2.metric("Error relativo medio del conteo", f"{df['error_conteo_%'].mean():.2f} %")
            st.caption("Los valores reales se muestran solo con fines pedagógicos (MODO_PEDAGOGICO=1). "
                       "En producción, el analista recibe únicamente la columna privatizada.")
        st.dataframe(df, width="stretch")

        with st.expander("Detalles técnicos del mecanismo (sensibilidad y composición)"):
            st.latex(r"\mathcal{M}(D) = f(D) + \mathrm{Lap}\!\left(\frac{\Delta f}{\epsilon}\right)")
            st.write(f"- Δf conteo = {m['delta_f_conteo']:.0f} (cada estudiante aporta una fila) → "
                     f"escala b = {m['escala_conteo']:.2f}\n"
                     f"- Δf suma acotada a [{m['dominio_promedio'][0]:.0f}, {m['dominio_promedio'][1]:.0f}] = "
                     f"{m['delta_f_suma']:.0f} → escala b = {m['escala_suma']:.2f}\n"
                     f"- Composición: {m['composicion']}\n"
                     "- El promedio = suma_DP / conteo_DP es post-procesamiento y no consume presupuesto "
                     "(Dwork et al., 2006).")
            st.json(m)

    with st.expander("📜 Registro de auditoría (audit_logs)"):
        logs, err = api("GET", "/audit/logs", params={"limite": 25})
        if err:
            st.error(err)
        else:
            st.dataframe(pd.DataFrame(logs["registros"]), hide_index=True)
            st.divider()
            st.write("**Administración (Oficial de Datos Personales):** abre un nuevo periodo de presupuesto. "
                     "Queda registrado y no borra el historial.")
            if st.button("Iniciar nuevo periodo de presupuesto"):
                _, err = api("POST", "/audit/nuevo-periodo", params={"responsable": "oficial_datos"})
                if err:
                    st.error(err)
                else:
                    st.session_state.pop("stats", None)
                    st.toast("Nuevo periodo iniciado: ε restante = 10", icon="🔄")
                    st.rerun()

    st.divider()
    st.subheader("Trilema privacidad – utilidad – equidad (notebook 02)")
    q1, q2 = st.columns(2)
    if (FIG_DIR / "curva_privacidad_utilidad.png").exists():
        q1.image(str(FIG_DIR / "curva_privacidad_utilidad.png"), width="stretch")
        q2.image(str(FIG_DIR / "trilema_privacidad_equidad.png"), width="stretch")
    st.write("- **Consultas:** con ε = 0.5 el error medio es < 0.7 %. Para grupos grandes, la DP es casi gratuita.\n"
             "- **Modelo:** con ε = 5 el AUC es 0.874, frente a 0.877 sin DP. Con ε ≤ 2 se pierden ≥ 5 pp de AUC "
             "y aumentan las alertas omitidas.\n"
             "- **Equidad:** la DP no degradó más al grupo `disability = Y` (no se observó *the poor get poorer*). "
             "Sin embargo, el modelo base ya incumple la regla de los 4/5 (DI = 0.79) y está peor calibrado para ese "
             "grupo. Por eso cada alerta requiere revisión humana.")

# =====================================================================================
# Pestaña 3 — Portal del estudiante
# =====================================================================================
with tab3:
    st.subheader("Portal del estudiante")
    id_student = st.number_input("Tu código de estudiante (inicio de sesión simulado)", min_value=1,
                                 value=11391, step=1)

    st.markdown("#### Aviso de privacidad")
    st.write("**En pocas palabras:**\n"
             "- Usamos tu actividad en el aula virtual de los primeros 60 días para avisarte a tiempo si podrías "
             "necesitar apoyo. Esto forma parte de tu servicio educativo.\n"
             "- Aparte, te pedimos permiso para usar tus datos, **protegidos con ruido matemático**, en "
             "investigaciones externas. Puedes decir que no; eso no afecta tus notas ni tus servicios.\n"
             "- Puedes cambiar de opinión cuando quieras, con un solo clic.")
    with st.expander("Detalles legales y técnicos"):
        st.write(
            "**Responsable:** Universidad (entorno de demostración). **Oficial de Datos Personales:** "
            "odp@universidad-demo.edu.pe\n\n"
            "| Finalidad | Base legal | ¿Puedes negarte? |\n|---|---|---|\n"
            "| Alerta temprana académica | Relación contractual educativa (Ley 29733, Art. 14) | Derecho de oposición ante el ODP |\n"
            "| Investigación externa | Consentimiento expreso, libre y separado | Sí, sin consecuencias |\n\n"
            "**Datos tratados:** curso, región, banda de edad, nivel educativo, índice socioeconómico de tu zona "
            "(IMD) y actividad académica de 60 días. La condición de discapacidad es un dato sensible: no se usa "
            "para predecir, solo para auditar que el sistema no discrimine.\n\n"
            "**Protección técnica:** las consultas para investigación aplican Privacidad Diferencial (Laplace, "
            "ε ≤ 5 por consulta, máximo acumulado de 10 por periodo). El modelo de riesgo se entrena con "
            "DP-Regresión Logística (ε = 5). Las identidades se guardan en una tabla separada con acceso restringido.\n\n"
            "**Tus derechos (ARCO + DS 016-2024-JUS):** acceso, rectificación, cancelación, oposición, "
            "portabilidad y desindexación. **Decisiones automatizadas (Art. 23):** ninguna alerta produce efectos "
            "sin revisión de un tutor, y puedes impugnarla. **Retención:** datos de actividad durante el periodo "
            "académico más un año; luego se eliminan. **Brechas:** se notifican a la ANPD en un plazo de 48 h.")

    recibos, err = api("GET", f"/consent/{int(id_student)}")
    if err:
        st.error(err)
    else:
        inv = next((r for r in recibos if r["purpose"] == "investigacion_externa"), None)
        vigente = bool(inv and inv["granted"] and not inv["revokedAt"])

        st.markdown("#### ¿Autorizas el uso de tus datos protegidos en investigación externa?")
        st.caption(f"Estado actual: **{'Autorizado' if vigente else 'No autorizado'}**. "
                   "Ninguna opción viene marcada: tu decisión solo se registra al pulsar un botón.")
        b1, b2 = st.columns(2)
        decision = None
        if b1.button("Aceptar", key="aceptar", width="stretch"):
            decision = True
        if b2.button("Rechazar", key="rechazar", width="stretch"):
            decision = False
        if decision is not None:
            _, err = api("POST", "/consent", json={"id_student": int(id_student),
                                                    "finalidad": "investigacion_externa", "otorgado": decision})
            if err:
                st.error(err)
            else:
                st.toast("Decisión registrada: " + ("aceptaste" if decision else "rechazaste"), icon="📝")
                st.rerun()

        if st.button("Revocar mi consentimiento (1 clic)", disabled=not vigente,
                     help="Disponible solo si tienes un consentimiento vigente."):
            r, err = api("POST", "/arco/revocar", json={"id_student": int(id_student),
                                                         "finalidad": "investigacion_externa"})
            if err:
                st.error(err)
            else:
                st.toast(r["mensaje"], icon="🔒")
                st.rerun()

        with st.expander("Ver mis recibos de consentimiento (estándar Kantara)"):
            st.json(recibos)

    st.divider()
    st.markdown("#### Mi riesgo académico")
    st.caption("La alerta temprana se basa en tu relación educativa, no en el consentimiento anterior.")
    if st.button("Consultar mi riesgo", type="primary"):
        pred, err = api("POST", "/predict/student", json={"id_student": int(id_student)})
        if err:
            st.error(err)
        else:
            st.session_state["pred"] = pred

    pred = st.session_state.get("pred")
    if pred and pred["id_student"] == int(id_student):
        r1, r2 = st.columns(2)
        r1.metric("Probabilidad estimada de aprobar", f"{100 * pred['probabilidad_aprobar']:.0f} %")
        r2.metric("Nivel de alerta", pred["nivel_alerta"].capitalize())
        aviso = {"alta": st.error, "media": st.warning, "baja": st.success}[pred["nivel_alerta"]]
        aviso({"alta": "🔴 Te recomendamos agendar una tutoría esta semana.",
               "media": "🟠 Algunas acciones concretas pueden mejorar tu situación.",
               "baja": "🟢 Vas por buen camino."}[pred["nivel_alerta"]])
        st.markdown("**¿Qué puedes hacer?**")
        for e in pred["explicaciones"]:
            st.write(f"- {e['mensaje']}")
        with st.expander("¿Cómo se calculó y cuáles son mis derechos?"):
            st.write(f"- Modelo: regresión logística con Privacidad Diferencial (ε = {pred['epsilon_modelo']:g}). "
                     "Tus datos no pueden deducirse a partir del modelo.\n"
                     "- Cada sugerencia cambia **una sola** variable que depende de ti y recalcula la estimación. "
                     "Es una orientación basada en patrones, no una garantía.\n"
                     "- El modelo considera tu curso y datos demográficos (región, banda de edad, género, nivel "
                     "educativo, IMD), pero las sugerencias **nunca** te piden cambiar algo que no depende de ti. "
                     "La condición de discapacidad no forma parte del modelo.\n"
                     f"- {pred['aviso_art23']}")
            st.json(pred)
