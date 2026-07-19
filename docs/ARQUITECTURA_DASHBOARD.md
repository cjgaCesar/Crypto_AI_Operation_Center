# Arquitectura del Dashboard (Etapa 5)

> Diseño original de la Iteración 5.1, actualizado en la Iteración 5.2 con
> la estructura de módulos realmente implementada, y en la Iteración 5.3
> con la primera página funcional (ver "Nota de implementación" e
> "Iteración 5.3" más abajo). La página "Resumen General" ya es funcional;
> el resto del Dashboard **todavía no está completo**: las demás páginas
> siguen siendo esqueletos mínimos (ver `docs/ALCANCE_ETAPA_5.md`).

## Nota de implementación (Iteración 5.2)

El diseño original de la Iteración 5.1 proponía una única capa de
consulta (`data_access.py`). Al implementarla, se dividió en dos módulos
más pequeños y con responsabilidades más claras — sin cambiar el
principio de diseño (separar consulta de presentación), solo su
granularidad:

- **`repository.py`**: `DashboardRepository` (interfaz) +
  `SQLiteDashboardRepository`. Reemplaza a `data_access.py`: es la única
  pieza que abre conexiones SQLite (reutilizando los 4 repositorios
  existentes para `fetch_latest`/`fetch_history`, y una conexión propia
  en modo solo lectura para los 2 métodos que no tienen equivalente:
  `get_available_symbols()`, `get_table_status()`).
- **`service.py`**: `DashboardService`. No estaba en el diseño original
  como un módulo separado; se agregó para que las páginas no llamen
  directamente al repositorio, sino a una capa que arma los modelos de
  presentación (`models.py`) y resuelve normalización/límites
  (`filters.py`). Esto deja `repository.py` enfocado solo en SQL.
- **`models.py`**, **`config.py`**, **`filters.py`**, **`formatters.py`**:
  no estaban explícitos en el diseño de la Iteración 5.1; se agregaron
  porque el principio "no contener diccionarios sin tipar como contrato
  principal" y "validar límites/normalizar símbolos" necesitaban un lugar
  propio, en vez de mezclarse dentro de `data_access.py` o de las páginas.

El principio de fondo (consulta separada de presentación, migrable a una
futura API sin reescribirse) **no cambió**: sigue siendo válido reemplazar
"`data_access.py`" por "`repository.py` + `service.py`" en el diagrama de
abajo.

## Nota de implementación (Iteración 5.3)

Se agregaron 2 piezas nuevas, sin romper el principio de diseño:

- **`DashboardSummaryView`** (`models.py`): vista aplanada de
  `DashboardSummary` para la página "Resumen General". `DashboardSummary`
  anida los 4 modelos completos (`summary.signal.signal.score`);
  `DashboardSummaryView` expone directamente los campos puntuales que una
  tarjeta necesita (`price`, `signal_type`, `signal_score`,
  `ai_recommendation`, etc.), reutilizando los mismos Enums de dominio
  (`SignalType`, `ConfidenceLevel`, `RecommendationAction`, `RiskLevel`)
  sin duplicarlos, más 4 banderas `has_*_data` y un
  `latest_update_timestamp` (el máximo entre los timestamps de mercado,
  indicadores, señal e IA — `None` si ninguno existe todavía).
- **`DashboardService.get_summary_view()`**: reutiliza `get_summary()` tal
  cual (mismas llamadas al repositorio, ninguna adicional) y solo
  transforma cada `DashboardSummary` ya obtenido en un
  `DashboardSummaryView`, sin volver a consultar nada.
- **`theme.py`** (nuevo): centraliza la paleta de colores del Dashboard
  (fondo, panel, borde, texto, positivo/negativo/advertencia/información/
  acento/IA/neutral) y 3 funciones puras (`get_signal_color`,
  `get_risk_color`, `get_change_color`) que devuelven siempre un color
  válido (`COLOR_NEUTRAL` para valores desconocidos o `None`, nunca una
  excepción). Ninguna función de `formatters.py` asigna color: eso vive
  exclusivamente en `theme.py`, a propósito, para no mezclar formato de
  texto con presentación visual.
- **`components.py`** ganó 4 helpers nuevos: `render_section_header`,
  `render_status_badge` (insignia con color de fondo, usada para señal/
  riesgo/recomendación de IA/variación 24h), `render_data_availability`
  (fila ✅/❌ de las 4 tablas) y `render_summary_card` (la tarjeta completa
  de un símbolo, combinando todo lo anterior).
- **`formatters.py`** ganó 5 funciones nuevas: `format_price_compact`,
  `format_confidence`, `format_score`, `format_risk_level` y
  `format_relative_status` (esta última acepta un `reference` explícito,
  para que las pruebas sean deterministas sin depender del reloj real).

### Revisión: `render_status_badge()` sin HTML

La primera versión de `render_status_badge()` usaba un `<span>` con
`unsafe_allow_html=True`. Se revisó y se reemplazó por la sintaxis nativa
de markdown de Streamlit para texto coloreado
(`:color[texto]`/`:color-background[texto]`, disponible desde ~1.31, ya
presente en la versión instalada), eliminando el HTML por completo:
`theme.to_streamlit_color_name()` traduce cada color hex de la paleta a
uno de los 7 nombres nativos que Streamlit reconoce (`blue`, `green`,
`orange`, `red`, `violet`, `gray`, `rainbow`), con `"gray"` como
respaldo para cualquier color no reconocido. Además, `render_status_badge()`
se protege a sí misma (no solo confía en que quien la llama ya validó
todo): un `label` `None`/vacío se muestra como `"N/D"`
(`formatters.NOT_AVAILABLE`), y los corchetes `[`/`]` se escapan para no
romper la sintaxis de markdown si algún valor llegara a contenerlos.

### Diseño responsive (layout.py)

Streamlit no expone el ancho real del viewport del navegador (no hay
breakpoints dinámicos nativos), y este proyecto explícitamente no agrega
detección de viewport vía JavaScript ni paquetes de terceros para
lograrlo. La estrategia adoptada es un selector manual en la barra
lateral de "Resumen General" (`Vista: Automática/Amplia/Compacta`),
guardado únicamente en `st.session_state` (nunca en disco ni en
`config.yaml`):

- **`src/dashboard/layout.py`** (nuevo): `get_cards_per_row(view_mode)`
  (Amplia=3, Automática=2, Compacta=1, cualquier valor desconocido cae en
  Automática — nunca 0, nunca más de 3), `is_compact(view_mode)`,
  `render_responsive_grid()` (distribuye tarjetas en filas de N columnas,
  o de corrido si N<=1) y `render_responsive_metric_group()` (columnas o
  apilado según el modo).
- **`render_summary_card(view, compact=False)`** se refactorizó en 4
  secciones internas (`_render_market_section`,
  `_render_signal_section`, `_render_ai_section`,
  `_render_update_section`), cada una con una rama columnas/apilado — el
  contenido mostrado es exactamente el mismo en ambos modos, solo cambia
  cómo se agrupa visualmente. Las insignias prioritarias (señal,
  recomendación de IA, riesgo) siempre ocupan su propia línea completa;
  las métricas secundarias (score, confianzas) se agrupan con
  `render_responsive_metric_group()`.
- Ninguna tarjeta usa ancho/alto fijo, posiciones absolutas ni CSS con
  coordenadas: solo `st.container(border=True)`, `st.columns()` y
  `st.metric()`, que ya se adaptan al ancho disponible.

## Tecnología seleccionada: Streamlit

| Opción | Evaluación |
|---|---|
| **Streamlit** (elegida) | Python puro de punta a punta; un solo proceso (servidor + UI); soporte nativo de multipágina; leer SQLite en modo solo lectura es directo. La opción con menor fricción para un dashboard personal, cumpliendo todas las restricciones dadas. |
| Dash | También Python, pero requiere más código repetitivo (layout declarativo + callbacks explícitos por cada interacción) para el mismo resultado. Más adecuado si se necesitara personalización visual fina, no es el caso aquí. |
| FastAPI | Es un framework de **backend/API**, no de interfaz visual. Usarlo solo entrega endpoints JSON; se necesitaría además un frontend separado (React, HTML+JS), justo lo que la restricción "no debe requerir un backend adicional" pide evitar. Queda como posible capa futura (ver "Migración futura"), no como base de esta etapa. |

## Principio de diseño: separar consulta de presentación

Igual que el resto del proyecto separa interfaces de implementaciones
(`ExchangeClient`, `*Repository`), el Dashboard separa **qué datos se
necesitan** de **cómo se muestran**, para poder migrar a una API en el
futuro sin reescribir la lógica de consulta:

```
SQLite (4 repositorios ya existentes, solo lectura)
    ↓
Repository    src/dashboard/repository.py   (DashboardRepository / SQLiteDashboardRepository)
    ↓
Service       src/dashboard/service.py        (DashboardService: arma modelos de presentación)
    ↓
View Model    src/dashboard/models.py           (DashboardSummary, DashboardSummaryView, ...)
    ↓
Components    src/dashboard/components.py         (render_summary_card, render_status_badge, ...)
    ↓
Page          src/dashboard/pages/*.py               (una página Streamlit por vista)
    ↓
Streamlit (renderiza en el navegador)
```

- **`repository.py`** es la única pieza que sabe instanciar
  `SQLiteMarketDataRepository`, `SQLiteIndicatorRepository`,
  `SQLiteSignalRepository` y `SQLiteAIRepository`, y solo llama a sus
  métodos `fetch_latest`/`fetch_history` (nunca `save()`).
- **`service.py`** llama a `repository.py` y arma los **modelos de
  vista** de `models.py` (ej. `DashboardSummary`, `DashboardSummaryView`);
  no sabe nada de Streamlit.
- **`models.py`** (View Model) son Pydantic puros: sin lógica visual, sin
  SQL, sin conexión a Streamlit.
- **`components.py`** consume los modelos de vista y los dibuja
  (`render_summary_card`, `render_status_badge`, etc.); es la única capa,
  junto con `layout.py`, que depende de Streamlit además de las páginas.
- **Las páginas** (`src/dashboard/pages/`) llaman a `service.py` para
  obtener datos y a `components.py`/`layout.py` para dibujarlos. No abren
  conexiones a SQLite directamente ni ejecutan SQL.
- **Migración futura a FastAPI**: si se decide exponer una API, sus
  endpoints llamarían a las mismas funciones de `service.py` que hoy usa
  Streamlit. Ni los repositorios ni `repository.py`/`service.py`/
  `models.py` cambiarían — solo `components.py`/`layout.py` (capa 100%
  de presentación) dejarían de usarse en ese contexto.

## Estructura de módulos (base en la Iteración 5.2, ampliada en la 5.3)

```
src/dashboard/
├── __init__.py
├── app.py                  # Punto de entrada: streamlit run src/dashboard/app.py
├── config.py                 # DashboardConfig + build_dashboard_config()
├── models.py                   # TableStatus, DashboardStatus, Latest*Snapshot,
│                                # DashboardSummary, DashboardSummaryView (5.3)
├── repository.py                 # DashboardRepository (interfaz) + SQLiteDashboardRepository
├── service.py                      # DashboardService (+ get_summary_view(), 5.3)
├── filters.py                        # normalize_symbol/normalize_exchange/validate_limit
├── formatters.py                       # format_price/percent/timestamp/enum +
│                                        # format_price_compact/confidence/score/
│                                        # risk_level/relative_status (5.3)
├── theme.py                              # Paleta + get_signal_color/get_risk_color/
│                                         # get_change_color/to_streamlit_color_name (5.3)
├── layout.py                              # get_cards_per_row/is_compact/render_responsive_grid/
│                                          # render_responsive_metric_group (responsive, 5.3)
├── charts.py                             # empty_figure/line_chart (mínimos; gráficos
│                                         # históricos completos en una iteración futura)
├── components.py                           # render_not_available/render_kpi_card +
│                                           # render_section_header/render_status_badge (sin HTML)/
│                                           # render_data_availability/render_summary_card
│                                           # (con modo compact, 5.3)
└── pages/                                    # Una página por vista
    ├── __init__.py
    ├── resumen.py                             # Funcional desde 5.3 (tarjetas por símbolo)
    ├── mercado.py                             # Esqueleto
    ├── indicadores.py                         # Esqueleto
    ├── senales.py                             # Esqueleto
    ├── recomendaciones.py                     # Esqueleto
    └── estado_tecnico.py                      # Funcional desde 5.2
```

No se usa la convención automática de nombres numerados de páginas de
Streamlit (`1_...py`, `2_...py`): la navegación queda centralizada en
`app.py` (una barra lateral con `st.sidebar.radio`), a propósito, para
tener control total sobre qué se le pasa a cada página (servicio, símbolo,
límite) sin depender de cómo Streamlit auto-descubre archivos.

## Páginas

> Nota de implementación: la página "Precios e Indicadores" del diseño
> original se dividió en dos páginas separadas (`mercado.py` /
> `indicadores.py`), y "Configuración" se reemplazó por "Estado Técnico"
> (`estado_tecnico.py`), que resultó más útil para diagnosticar el estado
> de las 4 tablas SQLite (existe/vacía/con datos) que una vista de solo
> lectura de `config.yaml`. En la Iteración 5.2 las 6 páginas eran
> esqueletos mínimos (título + un dato simple + manejo de ausencia de
> datos). En la Iteración 5.3, "Resumen General" se completó; las otras 4
> páginas de símbolo (Precios/Indicadores/Señales/Recomendaciones) siguen
> como esqueletos, pendientes de una iteración futura.

1. **Resumen General** (`resumen.py`) — **funcional desde la Iteración
   5.3**: una tarjeta por símbolo configurado (`DashboardService.get_summary_view()`)
   con precio, variación 24h, señal más reciente (`signal_type`, `score`,
   `confidence`), recomendación de IA (`recommendation`, `confidence`,
   `risk_level`), última actualización relativa y disponibilidad de datos
   (mercado/indicadores/señales/IA), además de un resumen general (símbolos
   configurados, símbolos con datos completos, última actualización del
   sistema), 4 estados vacíos distintos (base inexistente, sin precios,
   precios sin señales, señales sin IA), y un selector de vista responsive
   (`Vista: Automática/Amplia/Compacta`, ver "Diseño responsive" más
   arriba) que controla cuántas tarjetas se muestran por fila.
2. **Precios** (`mercado.py`) — esqueleto: hoy solo el último precio. En
   una iteración futura, gráfico de precio histórico (`market_data`)
   superpuesto con SMA/EMA.
3. **Indicadores** (`indicadores.py`) — esqueleto: hoy solo el RSI más
   reciente. En una iteración futura, gráficos de RSI, MACD y Bandas de
   Bollinger (`market_indicators`).
4. **Señales** (`senales.py`) — esqueleto: hoy solo `signal_type`/`score`
   más recientes. En una iteración futura, historial de
   `score`/`confidence`/`signal_type` en el tiempo, y el detalle completo
   de la señal más reciente (`trend`/`ema_signal`/`macd_signal`/
   `rsi_signal`/`bollinger_signal` con su `reason` y `rule_strength`
   individuales).
5. **Recomendaciones de IA** (`recomendaciones.py`) — esqueleto: hoy solo
   `recommendation`/`confidence` más recientes. En una iteración futura,
   historial de `recommendation`/`confidence`/`risk_level` en el tiempo, y
   el detalle completo de la recomendación más reciente (`reasoning`,
   `advantages`, `risks`, `summary`, `provider`/`model`/`prompt_version`,
   `processing_time_ms`).
6. **Estado Técnico** (`estado_tecnico.py`): estado de las 4 tablas SQLite
   (existe, cuántas filas, registro más reciente). Ya queda completamente
   funcional desde la Iteración 5.2, porque no depende de gráficos ni de
   un símbolo específico.

## Componentes reutilizables

- **`render_kpi_card`**: valor principal + etiqueta (envuelve `st.metric`).
- **`render_status_badge`** (5.3, sin HTML desde la revisión del Bloque
  C): insignia de una línea con color de fondo, vía la sintaxis nativa de
  markdown de Streamlit (señal, riesgo, recomendación de IA, variación
  24h). Con protección propia: `label` vacío/`None` -> `"N/D"`, color no
  reconocido -> gris.
- **`render_data_availability`** (5.3): fila ✅/❌ de las 4 tablas
  (mercado/indicadores/señales/IA) para un símbolo.
- **`render_section_header`** (5.3): encabezado de sección reutilizable.
- **`render_summary_card(view, compact=False)`** (5.3): la tarjeta
  completa de un símbolo en "Resumen General", combinando los componentes
  anteriores en 4 secciones internas (mercado/señal/IA/actualización), con
  layout en columnas o apilado según `compact`.
- **`layout.render_responsive_grid`/`render_responsive_metric_group`**
  (5.3): distribución de tarjetas y grupos de métricas según el modo de
  vista elegido (ver "Diseño responsive" más arriba).
- **Gráfico de serie temporal** (`charts.line_chart`): envoltura común
  para precio/indicadores/score/confidence a lo largo del tiempo —
  todavía sin usar en ninguna página (pendiente de una iteración futura).
- **Bloque de razones**: lista de `reason`/`rule_strength` o
  `advantages`/`risks` — pendiente de una iteración futura (Señales y
  Recomendaciones de IA todavía son esqueletos).

## Filtros globales

- **Símbolo**: selector con los símbolos de `settings.symbols`
  (`BTCUSDT`/`ETHUSDT`/`SOLUSDT` hoy), aplicado a todas las páginas salvo
  Resumen General (que siempre muestra los 3).
- **Exchange**: fijo en "Binance" hoy (único exchange implementado);
  reservado como filtro para cuando exista más de uno.
- **Límite de historial**: cuántos registros recientes mostrar en
  gráficos e historiales (ej. últimos 50/100/200), reutilizando
  `fetch_history(limit=...)` ya existente en los 4 repositorios.
- **Auto-actualización**: intervalo opcional de refresco automático de la
  página (ej. cada 30s), para reflejar nuevos ciclos del bot sin recargar
  manualmente.

## Regla para tablas y gráficos futuros (Precios/Indicadores/Señales/Recomendaciones)

Cuando se implementen los gráficos históricos e indicadores de esas 4
páginas (todavía esqueletos), seguir esta regla para que sean responsive
desde el primer commit, sin tener que revisarlos después:

- Usar `st.dataframe(..., use_container_width=True)` para cualquier
  tabla; evitar tablas estáticas en markdown.
- Usar gráficos Plotly con `use_container_width=True`; evitar tamaños
  fijos en píxeles.
- Limitar columnas visibles en pantallas angostas; ofrecer detalle
  expandible (`st.expander`) cuando haya demasiada información para
  mostrar de una vez.

## Qué NO hace el Dashboard

- No escribe en ninguna tabla.
- No recalcula indicadores, señales ni recomendaciones.
- No conecta con Binance ni con ningún proveedor de IA directamente: solo
  lee lo que `src/main.py` ya guardó en ciclos anteriores.
- No requiere ningún cambio en `src/market/`, `src/database/`,
  `src/services/`, `src/signals/`, `src/ai/` ni `src/utils/`: los 4
  repositorios ya exponen exactamente los métodos de lectura
  (`fetch_latest`/`fetch_history`) que el Dashboard necesita.

## Dependencias

`streamlit` y `plotly` (ambas Python puro, sin servicios adicionales),
agregadas a `requirements.txt` desde la Iteración 5.2. La Iteración 5.3 no
agregó ninguna dependencia nueva.

## Estado por iteración

- **5.1** (diseño): alcance y arquitectura documentados, sin código.
- **5.2** (estructura base): repositorio/servicio/config/helpers/`app.py`
  funcionando, 6 páginas esqueleto.
- **5.3** (esta): página "Resumen General" funcional
  (`DashboardSummaryView`, `get_summary_view()`, `theme.py`,
  `layout.py`/diseño responsive, tarjetas de resumen sin HTML). Las otras
  4 páginas de símbolo siguen siendo esqueletos.
- **Pendiente para la Iteración 5.4**: gráficos históricos completos
  (Precios/Indicadores/Señales/Recomendaciones), auto-refresh real,
  comparación entre símbolos, diseño visual definitivo de toda la
  aplicación (identidad visual más allá de la paleta ya centralizada en
  `theme.py`).
