# Arquitectura del Dashboard (Etapa 5)

> Diseño de la Iteración 5.1. No hay código todavía: este documento es la
> base para la implementación de la Iteración 5.2, pendiente de
> aprobación.

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
src/dashboard/data_access.py   (capa de consulta, reutiliza los repos)
    ↓
src/dashboard/pages/*.py       (una página Streamlit por vista)
    ↓
Streamlit (renderiza en el navegador)
```

- **`data_access.py`** es la única pieza que sabe instanciar
  `SQLiteMarketDataRepository`, `SQLiteIndicatorRepository`,
  `SQLiteSignalRepository` y `SQLiteAIRepository`, y solo llama a sus
  métodos `fetch_latest`/`fetch_history` (nunca `save()`). Expone
  funciones simples (ej. `get_latest_signal(symbol)`,
  `get_price_history(symbol, limit)`) que no saben nada de Streamlit.
- **Las páginas** (`src/dashboard/pages/`) solo llaman a `data_access.py`
  y renderizan el resultado (tablas, gráficos, tarjetas KPI). No abren
  conexiones a SQLite directamente.
- **Migración futura a FastAPI**: si se decide exponer una API, sus
  endpoints llamarían a las mismas funciones de `data_access.py` que hoy
  usa Streamlit. Ni los repositorios ni la capa de consulta cambiarían.

## Estructura de módulos propuesta (a crear en la Iteración 5.2)

```
src/dashboard/
├── __init__.py           # (ya existe, reservado)
├── app.py                  # Punto de entrada: streamlit run src/dashboard/app.py
├── data_access.py            # Capa de consulta de solo lectura (reutiliza los 4 repos)
├── components.py                # Helpers de presentación reutilizables (tarjeta KPI, gráfico de líneas)
└── pages/                          # Una página por vista (convención multipágina de Streamlit)
    ├── 1_Resumen_General.py
    ├── 2_Precios_e_Indicadores.py
    ├── 3_Senales.py
    ├── 4_Recomendaciones_IA.py
    └── 5_Configuracion.py
```

Nada de esto se crea todavía en esta iteración (ver
`docs/ALCANCE_ETAPA_5.md`, "Explícitamente fuera de la Iteración 5.1").

## Páginas

1. **Resumen General**: una tarjeta KPI por símbolo configurado (precio
   actual, variación 24h, `signal_type` más reciente, `recommendation` de
   IA más reciente con su `confidence`). Vista de "un vistazo" a los 3
   símbolos a la vez.
2. **Precios e Indicadores**: para el símbolo seleccionado (filtro
   global), gráfico de precio histórico (`market_data`) superpuesto con
   SMA/EMA, y gráficos separados para RSI, MACD y Bollinger
   (`market_indicators`).
3. **Señales**: historial de `score`/`confidence`/`signal_type`
   (`market_signals`) en el tiempo, y el detalle completo de la señal más
   reciente: `trend`/`ema_signal`/`macd_signal`/`rsi_signal`/`bollinger_signal`
   con su `reason` y `rule_strength` individuales.
4. **Recomendaciones de IA**: historial de `recommendation`/`confidence`/
   `risk_level` (`ai_recommendations`) en el tiempo, y el detalle completo
   de la recomendación más reciente: `reasoning`, `advantages`, `risks`,
   `summary`, `provider`/`model`/`prompt_version`, `processing_time_ms`.
5. **Configuración**: vista de solo lectura de los valores relevantes de
   `config.yaml` (símbolos, intervalo, umbrales de `signals`/`ai`), para
   transparencia sobre qué configuración generó los datos que se están
   viendo. No permite editar nada.

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
