# Arquitectura del Dashboard (Etapa 5)

> Diseño original de la Iteración 5.1, actualizado en la Iteración 5.2 con
> la estructura de módulos realmente implementada, en la Iteración 5.3 con
> la primera página funcional, en la Iteración 5.4 con la página
> "Mercado", en la Iteración 5.5 con la página "Indicadores", en la
> Iteración 5.6 con la página "Señales" y en la Iteración 5.7 con la
> página "Recomendaciones de IA" (ver "Nota de implementación" de cada
> iteración más abajo). Las 6 páginas del Dashboard ya son funcionales:
> "Resumen General", "Mercado", "Indicadores", "Señales", "Recomendaciones
> de IA" y "Estado Técnico". La Etapa 5 **todavía no está cerrada**: falta
> el refinamiento visual definitivo, validación visual real en navegador,
> y la aprobación formal de esta iteración (ver
> `docs/ALCANCE_ETAPA_5.md`).

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
lateral (`Vista: Automática/Amplia/Compacta`), presente en "Resumen
General" (desde la 5.3) y en "Mercado" (desde la 5.4), guardado
únicamente en `st.session_state` (nunca en disco ni en `config.yaml`).

**El modo de vista responsive es compartido entre las páginas del
Dashboard mediante una única clave centralizada de st.session_state**
(`layout.VIEW_MODE_SESSION_KEY`): elegir "Compacta" en una página y
navegar a la otra conserva "Compacta", en vez de que cada página
mantenga su propio modo por separado (lo que habría sido una
experiencia inconsistente y no documentada). Esto se descubrió y
corrigió al cerrar la Iteración 5.4: hasta entonces, cada página usaba
su propia key (`resumen_view_mode` / `mercado_view_mode`).

El selector en sí se construye en un único lugar:
**`layout.render_view_mode_selector()`**. Ninguna página llama a
`st.sidebar.selectbox("Vista", ...)` por su cuenta — ambas ("Resumen
General" y "Mercado") llaman exclusivamente a esta función, que:
inicializa `st.session_state[VIEW_MODE_SESSION_KEY]` en `VIEW_MODE_AUTO`
solo si todavía no existe, corrige el valor a `VIEW_MODE_AUTO` si
contuviera algo fuera de `VIEW_MODES` (ej. tras un cambio de código), y
renderiza el `selectbox` sin pasar `index` (con la key ya inicializada,
Streamlit usa ese valor existente directamente). Que la construcción del
widget viva en un único lugar —no solo la key y el `help`— es lo que
evita que una página diverja de la otra en el futuro.

- **`src/dashboard/layout.py`** (nuevo): `get_cards_per_row(view_mode)`
  (Amplia=3, Automática=2, Compacta=1, cualquier valor desconocido cae en
  Automática — nunca 0, nunca más de 3), `is_compact(view_mode)`,
  `render_responsive_grid()` (distribuye tarjetas en filas de N columnas,
  o de corrido si N<=1), `render_responsive_metric_group()` (columnas o
  apilado según el modo) y `render_view_mode_selector()` (construcción
  única y compartida del selector "Vista", ver arriba).
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
- **Cero persistencia del modo de vista**: la selección vive solo en
  `st.session_state` durante la sesión del navegador; nunca se escribe a
  disco ni a `config.yaml`. Al recargar la página desde cero, vuelve a
  "Automática".
- **Cero detección de viewport mediante JavaScript**: no hay ningún
  `components.html`, `streamlit-js-eval` ni script de terceros que lea el
  ancho real de la ventana. El modo "Automática" es un valor conservador
  fijo (2 tarjetas por fila), no una detección real de pantalla.
- **Cero dependencias nuevas**: todo el diseño responsive se construyó
  con lo que ya provee Streamlit (`st.container`, `st.columns`,
  `st.metric`, sintaxis de markdown coloreado); no se agregó ningún
  paquete a `requirements.txt` para esto.
- **Hallazgo verificado sobre widgets con `key` compartida entre
  páginas**: compartir la misma `key` de `st.session_state` no basta por
  sí solo. Streamlit solo conserva el valor guardado si el resto de los
  argumentos de construcción del widget (en particular `help`) también
  coinciden entre una página y otra; si difieren, trata la instancia
  como un widget distinto y resetea al `index` por defecto (comportamiento
  reproducido de forma aislada y confirmado con pruebas automatizadas en
  `tests/test_dashboard_navigation.py`). Por eso `VIEW_MODE_HELP_TEXT`
  (además de `VIEW_MODE_SESSION_KEY`) también vive centralizado en
  `layout.py`: ninguna página debe escribir su propio texto de ayuda para
  este selector.

### Reglas obligatorias de responsive (aplicadas a las 6 páginas; vigentes para cualquier página futura)

Estas reglas ya se aplicaron a las 6 páginas del Dashboard ("Mercado"
desde la 5.4, "Indicadores" desde la 5.5, "Señales" desde la 5.6,
"Recomendaciones de IA" desde la 5.7) y siguen vigentes para cualquier
página que se agregue en una etapa futura: deben ser **responsive desde
el inicio**, no revisarse después:

- Tablas con ancho del contenedor: `st.dataframe(..., use_container_width=True)`.
- Gráficos con ancho del contenedor: Plotly con `use_container_width=True`.
- Sin tamaños fijos en píxeles (ni ancho ni alto).
- **Sin scroll horizontal**: ninguna tabla, gráfico o bloque de texto debe
  forzarlo.
- Detalle expandible en móvil (`st.expander`) cuando haya demasiada
  información para mostrar de una vez, en vez de comprimir columnas hasta
  volverlas ilegibles.

## Nota de implementación (Iteración 5.4)

Se implementó la página "Mercado" (`mercado.py`, renombrada de "Precios" a
"Mercado" para que el título de la página, el nombre del módulo y la
tabla que consulta —`market_data`— usen el mismo nombre), reutilizando
todo lo que ya existía sin agregar ninguna dependencia nueva:

- **`repository.py` no ganó ningún método nuevo**: `get_market_history()`
  y `get_available_symbols()` (ambos ya existentes desde la Iteración
  5.2/5.3) ya eran suficientes para construir la página completa. Antes
  de escribir código se inspeccionó el esquema real de `market_data`
  (`PRAGMA table_info`) para confirmar los nombres de columna reales
  (`price`, `volume_24h`, `price_change_percent_24h`, `queried_at`; no
  existen columnas de máximo/mínimo separadas) y verificar que no hay
  filas nulas, duplicadas ni fuera de orden cronológico.
- **`DashboardService.get_market_page(exchange, symbol, limit)`**
  (`service.py`): una sola llamada a `get_market_history()` (no llama
  también a `get_latest_market()`: el último elemento del historial ya
  es el dato más reciente, evitando una consulta duplicada). A partir de
  esa misma lista construye el resumen (`_build_market_summary()`,
  método estático) y los puntos del gráfico. El máximo/mínimo del
  período y la variación frente al registro anterior son cálculos
  simples sobre filas ya existentes (no son indicadores técnicos: no se
  recalcula nada que ya viva en `market_indicators`).
- **`models.py`** ganó 3 modelos nuevos: `MarketSummaryView` (precio
  actual, precio anterior, variación absoluta/porcentual, máximo/mínimo
  del período, timestamp, cantidad de registros, volumen),
  `MarketHistoryPoint` (timestamp/precio/volumen de un punto del
  gráfico) y `MarketPageView` (símbolos configurados, símbolo elegido,
  resumen opcional, historial, disponibilidad y mensaje).
- **`formatters.py`** ganó 3 funciones: `format_price_change` (variación
  absoluta con signo, sin símbolo de porcentaje), `format_volume` y
  `format_record_count`. Ninguna asigna color (igual criterio que el
  resto del archivo).
- **`components.py`** ganó 3 helpers: `render_market_metrics()` (grupo de
  métricas responsive vía `layout.render_responsive_metric_group()`),
  `render_market_availability()` (última actualización + cantidad de
  registros) y `render_price_history_chart()` (envuelve
  `charts.line_chart()`, ya existente desde la Iteración 5.2, sin
  agregar ninguna librería nueva: sigue siendo Plotly).
- **Diseño responsive**: la página "Mercado" reutiliza exactamente el
  mismo selector "Vista" (Automática/Amplia/Compacta) que "Resumen
  General", guardado en su propia clave de `st.session_state`
  (`mercado_view_mode`) para no interferir con la de "Resumen General".
  El gráfico usa `use_container_width=True` (sin ancho fijo, sin scroll
  horizontal), y las métricas usan `render_responsive_metric_group()` ya
  existente. A diferencia de "Resumen General" (que muestra una tarjeta
  por símbolo y sí varía cuántas tarjetas caben por fila), "Mercado"
  muestra un único símbolo a la vez: `get_cards_per_row()` y
  `render_responsive_grid()` no aplican aquí porque no hay una colección
  de tarjetas que distribuir, solo un grupo de métricas y un gráfico.
- **Garantía de solo lectura sin cambios**: el selector de símbolo
  (compartido entre páginas) sigue viviendo en `app.py`; "Mercado" no
  abre conexiones ni ejecuta SQL directamente.
- **Manejo de ausencia de datos**: si `get_market_history()` devuelve una
  lista vacía (símbolo sin ningún precio guardado todavía), la página
  muestra un mensaje explícito en vez de un resumen vacío o un error.
  Con un único registro, `previous_price`/`absolute_change`/
  `percentage_change` quedan en `None` ("N/D"), pero el precio actual y
  el máximo/mínimo (iguales al único precio disponible) sí se muestran.
- **Cierre de la iteración**: al revisar el estado responsive compartido
  entre "Resumen General" y "Mercado" se encontró que cada página usaba
  su propia key de `st.session_state` (`resumen_view_mode` /
  `mercado_view_mode`), por lo que elegir un modo en una página no se
  conservaba al navegar a la otra. Un primer intento unificó solo
  `layout.VIEW_MODE_SESSION_KEY` (y, tras un segundo hallazgo, también
  `layout.VIEW_MODE_HELP_TEXT`, ver "Diseño responsive" más arriba), pero
  cada página seguía construyendo su propio `st.sidebar.selectbox(...)`
  por separado. La solución definitiva centralizó también la
  construcción del widget en `layout.render_view_mode_selector()`: ambas
  páginas la llaman exclusivamente, sin key/index/help propios.

## Nota de implementación (Iteración 5.5)

Se implementó la página "Indicadores" (`indicadores.py`), reutilizando
la infraestructura ya existente sin agregar ninguna dependencia nueva:

- **`repository.py` no ganó ningún método nuevo**: `get_indicator_history()`
  (ya existente desde la Iteración 5.2) fue suficiente para construir la
  página completa — mismo criterio que "Mercado" en la 5.4. Antes de
  escribir código se inspeccionó el esquema real de `market_indicators`
  (`PRAGMA table_info`): `id, exchange, symbol, sma, ema_fast,
  ema_medium, ema_slow, rsi, macd_line, macd_signal, macd_histogram,
  bollinger_upper, bollinger_middle, bollinger_lower, vwap,
  calculated_at`. No existen columnas de ATR, ADX ni volatilidad — el
  proyecto todavía no las calcula (ver README, "Todavía NO hace lo
  siguiente"). `ema_slow` está en `NULL` en el 100% de las 153 filas
  actuales (necesita 200 lecturas de historial, que todavía no existen).
- **`DashboardService.get_indicators_page(exchange, symbol, limit)`**
  (`service.py`): una sola llamada a `get_indicator_history()` (no llama
  también a `get_latest_indicators()`: el último elemento del historial
  ya es el snapshot más reciente), igual patrón que `get_market_page()`.
- **`models.py`** ganó 2 modelos nuevos: `IndicatorSummaryView` (los
  mismos ~12 campos de `IndicatorSnapshot`, aplanados, más `has_data`) e
  `IndicatorPageView` (símbolos configurados, símbolo elegido, resumen
  opcional, historial, disponibilidad y mensaje). El historial reutiliza
  `list[IndicatorSnapshot]` directamente en vez de un
  "IndicatorHistoryPoint" nuevo: a diferencia de "Mercado" (un punto de
  historial de precio son solo 3 campos), cada punto de historial de
  indicadores ya necesita los mismos ~12 campos que `IndicatorSnapshot`
  expone — duplicar ese modelo solo para el historial habría sido
  redundante, no una separación real.
- **`charts.py`** ganó `multi_line_chart(x, series, title)`: varias
  series superpuestas en una sola figura (una traza por clave de
  `series`), reutilizado para MACD (línea/señal/histograma) y medias
  móviles (SMA + EMA rápida/media/lenta). Sigue sin conocer Streamlit,
  SQLite ni los modelos del proyecto (recibe listas simples), igual
  criterio que `line_chart()`.
- **`components.py`** ganó 3 helpers: `render_indicator_metrics()`
  (RSI, MACD/Señal/Histograma, SMA, EMA rápida/media/lenta, Bandas de
  Bollinger, VWAP, vía `layout.render_responsive_metric_group()`),
  `render_indicator_availability()` (fecha del último cálculo) y
  `render_indicator_history_charts()` (3 gráficos: RSI, MACD, medias
  móviles).
- **ATR, ADX y Volatilidad**: no existen en `market_indicators` ni en
  `IndicatorSnapshot`, así que **no se agregaron como campos
  siempre-`None`** en `IndicatorSummaryView` (fingir que son parte del
  modelo de datos sería peor que omitirlos). En su lugar,
  `render_indicator_availability()` los declara explícitamente como
  "N/D" con una nota ("no calculados todavía en este proyecto"), para
  que quede claro que es una limitación real y conocida, no un olvido de
  esta página. Cualquier valor de indicador ausente en una fila puntual
  (ej. `ema_slow` con poco historial) también se muestra como "N/D" vía
  `formatters.format_price()`, nunca inventado ni recalculado.
- **Diseño responsive**: la página reutiliza exactamente
  `layout.render_view_mode_selector()` (misma key/help/comportamiento
  que "Resumen General" y "Mercado", ver más arriba) y
  `render_responsive_metric_group()`. Al igual que "Mercado",
  `get_cards_per_row()`/`render_responsive_grid()` no aplican aquí: la
  página muestra un único símbolo a la vez, no una colección de tarjetas
  por símbolo.
- **Garantía de solo lectura sin cambios**: `indicadores.py` no ejecuta
  SQL, no importa `sqlite3` ni el Repository directamente, y no
  recalcula ningún indicador — todo viene de
  `DashboardService.get_indicators_page()`.

## Nota de implementación (Iteración 5.6)

Se implementó la página "Señales" (`senales.py`), reutilizando la
infraestructura ya existente sin agregar ninguna dependencia nueva:

- **`repository.py` no ganó ningún método nuevo**: `get_signal_history()`
  (ya existente desde la Iteración 5.2) fue suficiente — mismo criterio
  que "Mercado"/"Indicadores". Antes de escribir código se inspeccionó el
  esquema real de `market_signals` (`PRAGMA table_info`): `id, exchange,
  symbol, trend, trend_strength, ema_signal, macd_signal, rsi_signal,
  bollinger_signal, trend_reason, ema_reason, macd_reason, rsi_reason,
  bollinger_reason, trend_rule_strength, ema_rule_strength,
  macd_rule_strength, rsi_rule_strength, bollinger_rule_strength, score,
  confidence, signal_type, generated_at`. A diferencia de
  `market_indicators`, **todas las columnas son `NOT NULL`** (153/153
  filas sin ningún nulo) y coinciden exactamente con `SignalSnapshot`
  (`src/models/signal_data.py`): no hay diferencia entre esquema y
  modelo de dominio. **No existe una columna `risk`**: el riesgo vive en
  `ai_recommendations` (página "Recomendaciones de IA", todavía no
  implementada), no en `market_signals` — no es un dato ausente de esta
  tabla, es un concepto de otra tabla/página.
- **`DashboardService.get_signals_page(exchange, symbol, limit)`**
  (`service.py`): una sola llamada a `get_signal_history()` (no llama
  también a `get_latest_signal()`), mismo patrón que
  `get_market_page()`/`get_indicators_page()`. No llama a `SignalEngine`
  ni recalcula ninguna señal.
- **`models.py`** ganó 2 modelos nuevos: `SignalSummaryView` (los mismos
  campos de veredicto de `SignalSnapshot` — `signal_type`, `score`,
  `confidence`, `trend`, `trend_strength`, y el veredicto de cada
  componente `ema_signal`/`macd_signal`/`rsi_signal`/`bollinger_signal`
  — aplanados, más `record_count`/`has_data`; sin `risk`, por lo ya
  explicado) e `SignalPageView` (símbolos, símbolo elegido, resumen
  opcional, historial, disponibilidad y mensaje). El historial reutiliza
  `list[SignalSnapshot]` directamente, mismo criterio que
  `IndicatorPageView`: cada punto ya necesita los mismos campos que
  `SignalSnapshot` expone (incluidas las 5 `*_reason` de texto) — un
  modelo "SignalHistoryPointView" habría sido una copia redundante.
- **`formatters.py`/`charts.py` no ganaron nada nuevo**: `format_score`,
  `format_enum` y `format_timestamp` (ya existentes) cubrían todo lo
  necesario; `charts.line_chart()` (ya existente) se reutilizó para el
  score.
- **`components.py`** ganó 5 helpers: `render_signal_status()` (insignia
  de color vía `theme.get_signal_color()`), `render_signal_metrics()`
  (score/confianza/tendencia/fuerza), `render_signal_explanation()`
  (veredicto de EMA/MACD/RSI/Bollinger), `render_signal_availability()`
  (fecha de generación + registros, con la nota explícita de que el
  riesgo no aplica aquí) y `render_signal_history_chart()`/
  `render_signal_history_table()`.
- **Gráfico vs. tabla — decisión explícita**: `signal_type`/`confidence`/
  `trend` son categóricos (ej. "Bullish"/"Very High"/"Strong Bullish");
  graficarlos como números arbitrarios en un eje sería engañoso (el
  proyecto lo prohíbe explícitamente). Por eso solo el **score** (numérico
  continuo, 0-100) se grafica con `charts.line_chart()`; el historial de
  señal/confianza/tendencia se muestra en una **tabla cronológica**
  (`st.dataframe(..., use_container_width=True)`), no en un gráfico.
- **Diseño responsive**: reutiliza `layout.render_view_mode_selector()`
  (misma key/help que las otras 3 páginas) y
  `render_responsive_metric_group()`. Igual que "Mercado"/"Indicadores",
  `get_cards_per_row()`/`render_responsive_grid()` no aplican: la página
  muestra un único símbolo a la vez.
- **Garantía de solo lectura sin cambios**: `senales.py` no ejecuta SQL,
  no importa `sqlite3` ni el Repository directamente, y no recalcula ni
  regenera ninguna señal — todo viene de
  `DashboardService.get_signals_page()`.
- **`tests/test_dashboard_navigation.py`** se amplió para incluir
  "Señales" como cuarta página en la validación de estado compartido
  (el radio del harness usa la opción ASCII "Senales", sin eñe, por el
  mismo bug de codificación de `AppTest.from_function()` ya documentado
  en ese archivo — confirmado también con "ñ", no solo con tildes).

## Nota de implementación (Iteración 5.7)

Se implementó la página "Recomendaciones de IA" (`recomendaciones.py`),
reutilizando la infraestructura ya existente sin agregar ninguna
dependencia nueva:

- **`repository.py` no ganó ningún método nuevo**: `get_ai_history()`
  (ya existente desde la Iteración 5.2) fue suficiente — mismo criterio
  que "Mercado"/"Indicadores"/"Señales". Antes de escribir código se
  inspeccionó el esquema real de `ai_recommendations` (`PRAGMA
  table_info`): `id, exchange, symbol, recommendation, confidence,
  risk_level, reasoning, advantages, risks, summary, provider, model,
  prompt_version, created_at, processing_time_ms, raw_response`. Todas
  las columnas son `NOT NULL` **excepto `raw_response`** (153/153 filas
  en `NULL` actualmente: `DummyProvider` nunca la puebla, ver
  `src/ai/recommendation.py`). Coincide exactamente con `AIRecommendation`
  (`src/ai/recommendation.py`), salvo que el modelo llama `timestamp` al
  campo que la tabla llama `created_at` (mapeo ya resuelto por
  `SQLiteAIRepository`, sin relación con esta iteración). Con los datos
  actuales, `recommendation` es siempre "Hold", `risk_level` siempre
  "Low" y `confidence` siempre 60.0 (`DummyProvider` es determinista).
- **`DashboardService.get_ai_recommendations_page(exchange, symbol,
  limit)`** (`service.py`): una sola llamada a `get_ai_history()` (no
  llama también a `get_latest_ai_recommendation()`), mismo patrón que
  `get_market_page()`/`get_indicators_page()`/`get_signals_page()`. No
  llama a `DecisionEngine` ni a ningún `AIProvider`.
- **`models.py`** ganó 2 modelos nuevos: `AIRecommendationSummaryView`
  (los mismos campos de `AIRecommendation` — `recommendation`,
  `confidence`, `risk_level`, `reasoning`, `summary`, `advantages`,
  `risks`, `provider`, `model` — aplanados, más `record_count`/
  `has_data`) e `AIRecommendationPageView` (símbolos, símbolo elegido,
  resumen opcional, historial, disponibilidad y mensaje). El historial
  reutiliza `list[AIRecommendation]` directamente, mismo criterio que
  `IndicatorPageView`/`SignalPageView`: un modelo
  "AIRecommendationHistoryView" habría sido una copia redundante.
- **`formatters.py`/`charts.py` no ganaron nada nuevo**: `format_confidence`,
  `format_risk_level`, `format_enum` y `format_timestamp` (ya existentes)
  cubrían todo lo necesario; `charts.line_chart()` (ya existente) se
  reutilizó para la confianza.
- **`components.py`** ganó 6 helpers: `render_ai_status()` (insignia de
  la recomendación, color fijo `theme.COLOR_AI`, mismo criterio que ya
  usa "Resumen General"), `render_ai_metrics()` (confianza + riesgo, vía
  `theme.get_risk_color()`), `render_ai_explanation()` (resumen en una
  línea + razonamiento/ventajas/riesgos completos en un
  `st.expander`, detalle expandible para móvil), `render_ai_availability()`
  (fecha de generación + registros + proveedor/modelo, dejando explícito
  que sigue siendo un proveedor simulado) y
  `render_ai_history_chart()`/`render_ai_history_table()`.
- **Gráfico vs. tabla — misma decisión que "Señales"**: `recommendation`/
  `risk_level` son categóricos; solo la **confianza** (numérica continua,
  0-100) se grafica con `charts.line_chart()`, y el historial de
  recomendación/confianza/riesgo se muestra en una **tabla cronológica**
  (`st.dataframe(..., use_container_width=True)`).
- **Diseño responsive**: reutiliza `layout.render_view_mode_selector()`
  (misma key/help que las otras 4 páginas) y
  `render_responsive_metric_group()`. Igual que "Mercado"/"Indicadores"/
  "Señales", `get_cards_per_row()`/`render_responsive_grid()` no
  aplican: la página muestra un único símbolo a la vez.
- **Garantía de solo lectura sin cambios**: `recomendaciones.py` no
  ejecuta SQL, no importa `sqlite3` ni el Repository directamente, y no
  recalcula ni regenera ninguna recomendación — todo viene de
  `DashboardService.get_ai_recommendations_page()`.
- **`tests/test_dashboard_navigation.py`** se amplió para incluir
  "Recomendaciones de IA" como quinta página en la validación de estado
  compartido (la etiqueta "Recomendaciones de IA" no tiene tildes ni
  "ñ", así que no requirió ningún alias ASCII para el harness).

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
Repository        src/dashboard/repository.py   (DashboardRepository / SQLiteDashboardRepository)
    ↓
Service           src/dashboard/service.py        (DashboardService: arma modelos de presentación)
    ↓
View Model        src/dashboard/models.py           (DashboardSummary, DashboardSummaryView, ...)
    ↓
Components/Layout src/dashboard/components.py + layout.py (tarjetas, insignias, grid responsive)
    ↓
Page              src/dashboard/pages/*.py               (una página Streamlit por vista)
    ↓
Streamlit (renderiza en el navegador)
```

Resumido: **Repository → Service → View Model → Components/Layout → Page**.

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

## Estructura de módulos (base en la Iteración 5.2, ampliada en 5.3/5.4/5.5/5.6/5.7)

```
src/dashboard/
├── __init__.py
├── app.py                  # Punto de entrada: streamlit run src/dashboard/app.py
├── config.py                 # DashboardConfig + build_dashboard_config()
├── models.py                   # TableStatus, DashboardStatus, Latest*Snapshot,
│                                # DashboardSummary, DashboardSummaryView (5.3),
│                                # MarketSummaryView/MarketHistoryPoint/MarketPageView (5.4),
│                                # IndicatorSummaryView/IndicatorPageView (5.5),
│                                # SignalSummaryView/SignalPageView (5.6),
│                                # AIRecommendationSummaryView/AIRecommendationPageView (5.7)
├── repository.py                 # DashboardRepository (interfaz) + SQLiteDashboardRepository
│                                  # (sin cambios en 5.4/5.5/5.6/5.7: get_market_history()/
│                                  # get_indicator_history()/get_signal_history()/
│                                  # get_ai_history() ya alcanzaban)
├── service.py                      # DashboardService (+ get_summary_view() 5.3,
│                                    # + get_market_page() 5.4, + get_indicators_page() 5.5,
│                                    # + get_signals_page() 5.6, + get_ai_recommendations_page() 5.7)
├── filters.py                        # normalize_symbol/normalize_exchange/validate_limit
├── formatters.py                       # format_price/percent/timestamp/enum +
│                                        # format_price_compact/confidence/score/
│                                        # risk_level/relative_status (5.3) +
│                                        # format_price_change/volume/record_count (5.4)
│                                        # (5.5/5.6/5.7 reutilizan format_price/format_score/
│                                        # format_confidence/format_risk_level/format_enum/
│                                        # format_timestamp, sin agregar nada)
├── theme.py                              # Paleta + get_signal_color/get_risk_color/
│                                         # get_change_color/to_streamlit_color_name (5.3)
├── layout.py                              # get_cards_per_row/is_compact/render_responsive_grid/
│                                          # render_responsive_metric_group (responsive, 5.3) +
│                                          # render_view_mode_selector() (construcción única y
│                                          # compartida del selector "Vista" entre páginas, 5.4)
├── charts.py                             # empty_figure/line_chart (5.2; reutilizado sin
│                                         # cambios por Mercado en 5.4, Señales en 5.6 y
│                                         # Recomendaciones de IA en 5.7) +
│                                         # multi_line_chart() (series superpuestas, 5.5)
├── components.py                           # render_not_available/render_kpi_card +
│                                           # render_section_header/render_status_badge (sin HTML)/
│                                           # render_data_availability/render_summary_card
│                                           # (con modo compact, 5.3) +
│                                           # render_market_metrics/render_market_availability/
│                                           # render_price_history_chart (5.4) +
│                                           # render_indicator_metrics/render_indicator_availability/
│                                           # render_indicator_history_charts (5.5) +
│                                           # render_signal_status/render_signal_metrics/
│                                           # render_signal_explanation/render_signal_availability/
│                                           # render_signal_history_chart/render_signal_history_table (5.6) +
│                                           # render_ai_status/render_ai_metrics/render_ai_explanation/
│                                           # render_ai_availability/render_ai_history_chart/
│                                           # render_ai_history_table (5.7)
└── pages/                                    # Una página por vista
    ├── __init__.py
    ├── resumen.py                             # Funcional desde 5.3 (tarjetas por símbolo)
    ├── mercado.py                             # Funcional desde 5.4 ("Mercado", antes "Precios")
    ├── indicadores.py                         # Funcional desde 5.5
    ├── senales.py                             # Funcional desde 5.6
    ├── recomendaciones.py                     # Funcional desde 5.7
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
> datos); se completaron progresivamente: "Resumen General" en la 5.3,
> `mercado.py` en la 5.4 (pasó a llamarse "Mercado", antes "Precios",
> para que coincida con el nombre del módulo y de la tabla que consulta),
> "Indicadores" en la 5.5, "Señales" en la 5.6 y "Recomendaciones de IA"
> en la 5.7. **Las 6 páginas del Dashboard ya son funcionales.**

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
2. **Mercado** (`mercado.py`, antes "Precios") — **funcional desde la
   Iteración 5.4**: para el símbolo elegido en la barra lateral
   (`DashboardService.get_market_page()`), muestra precio actual,
   variación absoluta y porcentual frente al registro anterior, máximo y
   mínimo del período disponible, volumen del último dato, fecha del
   último dato, cantidad de registros disponibles y un gráfico de línea
   con el historial de precio (`charts.line_chart()`, ya existente desde
   la 5.2). Sin indicadores técnicos ni señales superpuestas (eso vive en
   `market_indicators`/`market_signals`, no en `market_data`): quedan
   para las páginas Indicadores/Señales. Incluye el selector de vista
   responsive compartido (`Vista`, vía
   `layout.render_view_mode_selector()`, ver "Diseño responsive" más
   arriba).
3. **Indicadores** (`indicadores.py`) — **funcional desde la Iteración
   5.5**: para el símbolo elegido en la barra lateral
   (`DashboardService.get_indicators_page()`), muestra el último valor de
   RSI, MACD (línea/señal/histograma), medias móviles (SMA, EMA rápida/
   media/lenta), Bandas de Bollinger (superior/media/inferior) y VWAP,
   la fecha del último cálculo, y 3 gráficos de historial (RSI, MACD,
   medias móviles). ATR, ADX y Volatilidad se declaran explícitamente
   como no disponibles (no existen en `market_indicators`, ver "Nota de
   implementación (Iteración 5.5)" más arriba). Incluye el selector de
   vista responsive compartido.
4. **Señales** (`senales.py`) — **funcional desde la Iteración 5.6**: para
   el símbolo elegido en la barra lateral
   (`DashboardService.get_signals_page()`), muestra la señal actual
   (`signal_type`, insignia de color), score, confianza, tendencia y su
   fuerza, el veredicto de cada componente (`ema_signal`/`macd_signal`/
   `rsi_signal`/`bollinger_signal`), la fecha de generación, la cantidad
   de registros disponibles, un gráfico de la evolución del score y una
   tabla cronológica de señal/confianza/tendencia. El riesgo no aparece
   aquí: no es un campo de `market_signals` (vive en
   `ai_recommendations`, página "Recomendaciones de IA"). Incluye el
   selector de vista responsive compartido.
5. **Recomendaciones de IA** (`recomendaciones.py`) — **funcional desde
   la Iteración 5.7**: para el símbolo elegido en la barra lateral
   (`DashboardService.get_ai_recommendations_page()`), muestra la
   recomendación actual (insignia), confianza, nivel de riesgo (insignia
   de color), un resumen en una línea y el razonamiento completo con
   ventajas/riesgos en un `st.expander`, la fecha de generación, la
   cantidad de registros disponibles, un gráfico de la evolución de la
   confianza y una tabla cronológica de recomendación/confianza/riesgo.
   Declara explícitamente que el proveedor (`DummyProvider`) sigue siendo
   simulado, no un modelo de lenguaje real. `processing_time_ms` no se
   muestra en el resumen (detalle interno de rendimiento, no relevante
   para la interpretación de la recomendación). Incluye el selector de
   vista responsive compartido.
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
- **`render_market_metrics(summary, compact)`** (5.4): precio actual,
  variación absoluta/porcentual, máximo/mínimo del período y volumen de
  "Mercado", vía `render_responsive_metric_group()`.
- **`render_market_availability(summary)`** (5.4): última actualización
  relativa + cantidad de registros disponibles de "Mercado".
- **`render_price_history_chart(history, symbol)`** (5.4): envuelve
  `charts.line_chart()` con `st.plotly_chart(..., use_container_width=True)`
  (sin ancho fijo, sin scroll horizontal).
- **`render_indicator_metrics(summary, compact)`** (5.5): RSI, MACD
  (línea/señal/histograma), medias móviles (SMA, EMA rápida/media/lenta),
  Bandas de Bollinger y VWAP de "Indicadores", vía
  `render_responsive_metric_group()`.
- **`render_indicator_availability(summary)`** (5.5): fecha del último
  cálculo + declaración explícita de ATR/ADX/Volatilidad como no
  disponibles.
- **`render_indicator_history_charts(history, symbol)`** (5.5): 3
  gráficos (RSI, MACD, medias móviles), vía `charts.line_chart()` y
  `charts.multi_line_chart()`.
- **`render_signal_status(summary)`** (5.6): insignia de color de la
  señal actual, vía `theme.get_signal_color()`.
- **`render_signal_metrics(summary, compact)`** (5.6): score, confianza,
  tendencia y su fuerza de "Señales".
- **`render_signal_explanation(summary, compact)`** (5.6): veredicto de
  cada componente (EMA/MACD/RSI/Bollinger).
- **`render_signal_availability(summary)`** (5.6): fecha de generación +
  registros disponibles, con la nota explícita de que el riesgo no
  aplica a esta página.
- **`render_signal_history_chart(history, symbol)`** (5.6): evolución
  del score, vía `charts.line_chart()`.
- **`render_signal_history_table(history)`** (5.6): historial
  cronológico de señal/confianza/tendencia como tabla
  (`st.dataframe(..., use_container_width=True)`), no como gráfico —
  son valores categóricos, y graficarlos como números arbitrarios sería
  engañoso.
- **`render_ai_status(summary)`** (5.7): insignia de la recomendación
  actual, color fijo `theme.COLOR_AI` (mismo criterio que ya usa
  "Resumen General").
- **`render_ai_metrics(summary, compact)`** (5.7): confianza (métrica) +
  riesgo (insignia, vía `theme.get_risk_color()`).
- **`render_ai_explanation(summary)`** (5.7): resumen en una línea +
  razonamiento/ventajas/riesgos completos en un `st.expander`.
- **`render_ai_availability(summary)`** (5.7): fecha de generación +
  registros + proveedor/modelo, dejando explícito que sigue siendo un
  proveedor simulado.
- **`render_ai_history_chart(history, symbol)`** (5.7): evolución de la
  confianza, vía `charts.line_chart()`.
- **`render_ai_history_table(history)`** (5.7): historial cronológico de
  recomendación/confianza/riesgo como tabla, no como gráfico — mismo
  criterio que "Señales".
- **Gráfico de serie temporal** (`charts.line_chart`/`charts.multi_line_chart`):
  envoltura común para precio/indicadores/score/confianza a lo largo del
  tiempo — en uso desde la 5.4 en "Mercado", desde la 5.5 en
  "Indicadores", desde la 5.6 en "Señales" y desde la 5.7 en
  "Recomendaciones de IA".
- **Bloque de razones**: lista de `reason`/`rule_strength` de cada regla
  de señal — no se expone todavía en el resumen de "Señales" (solo el
  veredicto de cada componente, no su explicación en texto completo).
  `advantages`/`risks` de IA sí se exponen desde la 5.7, en
  `render_ai_explanation()`.

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

(Ver "Reglas obligatorias para páginas futuras" en la sección de diseño
responsive, más arriba, para la regla completa de tablas/gráficos.)

## Qué NO hace el Dashboard

- No escribe en ninguna tabla.
- No recalcula indicadores, señales ni recomendaciones.
- No conecta con Binance ni con ningún proveedor de IA directamente: solo
  lee lo que `src/main.py` ya guardó en ciclos anteriores.
- No requiere ningún cambio en `src/market/`, `src/database/`,
  `src/services/`, `src/signals/`, `src/ai/` ni `src/utils/`: los 4
  repositorios ya exponen exactamente los métodos de lectura
  (`fetch_latest`/`fetch_history`) que el Dashboard necesita.
- No muestra ATR, ADX ni Volatilidad: el proyecto todavía no los calcula
  en ninguna etapa (ni el bot ni el Dashboard) — "Indicadores" los
  declara explícitamente como no disponibles en vez de omitirlos en
  silencio o inventarlos.
- No muestra nivel de riesgo en "Señales": ese campo no existe en
  `market_signals` (vive en `ai_recommendations`, página "Recomendaciones
  de IA") — es un concepto de otra página, no un dato ausente de esta
  tabla.
- No conecta con un proveedor de IA real: "Recomendaciones de IA"
  muestra lo que `DummyProvider` (simulado) ya guardó, no un modelo de
  lenguaje real — lo declara explícitamente en vez de sugerir lo
  contrario.
- No ejecuta `SignalEngine`, `IndicatorEngine` ni `DecisionEngine`: el
  Dashboard entero es de solo lectura sobre lo que esos motores ya
  guardaron en ciclos anteriores de `python -m src.main`.

## Dependencias

`streamlit` y `plotly` (ambas Python puro, sin servicios adicionales),
agregadas a `requirements.txt` desde la Iteración 5.2. Ninguna iteración
posterior (5.3, 5.4, 5.5, 5.6, 5.7) agregó ninguna dependencia nueva.

## Estado por iteración

- **5.1** (diseño): alcance y arquitectura documentados, sin código.
- **5.2** (estructura base): repositorio/servicio/config/helpers/`app.py`
  funcionando, 6 páginas esqueleto.
- **5.3**: página "Resumen General" funcional (`DashboardSummaryView`,
  `get_summary_view()`, `theme.py`, `layout.py`/diseño responsive,
  tarjetas de resumen sin HTML).
- **5.4**: página "Mercado" funcional (antes "Precios";
  `MarketSummaryView`/`MarketHistoryPoint`/`MarketPageView`,
  `get_market_page()`, gráfico de historial de precio). Al cerrar la
  iteración se centralizó el selector "Vista" en
  `layout.render_view_mode_selector()` (ver "Diseño responsive" más
  arriba), compartido entre páginas, y se agregó
  `tests/test_dashboard_navigation.py` (pruebas de integración de
  navegación y estado compartido).
- **5.5**: página "Indicadores" funcional
  (`IndicatorSummaryView`/`IndicatorPageView`, `get_indicators_page()`,
  `charts.multi_line_chart()`, 3 gráficos de historial). ATR, ADX y
  Volatilidad declarados explícitamente como no disponibles (no existen
  en `market_indicators`). `tests/test_dashboard_navigation.py` se
  amplió para incluir "Indicadores" en la validación de estado
  compartido.
- **5.6**: página "Señales" funcional
  (`SignalSummaryView`/`SignalPageView`, `get_signals_page()`, gráfico
  de score + tabla cronológica de señal/confianza/tendencia). Riesgo
  declarado explícitamente como no aplicable a esta página (vive en
  `ai_recommendations`, no en `market_signals`).
  `tests/test_dashboard_navigation.py` se amplió para incluir "Señales"
  como cuarta página en la validación de estado compartido.
- **5.7** (esta): página "Recomendaciones de IA" funcional
  (`AIRecommendationSummaryView`/`AIRecommendationPageView`,
  `get_ai_recommendations_page()`, gráfico de confianza + tabla
  cronológica de recomendación/confianza/riesgo + razonamiento/ventajas/
  riesgos en un expander). Proveedor declarado explícitamente como
  simulado (`DummyProvider`). `tests/test_dashboard_navigation.py` se
  amplió para incluir "Recomendaciones de IA" como quinta página en la
  validación de estado compartido. Las 6 páginas del Dashboard ya son
  funcionales.
- **Pendiente para una iteración futura**: auto-refresh real,
  comparación entre símbolos, diseño visual definitivo de toda la
  aplicación (identidad visual más allá de la paleta ya centralizada en
  `theme.py`), conexión a un proveedor de IA real (OpenAI/Claude),
  validación visual real en navegador, aprobación formal de la Etapa 5.
