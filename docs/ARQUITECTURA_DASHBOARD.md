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
src/dashboard/repository.py   (DashboardRepository / SQLiteDashboardRepository)
    ↓
src/dashboard/service.py        (DashboardService: arma modelos de presentación)
    ↓
src/dashboard/pages/*.py          (una página Streamlit por vista)
    ↓
Streamlit (renderiza en el navegador)
```

- **`repository.py`** es la única pieza que sabe instanciar
  `SQLiteMarketDataRepository`, `SQLiteIndicatorRepository`,
  `SQLiteSignalRepository` y `SQLiteAIRepository`, y solo llama a sus
  métodos `fetch_latest`/`fetch_history` (nunca `save()`).
- **`service.py`** llama a `repository.py` y arma los modelos de
  `models.py` (ej. `DashboardSummary`); no sabe nada de Streamlit.
- **Las páginas** (`src/dashboard/pages/`) solo llaman a `service.py` y
  renderizan el resultado. No abren conexiones a SQLite directamente.
- **Migración futura a FastAPI**: si se decide exponer una API, sus
  endpoints llamarían a las mismas funciones de `service.py` que hoy usa
  Streamlit. Ni los repositorios ni `repository.py`/`service.py`
  cambiarían.

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
│                                         # get_change_color (nuevo, 5.3)
├── charts.py                             # empty_figure/line_chart (mínimos; gráficos
│                                         # históricos completos en una iteración futura)
├── components.py                           # render_not_available/render_kpi_card +
│                                           # render_section_header/render_status_badge/
│                                           # render_data_availability/render_summary_card (5.3)
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
   sistema) y 4 estados vacíos distintos (base inexistente, sin precios,
   precios sin señales, señales sin IA).
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
- **`render_status_badge`** (5.3): insignia de una línea con color de
  fondo controlado por `theme.py` (señal, riesgo, recomendación de IA,
  variación 24h).
- **`render_data_availability`** (5.3): fila ✅/❌ de las 4 tablas
  (mercado/indicadores/señales/IA) para un símbolo.
- **`render_section_header`** (5.3): encabezado de sección reutilizable.
- **`render_summary_card`** (5.3): la tarjeta completa de un símbolo en
  "Resumen General", combinando los 4 componentes anteriores.
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
  (`DashboardSummaryView`, `get_summary_view()`, `theme.py`, tarjetas de
  resumen). Las otras 4 páginas de símbolo siguen siendo esqueletos.
- **Pendiente**: gráficos históricos completos, auto-refresh real,
  comparación entre símbolos, diseño visual definitivo de toda la
  aplicación.
