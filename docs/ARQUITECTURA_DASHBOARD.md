# Arquitectura del Dashboard (Etapa 5)

> Diseño original de la Iteración 5.1, actualizado en la Iteración 5.2 con
> la estructura de módulos realmente implementada (ver "Nota de
> implementación" más abajo). El Dashboard tiene su estructura base
> funcionando, pero **todavía no está completo**: las páginas son
> esqueletos mínimos (ver `docs/ALCANCE_ETAPA_5.md`).

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

## Estructura de módulos (implementada en la Iteración 5.2)

```
src/dashboard/
├── __init__.py
├── app.py                  # Punto de entrada: streamlit run src/dashboard/app.py
├── config.py                 # DashboardConfig + build_dashboard_config()
├── models.py                   # TableStatus, DashboardStatus, Latest*Snapshot, DashboardSummary
├── repository.py                 # DashboardRepository (interfaz) + SQLiteDashboardRepository
├── service.py                      # DashboardService
├── filters.py                        # normalize_symbol/normalize_exchange/validate_limit
├── formatters.py                       # format_price/format_percent/format_timestamp/format_enum
├── charts.py                             # empty_figure/line_chart (mínimos; completos en 5.3)
├── components.py                           # render_not_available/render_kpi_card
└── pages/                                    # Una página por vista (esqueletos en 5.2)
    ├── __init__.py
    ├── resumen.py
    ├── mercado.py
    ├── indicadores.py
    ├── senales.py
    ├── recomendaciones.py
    └── estado_tecnico.py
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
> lectura de `config.yaml`. En la Iteración 5.2 las 6 páginas son
> esqueletos mínimos (título + un dato simple + manejo de ausencia de
> datos); el contenido completo de cada una es la Iteración 5.3.

1. **Resumen General** (`resumen.py`): en 5.3, una tarjeta KPI por símbolo
   configurado (precio actual, variación 24h, `signal_type` más reciente,
   `recommendation` de IA más reciente con su `confidence`). En 5.2, solo
   lista los símbolos configurados.
2. **Precios** (`mercado.py`): en 5.3, gráfico de precio histórico
   (`market_data`) superpuesto con SMA/EMA. En 5.2, solo el último precio.
3. **Indicadores** (`indicadores.py`): en 5.3, gráficos de RSI, MACD y
   Bandas de Bollinger (`market_indicators`). En 5.2, solo el RSI más
   reciente.
4. **Señales** (`senales.py`): en 5.3, historial de
   `score`/`confidence`/`signal_type` en el tiempo, y el detalle completo
   de la señal más reciente (`trend`/`ema_signal`/`macd_signal`/
   `rsi_signal`/`bollinger_signal` con su `reason` y `rule_strength`
   individuales). En 5.2, solo `signal_type`/`score` más recientes.
5. **Recomendaciones de IA** (`recomendaciones.py`): en 5.3, historial de
   `recommendation`/`confidence`/`risk_level` en el tiempo, y el detalle
   completo de la recomendación más reciente (`reasoning`, `advantages`,
   `risks`, `summary`, `provider`/`model`/`prompt_version`,
   `processing_time_ms`). En 5.2, solo `recommendation`/`confidence` más
   recientes.
6. **Estado Técnico** (`estado_tecnico.py`): estado de las 4 tablas SQLite
   (existe, cuántas filas, registro más reciente). Ya queda completamente
   funcional desde la Iteración 5.2, porque no depende de gráficos ni de
   un símbolo específico.

## Componentes reutilizables

- **Tarjeta KPI**: valor principal + variación/estado, usada en Resumen
  General y en la cabecera de las demás páginas.
- **Gráfico de serie temporal**: envoltura común para precio/indicadores/
  score/confidence a lo largo del tiempo (misma función, distintos datos).
- **Bloque de razones**: lista de `reason`/`rule_strength` o
  `advantages`/`risks`, reutilizado en Señales y Recomendaciones de IA.

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

## Dependencias que se agregarán en la Iteración 5.2 (no en esta)

`streamlit` y, si se decide usar una librería de gráficos más rica que la
nativa de Streamlit, `plotly` (ambas Python puro, sin servicios
adicionales). Ninguna se agrega a `requirements.txt` todavía.
