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
- ✅ **Etapa 5 aprobada** — Dashboard de solo lectura (Streamlit) sobre
  las 4 tablas ya generadas por las Etapas 1 a 4: 6 páginas funcionales
  (Resumen General, Mercado, Indicadores, Señales, Recomendaciones de IA,
  Estado Técnico), diseño responsive con selector de vista compartido y
  centralizado. Ver [docs/ALCANCE_ETAPA_5.md](docs/ALCANCE_ETAPA_5.md) y
  [docs/ARQUITECTURA_DASHBOARD.md](docs/ARQUITECTURA_DASHBOARD.md).
- 🛠️ **Etapas 6.0-6.9 (implementación en curso)** — Paper Trading
  (compra/venta simulada, sin dinero real, sin conexión a un exchange
  para operar): dominio (`src/paper_trading/models.py`), motores puros
  (fill/position/PnL/risk/**reservation**/**reconciliation**), persistencia
  SQLite propia (`paper_trading_*`), `PaperTradingService` y una
  Composition Root con `PaperTradingApplication` para someter una orden
  manual, más una página de Dashboard **estrictamente de solo lectura**
  ("Paper Trading": saldo, patrimonio, posiciones, órdenes, trades,
  gráficos y auditoría de consistencia del PnL, sin ningún botón ni
  formulario de operación) — todo con pruebas automatizadas. **6.7**
  introdujo el ciclo de vida explícito de una orden MARKET con reservas
  reales (`NEW → PENDING con reserva → FILLED/CANCELLED con
  liberación`), vía `ReservationEngine` (motor puro) y transacciones
  atómicas nuevas en el repositorio. **6.8** agregó un subsistema de
  reconciliación (`ReconciliationEngine`/`ReconciliationService`) que
  detecta inconsistencias entre órdenes/reservas/ejecuciones/trades/PnL
  y permite repararlas solo mediante una acción explícita (nunca
  automática ni al arrancar): dry-run por defecto, auditoría persistente
  de cada corrida (`paper_trading_reconciliation_audit`), y una CLI
  administrativa separada (`python -m src.paper_trading.reconciliation_cli`)
  -- el Dashboard sigue sin ningún botón de inspección/reparación. **6.9**
  automatizó exclusivamente la *inspección* (nunca la reparación):
  `InspectionService` ejecuta `ReconciliationService.inspect()`
  periódicamente, compara contra la corrida anterior, y genera alertas
  (`NEW_ISSUE`/`RESOLVED_ISSUE`/`SEVERITY_INCREASED`/`SEVERITY_DECREASED`/
  `VALUE_CHANGED`/`INSPECTION_FAILED`/`SYSTEM_RECOVERED`) deduplicadas por
  SHA-256, entregadas vía `logging` con reintentos acotados; un
  `InspectionJob` con no-solapamiento en memoria puede ejecutarse
  manualmente (`python -m src.paper_trading.inspection_cli run|alerts|history`)
  o periódicamente (`python -m src.paper_trading.inspection_scheduler`,
  proceso independiente de `main.py`, gateado por
  `paper_trading.reconciliation_inspection.enabled`, `false` por
  defecto) -- **nunca llama `repair()`**, que sigue siendo exclusivamente
  manual (Etapa 6.8).
  `config.yaml -> paper_trading.enabled` es `false` por defecto:
  **ninguna orden se ejecuta automáticamente ni desde el
  Dashboard** (sin Strategy Engine, sin señales ni IA ejecutando
  órdenes). Ver [docs/ALCANCE_ETAPA_6.md](docs/ALCANCE_ETAPA_6.md) y
  [docs/ARQUITECTURA_PAPER_TRADING.md](docs/ARQUITECTURA_PAPER_TRADING.md).

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

## Cómo ejecutar el Dashboard (Etapa 5, Iteración 5.7 — las 6 páginas ya son funcionales)

Instalar dependencias (incluye `streamlit`/`plotly`, ya en `requirements.txt`):

```bash
pip install -r requirements.txt
```

Ejecutar:

```bash
streamlit run src/dashboard/app.py
```

**Estado actual: Iteración 5.7 completada — las 6 páginas del Dashboard
("Resumen General", "Mercado", "Indicadores", "Señales", "Recomendaciones
de IA" y "Estado Técnico") ya son funcionales. La Etapa 5 en general
todavía NO está cerrada**: falta el refinamiento visual definitivo, la
validación visual real en navegador y tu aprobación formal.

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
`ai_recommendations`, página "Recomendaciones de IA") — la página lo
declara explícitamente en vez de omitirlo en silencio.

**Recomendaciones de IA** muestra, para el mismo símbolo elegido, la
recomendación actual, confianza, nivel de riesgo, un resumen en una
línea y el razonamiento completo con ventajas/riesgos en un panel
expandible, la fecha de generación, la cantidad de registros
disponibles, un gráfico con la evolución de la confianza y una tabla
cronológica de recomendación/confianza/riesgo. **El proveedor sigue
siendo simulado (`DummyProvider`)**, no un modelo de lenguaje real
todavía — la página lo deja explícito.

Las 5 páginas tienen **diseño responsive**: cada una incluye el selector
**"Vista"** con 3 modos (**Automática**, **Amplia**, **Compacta**) en la
barra lateral. En "Resumen General" controla cuántas tarjetas se
muestran por fila (3 en Amplia, 2 en Automática, 1 apilada verticalmente
en Compacta); en "Mercado", "Indicadores", "Señales" y "Recomendaciones
de IA" controla si las métricas se muestran en columnas o apiladas. **El
modo de vista responsive es compartido entre las páginas del Dashboard
mediante una única clave centralizada de st.session_state**: elegir
"Compacta" en una página y navegar a otra conserva "Compacta", en vez de
resetear a un valor distinto. La elección se guarda solo en la sesión
del navegador (`st.session_state`), nunca en disco ni en `config.yaml`.

Las 6 páginas del Dashboard ya son funcionales — la identidad visual
definitiva de toda la aplicación (más allá de la paleta ya centralizada
en `theme.py`) todavía se completará más adelante. "Estado Técnico" es
funcional desde la Iteración 5.2 (estado de las 4 tablas SQLite).

El diseño responsive se validó mediante pruebas automatizadas (AppTest) y
revisión de código (sin anchos/altos fijos, sin tablas HTML, sin scroll
horizontal forzado), pero **todavía no se validó visualmente en un
navegador real** en ningún tamaño de pantalla — se recomienda hacerlo
antes de dar por cerrado el diseño responsive de estas cinco páginas.

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

✅ **Etapa 5 aprobada**: Dashboard de solo lectura (Streamlit) con 6
páginas funcionales (Resumen General, Mercado, Indicadores, Señales,
Recomendaciones de IA, Estado Técnico), construidas incrementalmente en
las Iteraciones 5.1-5.7 sobre las 4 tablas ya generadas por las Etapas
1-4, sin recalcular ni escribir ningún dato. Selector de vista
responsive (Automática/Amplia/Compacta) centralizado y compartido entre
las 5 páginas que lo usan (`layout.render_view_mode_selector()`). Ver
[docs/ARQUITECTURA_DASHBOARD.md](docs/ARQUITECTURA_DASHBOARD.md) para el
detalle completo de cada iteración.

🛠️ **Etapas 6.0-6.9 (implementación en curso)**: Paper Trading (compra/
venta simulada, sin dinero real, sin conexión a un exchange para
operar). 6.0 diseñó la arquitectura (auditada en 6.0.1); desde entonces
se implementó, con pruebas automatizadas en cada paso: **6.1** dominio
(`Order`, `Execution`, `Trade`, `Position`, `CashBalance`,
`PortfolioSnapshot`, `PnLSnapshot`, `RiskValidationResult` — sin
`OrderBook`, eliminado por redundante con `MarketTicker`); **6.2**
motores puros (`FillEngine`, `PositionEngine`, `PnLEngine`, `RiskEngine`,
solo MARKET/LONG); **6.3** persistencia SQLite propia (tablas
`paper_trading_*`, Decimal como TEXT, transacción atómica de fill);
**6.4** `PaperTradingService`, única capa que orquesta motores +
persistencia; **6.5** Composition Root (`src/paper_trading/
composition.py`) + `PaperTradingApplication` para someter una orden
manual, con `config.yaml -> paper_trading` (`enabled: false` por
defecto) e integración mínima en `main.py`; **6.6** página de Dashboard
"Paper Trading" **estrictamente de solo lectura** (saldo, patrimonio,
posiciones, órdenes, ejecuciones, trades, evolución del patrimonio/PnL
y auditoría de consistencia — sin ningún botón, formulario ni acción
que ejecute/cree/cancele una orden); **6.7** ciclo de vida explícito de
una orden MARKET con reservas reales de capital/cantidad
(`NEW → PENDING con reserva → FILLED/CANCELLED con liberación`, o
`NEW → REJECTED` sin reservar nada), mediante un nuevo motor puro
`ReservationEngine` (reserva/libera `CashBalance.reserved_balance` en
BUY y `Position.reserved_quantity` en SELL, guardado en 4 campos nuevos
del propio `Order`) y nuevas transacciones atómicas del repositorio
(`save_order_acceptance_transaction`/`save_order_cancellation_transaction`);
`submit_market_order`/`submit_manual_market_order` se conservan como
fachadas de compatibilidad; **6.8** agregó reconciliación y recuperación
de estado: `ReconciliationEngine` (motor puro) detecta -- nunca repara
por sí solo -- inconsistencias entre órdenes PENDING/reservas
agregadas/ejecuciones/trades/PnL, con 20 códigos estables y 4 niveles de
severidad; `ReconciliationService.inspect()` es de solo lectura,
`.repair()` corre en `dry_run=True` por defecto y solo corrige
`CashBalance.reserved_balance`/`Position.reserved_quantity` (recálculo
exacto desde las órdenes PENDING vigentes, nunca crea Execution/Trade ni
cambia un `OrderStatus`), con control optimista de concurrencia y una
tabla de auditoría inmutable (`paper_trading_reconciliation_audit`) que
registra tanto los dry-run como las reparaciones reales.
`build_paper_trading_context()` construye el servicio pero nunca lo
ejecuta al arrancar; una CLI administrativa nueva y separada
(`python -m src.paper_trading.reconciliation_cli inspect|repair`,
`--apply` obligatorio para escribir) es la única forma de invocarlo. El
Dashboard no cambia (sigue estrictamente de solo lectura, sin ningún
botón administrativo); **6.9** automatizó exclusivamente la *inspección*
periódica de reconciliación -- nunca la reparación, que sigue siendo
manual (Etapa 6.8): `InspectionComparator` (puro) compara la corrida
actual contra la última exitosa por `IssueIdentity` (código+entidad,
nunca por texto/timestamp), clasificando cada issue en nuevo/resuelto/
persistente, con subcategorías de severidad aumentada/disminuida y
cambio de valor; `AlertBuilder` (puro) construye alertas tipadas
(`NEW_ISSUE`/`RESOLVED_ISSUE`/`SEVERITY_INCREASED`/`SEVERITY_DECREASED`/
`VALUE_CHANGED`/`INSPECTION_FAILED`/`SYSTEM_RECOVERED`) con una
`deduplication_key` SHA-256 (nunca `hash()` nativo) que evita duplicar
la misma alerta tras un reinicio; `InspectionService` persiste cada
corrida + sus alertas en una única transacción atómica
(`paper_trading_inspection_runs`/`paper_trading_inspection_alerts`,
UNIQUE en `deduplication_key`); `AlertDeliveryService` entrega alertas
`PENDING` vía `logging` (`LoggingInspectionAlertSink`/
`NullInspectionAlertSink` para pruebas) con reintentos acotados
(`max_alert_delivery_attempts`, `FAILED` al agotarse, `DELIVERED` nunca
se reenvía); `InspectionJob` combina Clock/IdGenerator/ambos servicios
con un lock no reentrante en memoria (protege un solo proceso, no
multiproceso) para evitar solapamiento; ejecutable manualmente
(`python -m src.paper_trading.inspection_cli run|alerts|history`) o
periódicamente (`python -m src.paper_trading.inspection_scheduler`,
proceso independiente con su propio loop, sin la librería `schedule` de
`main.py`), gateado por `paper_trading.reconciliation_inspection.enabled`
(`false` por defecto, bloque opcional en `config.yaml`, independiente de
`paper_trading.enabled`). **Ninguna orden se ejecuta automáticamente
todavía**: sin Strategy Engine, sin señales ni IA ejecutando órdenes,
sin cambios en el Dashboard (sigue de solo lectura). Ver
[docs/ALCANCE_ETAPA_6.md](docs/ALCANCE_ETAPA_6.md) y
[docs/ARQUITECTURA_PAPER_TRADING.md](docs/ARQUITECTURA_PAPER_TRADING.md).
**Etapas 6.10-6.16.1**: sistema de notificaciones multicanal cerrado --
Logging/Telegram/Slack/Email/Webhook, sin placeholders restantes,
auditoría transversal y sanitización de excepciones inesperadas
completas. **Etapa 6.17**: caracterización y endurecimiento mínimo de
concurrencia SQLite (`SQLitePaperTradingRepository`): timeout explícito
y validado (`timeout_seconds`, mismo default de 5.0s ya vigente antes
de esta etapa), sin habilitar WAL (sin evidencia que lo justificara),
con pruebas reales de escritores/lectores concurrentes, atomicidad bajo
contención, reinicio e integridad. Ver
[docs/ARQUITECTURA_PAPER_TRADING.md §32](docs/ARQUITECTURA_PAPER_TRADING.md).
**Etapa 6.18**: CLI operativa `python -m src.paper_trading.portfolio_cli`
(`summary`/`balances`/`positions`/`orders`/`executions`/`trades`/
`snapshots`/`inspections`/`alerts`/`deliveries`/`reconciliation-audits`,
formatos `table`/`json`) -- **estrictamente de solo lectura**: abre
SQLite en modo real `mode=ro`, nunca crea la base ni escribe nada. Ver
[docs/ARQUITECTURA_PAPER_TRADING.md §33](docs/ARQUITECTURA_PAPER_TRADING.md).
**Etapa 6.18.1**: `--database-path`/`--format` ahora se aceptan tanto
antes como después del subcomando (ambas formas son equivalentes):
`portfolio_cli --database-path db.sqlite --format json summary` y
`portfolio_cli summary --database-path db.sqlite --format json`.
**Etapa 6.19**: CLI administrativa `python -m src.paper_trading.order_cli`
(`accept`/`fill`/`cancel`/`submit`) para operar manualmente órdenes
simuladas de Paper Trading desde terminal -- expone tal cual los
cuatro casos de uso ya existentes de `PaperTradingApplication` (Etapas
6.5/6.7), sin duplicar ninguna regla de negocio. Escribe exclusivamente
en la base de Paper Trading simulada configurada oficialmente
(`config/config.yaml` + `.env`, sin `--database-path`); `--confirm` es
obligatorio para autorizar cualquier escritura (real, aunque siempre
simulada) -- sin él, no se construye ningún contexto ni se ejecuta
ninguna operación. Solo MARKET, solo posiciones LONG. Ver
[docs/ARQUITECTURA_PAPER_TRADING.md §34](docs/ARQUITECTURA_PAPER_TRADING.md).
PostgreSQL (`postgres_repository.py`) sigue pendiente, como fase futura
independiente -- el proyecto no se declara listo para producción ni
para Live Trading.
**Etapa 6.19.1**: `order_cli.py` ahora comprueba
`paper_trading.enabled` inmediatamente después de cargar la
configuración y **antes** de inicializar cualquier repositorio -- con
`enabled: false`, los cuatro subcomandos devuelven el código 4 sin
crear ni modificar ninguna base SQLite (ni la de mercado ni la de
Paper Trading), sin importar si `--order-id` existe. Ver
[docs/ARQUITECTURA_PAPER_TRADING.md §34.12](docs/ARQUITECTURA_PAPER_TRADING.md).
**Etapa 6.20**: CLI administrativa
`python -m src.paper_trading.backup_cli` (`backup`/`verify`/`restore`)
para la base SQLite de Paper Trading, vía `sqlite3.Connection.backup()`
(nunca copia de bytes cruda) y publicación atómica (`os.replace()`
sobre un temporal ya verificado). Ejemplos:
`backup_cli backup --output backups/paper_trading_2026-07-27.sqlite`,
`backup_cli verify --backup-path backups/paper_trading_2026-07-27.sqlite`,
`backup_cli restore --backup-path backups/paper_trading_2026-07-27.sqlite --confirm`
(`--confirm` es obligatorio para `restore`, y crea un backup previo por
defecto). No sustituye un backup externo real, no incluye cifrado ni
subida a la nube, no programa backups automáticos, y no está diseñado
para múltiples escritores distribuidos. Ver
[docs/ARQUITECTURA_PAPER_TRADING.md §35](docs/ARQUITECTURA_PAPER_TRADING.md).
**Etapa 6.20.1**: los backups se publican únicamente si integridad y
schema son válidos, y `restore` reporta error si la base final no
supera la verificación posterior al reemplazo (`os.replace()`). Ver
[docs/ARQUITECTURA_PAPER_TRADING.md §35.14](docs/ARQUITECTURA_PAPER_TRADING.md).

Pendiente: aprobación formal de la Etapa 4 (todavía en revisión) antes
de conectar un proveedor de IA real; migración a PostgreSQL real para
Paper Trading (`postgres_repository.py` sigue siendo un stub
preparado, sin implementar). El proyecto sigue en desarrollo activo --
no se considera terminado.
