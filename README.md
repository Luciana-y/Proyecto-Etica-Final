# Alerta Temprana de Deserción con Analítica Privatizada

Proyecto final del curso **DS3031 — Ética y Seguridad de Datos** (Tipo 1).

**Integrantes:**
- Valentina Álvarez Beraun
- Luciana Yangali Cáceres

## Idea de la aplicación

Plataforma para una universidad peruana que detecta, con la actividad de los **primeros 60 días** del ciclo, a los estudiantes con riesgo de desaprobar o abandonar. El objetivo es ofrecerles apoyo a tiempo sin comprometer su privacidad.

La plataforma resuelve tres problemas:

1. **Riesgo de re-identificación.** Quitar nombres y DNI no basta: cruzando cuasi-identificadores (región, edad, curso, semestre) se re-identifica al 22 % de los estudiantes. La app lo demuestra con un ataque de enlace en vivo.
2. **Analítica con privacidad diferencial (ε-DP).** Los analistas e investigadores reciben estadísticas con ruido de Laplace, con un presupuesto ε limitado y auditado. Solo se usan datos de estudiantes que dieron su consentimiento.
3. **Derechos del estudiante.**
   - Consentimiento sin *dark patterns* (botones Aceptar/Rechazar simétricos, nada pre-marcado).
   - Recibo de consentimiento con el estándar Kantara.
   - Revocación ARCO en un clic.
   - Explicaciones accionables de su nivel de riesgo, en cumplimiento del Art. 23 de la Ley 29733.

Los datos provienen del dataset público **OULAD** (Open University Learning Analytics Dataset). Los nombres, DNI y correos son sintéticos (Faker).

## Cómo iniciar el proyecto

Requisitos: Python 3.10 o superior.

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Descomprimir los CSV de OULAD en data/raw/
#    (data/raw/Dataset_ética_final.zip)

# 3. Construir la base de datos (oulad_analitico + tablas de consentimiento y auditoría)
python db/build_oulad_db.py

# 4. Poblar identidades sintéticas y recibos de consentimiento
python db/enrich_db.py

# 5. (Opcional) Abrir los notebooks de notebooks/ con Jupyter o VS Code

# 6. Levantar el backend (terminal 1, desde la raíz)
uvicorn backend.main:app --reload

# 7. Levantar el frontend (terminal 2, desde la raíz)
streamlit run frontend/app.py
```

- **Backend:** la API queda en `http://127.0.0.1:8000` y la documentación interactiva en `/docs`.
- **Modelo:** el primer arranque entrena el modelo DP y lo guarda en `backend/artifacts/`; los siguientes lo cargan en segundos.
- **Informe web:** `python docs/web/build_site.py` genera `_site/` a partir de `docs/informe_final.md` (requiere `markdown-it-py` y `mdit-py-plugins`). Para verlo: `python -m http.server -d _site`. En GitHub se publica automáticamente con `.github/workflows/pages.yml`.
- **Modo pedagógico:** la variable `MODO_PEDAGOGICO=1` (por defecto) muestra los valores reales junto a los privatizados y habilita la demo del ataque. En producción debe ser `0`.

## Estructura de carpetas

```
├── backend/
│   ├── main.py          # API FastAPI: consultas DP, predicción, consentimiento, ARCO, auditoría
│   ├── dp_engine.py     # Mecanismo de Laplace, modelo DP y explicaciones contrafactuales
│   └── models.py        # Esquemas Pydantic
├── frontend/
│   └── app.py           # Interfaz Streamlit (3 pestañas, solo componentes nativos)
├── db/
│   ├── build_oulad_db.py   # ETL: CSV de OULAD -> tabla analítica de 60 días
│   ├── enrich_db.py        # Identidades sintéticas y recibos de consentimiento
│   └── oulad_proyecto.db   # SQLite (se genera, no se versiona)
├── notebooks/
│   ├── 01_auditoria_riesgo_klt.ipynb        # k-anonimato, l-diversidad, t-cercanía, ataque de enlace
│   ├── 02_experimentos_dp_y_equidad.ipynb   # Baseline, equidad, proxies, barrido de ε
│   └── 03_matriz_riesgos_dpia.ipynb         # Matriz de riesgos LINDDUN de la DPIA
├── data/
│   ├── raw/             # CSV originales de OULAD
│   └── processed/       # Parquet analítico
├── docs/
│   ├── figuras/         # Gráficas generadas por los notebooks
│   ├── web/             # Generador del sitio (build_site.py, plantilla, CSS, JS)
│   └── informe_final.md # Informe técnico-ético (DPIA, Datasheet, Model Card)
├── .github/workflows/pages.yml  # Publicación del informe en GitHub Pages
└── requirements.txt
```

## Tecnología usada

| Capa | Herramientas |
|---|---|
| Datos | SQLite, pandas, pyarrow |
| Privacidad | `diffprivlib` (IBM): mecanismo de Laplace y regresión logística DP |
| Equidad | `fairlearn`, scikit-learn |
| Backend | FastAPI, Pydantic v2, Uvicorn |
| Frontend | Streamlit (sin CSS/HTML personalizado) |
| Análisis | Jupyter, matplotlib |
| Datos sintéticos | Faker |

## Metodología

1. **Preparación de datos.**
   - Se construye una tabla con la información disponible a los 60 días: notas, entregas, retrasos, clics y días activos en el aula virtual.
   - Se añaden identidades sintéticas.
   - Se añaden consentimientos con dos bases legales:
     - Alerta temprana: relación contractual (Art. 14, Ley 29733).
     - Investigación externa: consentimiento expreso.
2. **Auditoría de riesgo** (notebook 01).
   - Clasificación de atributos.
   - Medición de k-anonimato, l-diversidad y t-cercanía.
   - Simulación de un ataque de enlace.
   - Prueba de que generalizar hasta k ≥ 5 destruye el análisis de desigualdad, lo que justifica el uso de ε-DP.
3. **Experimentos de privacidad y equidad** (notebook 02).
   - Modelo baseline y métricas de equidad por discapacidad y nivel socioeconómico: Disparate Impact, TPR, FPR y calibración.
   - Prueba de fuga por variables proxy.
   - Barrido de ε ∈ {0.1, …, 10} con 10 repeticiones por valor.
   - Selección de ε con criterios fijados de antemano: ε = 5 para el modelo y ε = 0.5 para las consultas.
4. **Aplicación.**
   - Integra los resultados en una demo con contador del presupuesto de privacidad (máximo 10 ε por periodo).
   - Registra cada consulta en los logs de auditoría.
   - Incluye consentimiento ético, derechos ARCO y explicaciones contrafactuales.
5. **Documentación.**
   - Evaluación de Impacto en la Protección de Datos (DPIA) según la Ley 29733 y el DS 016-2024-JUS.
   - Datasheet del dataset y Model Card del modelo.
   - Reflexión ética sobre sesgo, transparencia y consentimiento.
