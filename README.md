# Crypto AI Operation Center

Sistema propio para observar el mercado de criptomonedas de forma automatizada,
construido paso a paso y en etapas controladas.

Este repositorio se construye **por etapas**. Cada etapa se valida por completo
antes de avanzar a la siguiente. No se salta ningún paso.

## Etapas completadas

- ✅ **Etapa 1** — Bot de consulta de mercado (solo lectura). Ver
  [docs/ALCANCE_ETAPA_1.md](docs/ALCANCE_ETAPA_1.md).
- ✅ **Etapa 1.5** — Refactorización y preparación de arquitectura (esta
  etapa no cambia el comportamiento del bot, solo cómo está organizado el
  código por dentro). Ver [docs/ALCANCE_ETAPA_1_5.md](docs/ALCANCE_ETAPA_1_5.md)
  y [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).
- ✅ **Etapa 2** — Motor de indicadores técnicos (SMA, EMA, RSI, MACD,
  Bollinger, VWAP), calculados sobre el historial ya guardado y persistidos
  en una tabla independiente. Ver [docs/ALCANCE_ETAPA_2.md](docs/ALCANCE_ETAPA_2.md).
- ✅ **Etapa 3** — Motor de señales (sin inteligencia artificial):
  transforma los indicadores en señales estructuradas (tendencia, fuerza
  individual por regla, score ponderado, confianza, razones explicables)
  mediante reglas configurables y tipadas, persistidas en una tabla
  independiente. Ver [docs/ALCANCE_ETAPA_3.md](docs/ALCANCE_ETAPA_3.md).
- 🔶 **Etapa 4 (en revisión, no aprobada todavía)** — Motor de decisión de
  IA: interpreta, explica y prioriza las señales de la Etapa 3 (sin
  reemplazar el motor de reglas), generando una recomendación estructurada
  (acción sugerida, confianza propia, nivel de riesgo, razonamiento y
  factores positivos/negativos), persistida en una tabla independiente.
  Hoy usa un proveedor simulado (`DummyProvider`); OpenAI/Claude quedan
  preparados pero sin conectar. Ver [docs/ALCANCE_ETAPA_4.md](docs/ALCANCE_ETAPA_4.md).
- 📝 **Etapa 5 (en desarrollo, Iteración 5.6 — Resumen General, Mercado,
  Indicadores y Señales funcionales, el resto del Dashboard todavía no
  está completo)** — Dashboard de solo lectura (Streamlit) sobre las 4
  tablas ya generadas por las Etapas 1 a 4. Ver
  [docs/ALCANCE_ETAPA_5.md](docs/ALCANCE_ETAPA_5.md) y
  [docs/ARQUITECTURA_DASHBOARD.md](docs/ARQUITECTURA_DASHBOARD.md).

## Qué hace el bot hoy

- Consulta precios públicos de Binance para `BTCUSDT`, `ETHUSDT` y `SOLUSDT`.
- Obtiene precio actual, volumen 24h, variación % 24h y la fecha/hora de la consulta.
- Guarda cada resultado en la tabla `market_data` de una base de datos SQLite local.
- Calcula indicadores técnicos (SMA, EMA rápida/media/lenta, RSI, MACD,
  Bandas de Bollinger, VWAP) sobre el historial de cada símbolo, y los
  guarda en la tabla `market_indicators`, independiente de `market_data`.
- Genera una señal estructurada por símbolo (tendencia, fuerza de tendencia,
  señal de EMA/MACD/RSI/Bollinger, la fuerza individual y la razón en texto
  de cada una, score 0-100 ponderado y nivel de confianza), combinando
  reglas determinísticas y configurables sobre los indicadores ya
  calculados, y la guarda en la tabla `market_signals`, independiente de
  las otras dos.
- Interpreta la última señal con un motor de decisión de IA (acción
  sugerida en 7 niveles desde Strong Buy hasta Strong Sell, confianza
  propia, nivel de riesgo en 5 niveles, razonamiento y factores
  positivos/negativos), y la guarda en la tabla `ai_recommendations`,
  independiente de las otras tres. Hoy usa un proveedor simulado y
  determinista (`DummyProvider`, con Buy/Sell/Hold y riesgo Low/Medium,
  sin conexión a ninguna API real); la IA **no reemplaza** al motor de
  señales, solo lo interpreta. Se puede desactivar con `ai.enabled: false`
  en `config.yaml`, sin afectar el resto del ciclo.
- Repite todo el ciclo automáticamente cada 5 minutos (configurable).
- Registra toda la actividad y los errores en archivos de log.

**Todavía NO hace lo siguiente (a propósito, queda preparado para etapas futuras):**

- No usa ninguna clave privada real (de Binance, OpenAI, Anthropic, Telegram, etc.).
- No compra ni vende nada. No mueve dinero real ni de prueba.
- No conecta ningún proveedor de IA real (OpenAI/Claude): el motor de
  decisión de IA existe y funciona, pero con un proveedor simulado.
- No incluye Machine Learning, Fine Tuning, Embeddings, RAG ni bases de
  datos vectoriales.
- No incluye dashboard ni interfaz visual todavía.
- No envía mensajes a Telegram ni a ningún otro servicio externo todavía.
- No calcula ATR ni ADX todavía (requieren datos de velas que este proyecto
  no consulta aún; ver [docs/ALCANCE_ETAPA_2.md](docs/ALCANCE_ETAPA_2.md)).

## Estructura del proyecto (desde la Etapa 4)

```
Crypto_AI_Operation_Center/
├── README.md
├── requirements.txt
├── .env.example              # Plantilla de credenciales futuras (no se usan todavía)
├── config/
│   └── config.yaml            # Monedas, intervalo, indicadores, reglas de señales
├── src/
│   ├── main.py                 # Punto de entrada (Composition Root): SOLO arma piezas y coordina
│   ├── market/                  # Clientes de exchanges (hoy: Binance)
│   │   ├── base.py                # Interfaz común ExchangeClient
│   │   └── binance.py             # Implementación de Binance
│   ├── database/                  # Repositorios de mercado e indicadores
│   │   ├── base.py                  # Interfaces MarketDataRepository e IndicatorRepository
│   │   ├── sqlite_repository.py               # market_data (SQLite, en uso)
│   │   ├── postgres_repository.py             # market_data (preparado, no implementado)
│   │   ├── sqlite_indicator_repository.py     # market_indicators (SQLite, en uso)
│   │   └── postgres_indicator_repository.py   # market_indicators (preparado, no implementado)
│   ├── services/                    # Lógica de negocio de mercado e indicadores
│   │   ├── market_data_service.py     # Orquesta exchange + repositorio de precios
│   │   ├── indicator_engine.py        # Cálculo puro de indicadores técnicos
│   │   └── indicator_service.py       # Orquesta historial + motor + repositorio de indicadores
│   ├── signals/                       # Motor de señales (Etapa 3, en revisión)
│   │   ├── enums.py                     # Direction, TrendStrength, ConfidenceLevel, SignalType + labels
│   │   ├── rule_result.py                 # Modelo genérico RuleResult[TrendLabel|EMALabel|...]
│   │   ├── base.py                          # Interfaz SignalRepository
│   │   ├── sqlite_repository.py               # market_signals (SQLite, en uso)
│   │   ├── postgres_repository.py              # market_signals (preparado, no implementado)
│   │   ├── engine.py                            # SignalEngine (cálculo puro, sin I/O)
│   │   ├── service.py                            # SignalService (orquesta indicadores + precio + motor)
│   │   ├── aggregator.py                          # Combina reglas en score/confidence/trend_strength
│   │   └── rules/                                  # TrendRule, EMARule, MACDRule, RSIRule, BollingerRule
│   ├── ai/                            # Motor de decisión de IA (Etapa 4, en revisión)
│   │   ├── context.py                   # Modelo MarketContext + build_market_context()
│   │   ├── recommendation.py              # RecommendationAction, RiskLevel, AIRecommendation
│   │   ├── explanation.py                   # AIExplanation + build_explanation()
│   │   ├── models.py                          # Reexporta los 3 modelos anteriores
│   │   ├── base.py                              # Interfaz AIProvider + AIProviderResponse
│   │   ├── providers/                             # DummyProvider (en uso), OpenAI/Claude (stubs)
│   │   ├── prompt_builder.py                        # PromptBuilder (MarketContext -> texto)
│   │   ├── decision_engine.py                         # DecisionEngine (cálculo puro, sin I/O)
│   │   ├── repository.py                                # Interfaz AIRepository
│   │   ├── sqlite_repository.py                            # ai_recommendations (SQLite, en uso)
│   │   └── service.py                                        # AIService (orquesta señal + motor + repositorio)
│   ├── models/                        # Modelos de datos (Pydantic)
│   │   ├── market_data.py               # MarketTicker
│   │   ├── indicator_data.py            # IndicatorSnapshot
│   │   └── signal_data.py               # SignalSnapshot
│   ├── utils/                           # Configuración y logging
│   │   ├── config.py                      # Lee config.yaml + .env
│   │   └── logger.py                      # Configuración de logs
│   ├── dashboard/                         # Dashboard Streamlit (Etapa 5, en desarrollo — ver docs/ARQUITECTURA_DASHBOARD.md)
│   ├── alerts/                            # Reservado para alertas (etapa futura)
│   └── telegram/                          # Reservado para Telegram (etapa futura)
├── data/
│   └── crypto_data.db         # Base de datos SQLite (se crea automáticamente)
├── logs/
│   └── app.log                 # Archivo de log (se crea automáticamente)
├── tests/                       # Pruebas automatizadas (pytest)
└── docs/
    ├── ALCANCE_ETAPA_1.md
    ├── ALCANCE_ETAPA_1_5.md
    ├── ALCANCE_ETAPA_2.md
    ├── ALCANCE_ETAPA_3.md
    ├── ALCANCE_ETAPA_4.md
    ├── ALCANCE_ETAPA_5.md
    ├── ARQUITECTURA.md
    └── ARQUITECTURA_DASHBOARD.md
```

Ver el detalle de por qué está organizado así en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## Qué vas a instalar

Solo necesitas Python 3.10 o superior (ya tienes 3.12) y las librerías listadas
en `requirements.txt`. Ninguna de ellas requiere pagar ni crear cuentas.

## Cómo instalar (desde cero)

Desde la carpeta raíz del proyecto (`c:\Crypto_AI_Operation_Center`):

**PowerShell (Windows):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Git Bash / terminal tipo Unix:**
```bash
python -m venv venv
source venv/Scripts/activate
pip install -r requirements.txt
```

`venv` es un "entorno virtual": una carpeta aislada donde se instalan las
librerías de este proyecto sin mezclarse con otros programas Python que tengas
en tu computadora.

Sabrás que el entorno virtual está activo porque tu terminal mostrará `(venv)`
al inicio de la línea. A partir de ahí, todos los comandos (`pip`, `python`,
`pytest`) deben ejecutarse con el entorno activado.

### Sobre el archivo `.env`

El proyecto incluye `.env.example`, una plantilla con nombres de variables
para credenciales que se usarán en etapas futuras (Binance privado, OpenAI,
Anthropic, Telegram, CoinGecko, NewsAPI, base de datos). **No es necesario
crear un archivo `.env` para que el bot funcione hoy**: todas esas
credenciales son opcionales y, si no existen, el bot simplemente no las usa.

Si más adelante quieres dejarlo preparado, puedes copiar la plantilla:

```bash
cp .env.example .env          # Git Bash
Copy-Item .env.example .env   # PowerShell
```

y completar solo los valores que ya tengas. El archivo `.env` nunca se sube
a git (está en `.gitignore`).

## Cómo ejecutar

Con el entorno virtual activado:

```bash
python -m src.main
```

Esto va a, en cada ciclo:

1. Leer la configuración desde `config/config.yaml` (y `.env` si existe).
2. Consultar Binance para las monedas configuradas y guardar los precios en
   `market_data`.
3. Calcular los indicadores técnicos disponibles con el historial
   acumulado y guardarlos en `market_indicators`.
4. Generar una señal estructurada a partir del último indicador y el
   precio más reciente, y guardarla en `market_signals`.
5. Interpretar la última señal con el motor de decisión de IA (proveedor
   simulado `DummyProvider` por defecto) y guardar la recomendación en
   `ai_recommendations` (se puede desactivar con `ai.enabled: false` en
   `config.yaml`, sin afectar los 3 pasos anteriores).
6. Escribir actividad y errores en `logs/app.log`.
7. Repetir automáticamente cada 5 minutos (o el intervalo que definas).

Para detenerlo, presiona `Ctrl + C` en la terminal.

Nota: los indicadores (y por lo tanto las señales) que necesitan mucho
historial (ej. la EMA lenta, que por defecto usa 200 lecturas) no van a
tener valor todavía en los primeros ciclos — es normal, y se completan
solos a medida que se acumulan datos.

## Cómo ejecutar el Dashboard (Etapa 5, Iteración 5.6 — Resumen General, Mercado, Indicadores y Señales funcionales)

Instalar dependencias (incluye `streamlit`/`plotly`, ya en `requirements.txt`):

```bash
pip install -r requirements.txt
```

Ejecutar:

```bash
streamlit run src/dashboard/app.py
```

**Estado actual: Iteración 5.6 completada — "Resumen General", "Mercado",
"Indicadores" y "Señales" ya son funcionales; el resto del Dashboard
todavía NO está completo, y la Etapa 5 en general tampoco.**

"Resumen General" muestra, para cada símbolo configurado
(`BTCUSDT`/`ETHUSDT`/`SOLUSDT`), una tarjeta con precio, variación 24h,
señal más reciente, score, confianza de la señal, recomendación de IA,
confianza de IA, nivel de riesgo, última actualización relativa ("Hace 5
min") y qué tablas tienen datos disponibles (mercado/indicadores/
señales/IA) — todo con valores "N/D" cuando algo todavía no existe, y un
resumen general (cuántos símbolos están configurados, cuántos tienen
datos completos, cuándo se actualizó el sistema por última vez).

**Mercado** (antes "Precios") muestra, para el símbolo elegido en la
barra lateral, el precio actual, la variación absoluta y porcentual
frente al registro anterior, el máximo y el mínimo del período
disponible, el volumen del último dato, la fecha del último dato, la
cantidad de registros disponibles (respeta el límite de historial
elegido en la barra lateral) y un gráfico de línea con el historial de
precio. No calcula indicadores técnicos, señales ni recomendaciones de
IA (eso vive en las páginas Indicadores/Señales/Recomendaciones de IA).

**Indicadores** muestra, para el mismo símbolo elegido, el último valor
de RSI, MACD (línea/señal/histograma), medias móviles (SMA, EMA rápida/
media/lenta), Bandas de Bollinger (superior/media/inferior) y VWAP, la
fecha del último cálculo, y 3 gráficos de historial (RSI, MACD, medias
móviles). Cada valor todavía no calculado (ej. la EMA lenta, que
necesita 200 lecturas de historial) se muestra como "N/D", nunca
inventado. **ATR, ADX y Volatilidad se declaran explícitamente como no
disponibles**: este proyecto todavía no los calcula en ninguna etapa
(ver más arriba, "Todavía NO hace lo siguiente").

**Señales** muestra, para el mismo símbolo elegido, la señal actual
(alcista/neutral/bajista), score, confianza, tendencia y su fuerza, el
veredicto de cada componente (EMA/MACD/RSI/Bollinger), la fecha de
generación, la cantidad de registros disponibles, un gráfico con la
evolución del score y una tabla cronológica de señal/confianza/
tendencia (categóricas: se muestran en tabla, no en gráfico, para no
representarlas con una escala numérica engañosa). **El nivel de riesgo
no aparece en esta página**: no es un campo de `market_signals` (vive en
`ai_recommendations`, página "Recomendaciones de IA", todavía no
implementada) — la página lo declara explícitamente en vez de omitirlo
en silencio.

Las 4 páginas tienen **diseño responsive**: cada una incluye el selector
**"Vista"** con 3 modos (**Automática**, **Amplia**, **Compacta**) en la
barra lateral. En "Resumen General" controla cuántas tarjetas se
muestran por fila (3 en Amplia, 2 en Automática, 1 apilada verticalmente
en Compacta); en "Mercado", "Indicadores" y "Señales" controla si las
métricas se muestran en columnas o apiladas. **El modo de vista
responsive es compartido entre las páginas del Dashboard mediante una
única clave centralizada de st.session_state**: elegir "Compacta" en una
página y navegar a otra conserva "Compacta", en vez de resetear a un
valor distinto. La elección se guarda solo en la sesión del navegador
(`st.session_state`), nunca en disco ni en `config.yaml`.

La página que falta (Recomendaciones de IA) sigue siendo un esqueleto
mínimo — su contenido completo queda para una iteración futura, y la
identidad visual definitiva de toda la aplicación (más allá de la
paleta ya centralizada en `theme.py`) también se completará más
adelante. "Estado Técnico" ya es funcional desde la Iteración 5.2
(estado de las 4 tablas SQLite).

El diseño responsive se validó mediante pruebas automatizadas (AppTest) y
revisión de código (sin anchos/altos fijos, sin tablas HTML, sin scroll
horizontal forzado), pero **todavía no se validó visualmente en un
navegador real** en ningún tamaño de pantalla — se recomienda hacerlo
antes de dar por cerrado el diseño responsive de estas cuatro páginas.

El Dashboard es de **solo lectura**: nunca escribe en
`data/crypto_data.db`, no recalcula indicadores ni señales, no genera
recomendaciones de IA ni se conecta a Binance directamente — solo lee lo
que `python -m src.main` ya guardó. Si la base de datos todavía no existe,
lo indica en la barra lateral en vez de crearla. Ver
[docs/ARQUITECTURA_DASHBOARD.md](docs/ARQUITECTURA_DASHBOARD.md).

## Cómo ejecutar las pruebas

```bash
pytest
```

Esto valida la conexión a Binance, el guardado en la base de datos, los
modelos de datos, los servicios, el motor de indicadores, el motor de
señales (reglas + agregador), el motor de decisión de IA (contexto,
prompt, proveedor simulado, motor de decisión, repositorio) y la
configuración.

Las pruebas que dependen de Binance usan datos simulados (no llaman a
internet), así que son rápidas y siempre dan el mismo resultado. La
conexión real se verifica manualmente ejecutando el bot (paso anterior).

## Cómo revisar los datos guardados manualmente

Precios crudos:
```bash
python -c "from src.database.sqlite_repository import SQLiteMarketDataRepository; [print(t) for t in SQLiteMarketDataRepository('data/crypto_data.db').fetch_all()]"
```

Indicadores técnicos calculados:
```bash
python -c "from src.database.sqlite_indicator_repository import SQLiteIndicatorRepository; [print(s) for s in SQLiteIndicatorRepository('data/crypto_data.db').fetch_history('Binance', 'BTCUSDT')]"
```

Señales generadas:
```bash
python -c "from src.signals.sqlite_repository import SQLiteSignalRepository; [print(s) for s in SQLiteSignalRepository('data/crypto_data.db').fetch_history('Binance', 'BTCUSDT')]"
```

Recomendaciones de IA:
```bash
python -c "from src.ai.sqlite_repository import SQLiteAIRepository; [print(r) for r in SQLiteAIRepository('data/crypto_data.db').fetch_history('Binance', 'BTCUSDT')]"
```

## Estado del proyecto

✅ Etapa 1 aprobada: bot funcional de consulta de mercado.
✅ Etapa 1.5 aprobada: arquitectura modular, interfaces para exchanges y
bases de datos, modelos de datos con Pydantic, configuración combinada
`.env` + `config.yaml`, lógica de negocio separada en servicios.
✅ Etapa 2 aprobada: motor de indicadores técnicos, tabla independiente
`market_indicators`, configuración de periodos en `config.yaml`.
✅ Etapa 3 aprobada: motor de señales (sin IA), 5 reglas independientes que
devuelven `RuleResult` tipado (enums de label + fuerza individual),
agregador con score ponderado y confidence determinístico documentado,
tabla independiente `market_signals` con migración automática.
🔶 Etapa 4 implementada, en revisión (NO aprobada todavía): motor de
decisión de IA (`src/ai/`) que interpreta las señales de la Etapa 3 sin
reemplazarlas — `MarketContext -> PromptBuilder -> AIProvider ->
AIRecommendation` —, proveedor simulado `DummyProvider` conectado
(OpenAI/Claude preparados, sin conectar), tabla independiente
`ai_recommendations`. Pendiente de tu revisión y aprobación formal.

📝 Etapa 5, Iteración 5.6 (Resumen General, Mercado, Indicadores y
Señales funcionales, resto del Dashboard todavía NO completo): las
Iteraciones 5.3-5.5 agregaron `DashboardSummaryView`/`MarketSummaryView`/
`IndicatorSummaryView` y sus páginas, además de centralizar el selector
"Vista" en `layout.render_view_mode_selector()` (compartido entre
páginas). Esta iteración agregó, reutilizando lo anterior sin
duplicarlo: `SignalSummaryView`/`SignalPageView` (`models.py`, el
historial reutiliza `SignalSnapshot` directamente en vez de un modelo
nuevo), `DashboardService.get_signals_page()` (una sola llamada a
`get_signal_history()` ya existente: sin métodos nuevos en
`repository.py`, sin llamar a `SignalEngine`) y 6 componentes nuevos
(`render_signal_status`/`render_signal_metrics`/
`render_signal_explanation`/`render_signal_availability`/
`render_signal_history_chart`/`render_signal_history_table`). La página
"Señales" ya muestra la señal actual, score, confianza, tendencia,
veredicto de cada componente, fecha de generación, un gráfico del score
y una tabla cronológica para el símbolo elegido, con el selector de
vista responsive compartido; el riesgo se declara explícitamente como
no aplicable a esta página (vive en `ai_recommendations`, no en
`market_signals`). Recomendaciones de IA sigue siendo un esqueleto (sin
gráficos históricos todavía, eso es una iteración futura). Pendiente tu
auditoría antes de continuar.

Pendiente: aprobación formal de la Etapa 4 antes de avanzar a cualquier
etapa futura (Dashboard, Telegram, paper trading o trading automático, o
conectar un proveedor de IA real).
