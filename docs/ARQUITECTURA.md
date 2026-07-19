# Arquitectura del proyecto (desde la Etapa 1.5, ampliada en las Etapas 2, 3 y 4)

Este documento explica cómo está organizado el código a partir de la Etapa
1.5 (refactorización y preparación de arquitectura), la Etapa 2 (motor de
indicadores técnicos), la Etapa 3 (motor de señales) y la Etapa 4 (motor de
decisión de IA), y por qué se organizó así. El objetivo de esta
arquitectura es que las etapas futuras (múltiples exchanges, dashboard,
Telegram, paper trading, trading automatizado) se puedan agregar **sumando
módulos nuevos**, sin tener que reescribir los ya existentes.

## Principio general: interfaces primero, implementaciones después

En vez de que el resto del proyecto dependa directamente de "Binance" o de
"SQLite", depende de contratos (interfaces):

- `ExchangeClient` (`src/market/base.py`): "algo que sabe consultar precios
  de un exchange".
- `MarketDataRepository` (`src/database/base.py`): "algo que sabe guardar y
  leer datos crudos de mercado".
- `IndicatorRepository` (`src/database/base.py`, Etapa 2): "algo que sabe
  guardar y leer indicadores técnicos calculados".
- `SignalRepository` (`src/signals/base.py`, Etapa 3): "algo que sabe
  guardar y leer señales estructuradas".
- `AIRepository` (`src/ai/repository.py`, Etapa 4): "algo que sabe guardar
  y leer recomendaciones de IA".
- `AIProvider` (`src/ai/base.py`, Etapa 4): "algo que sabe generar una
  recomendación estructurada a partir de un prompt". A diferencia de las
  interfaces anteriores (que abstraen almacenamiento), esta abstrae el
  "cerebro" que interpreta la señal: hoy es `DummyProvider`; mañana podría
  ser `OpenAIProvider` o `ClaudeProvider`, sin tocar `DecisionEngine`.

Binance, SQLite y DummyProvider son, hoy, la única implementación de cada
interfaz correspondiente. Agregar Bybit, Coinbase, Kraken, PostgreSQL,
OpenAI o Anthropic en el futuro significa crear una nueva clase que cumpla
el mismo contrato, sin tocar el resto del proyecto.

## Estructura de carpetas

```
Crypto_AI_Operation_Center/
├── .env.example          # Plantilla de credenciales (Binance, OpenAI, Anthropic, Telegram, CoinGecko, NewsAPI, DB)
├── config/
│   └── config.yaml       # Configuración de comportamiento (monedas, intervalo, límites, rutas, indicadores)
├── data/
│   └── crypto_data.db    # Base de datos SQLite (se genera sola; tablas market_data + market_indicators)
├── docs/
│   ├── ALCANCE_ETAPA_1.md
│   ├── ALCANCE_ETAPA_1_5.md
│   ├── ALCANCE_ETAPA_2.md
│   ├── ALCANCE_ETAPA_3.md
│   └── ARQUITECTURA.md   # Este documento
├── logs/
│   └── app.log            # Log de actividad y errores (se genera solo)
├── tests/                 # Pruebas automatizadas (pytest)
├── src/
│   ├── main.py             # Punto de entrada (Composition Root): SOLO arma piezas y coordina
│   ├── market/              # Clientes de exchanges (hoy: Binance)
│   │   ├── base.py          # Interfaz ExchangeClient + ExchangeClientError
│   │   └── binance.py       # BinanceExchangeClient (implementa ExchangeClient)
│   ├── database/             # Repositorios de mercado e indicadores
│   │   ├── base.py            # Interfaces MarketDataRepository e IndicatorRepository
│   │   ├── sqlite_repository.py             # market_data (SQLite, en uso)
│   │   ├── postgres_repository.py           # market_data (stub, NO implementado)
│   │   ├── sqlite_indicator_repository.py   # market_indicators (SQLite, en uso)
│   │   └── postgres_indicator_repository.py # market_indicators (stub, NO implementado)
│   ├── services/              # Lógica de negocio de mercado e indicadores
│   │   ├── market_data_service.py  # Orquesta exchange + repositorio (el ciclo de consulta)
│   │   ├── indicator_engine.py     # Cálculo puro de indicadores (SMA, EMA, RSI, MACD, Bollinger, VWAP)
│   │   └── indicator_service.py    # Orquesta historial + motor + repositorio de indicadores
│   ├── signals/                 # Motor de señales (Etapa 3)
│   │   ├── enums.py               # Direction, TrendStrength, ConfidenceLevel, SignalType
│   │   ├── rule_result.py           # Modelo RuleResult (direction, strength, reason, label)
│   │   ├── base.py                    # Interfaz SignalRepository
│   │   ├── sqlite_repository.py         # market_signals (SQLite, en uso)
│   │   ├── postgres_repository.py        # market_signals (stub, NO implementado)
│   │   ├── engine.py                      # SignalEngine (cálculo puro, sin I/O)
│   │   ├── service.py                      # SignalService (orquesta indicadores + precio + motor + repositorio)
│   │   ├── aggregator.py                    # Combina 5 RuleResult en score/confidence/trend_strength/signal_type
│   │   └── rules/                            # Reglas independientes (Single Responsibility)
│   │       ├── trend_rule.py                   # TrendRule -> RuleResult
│   │       ├── ema_rule.py                      # EMARule -> RuleResult
│   │       ├── macd_rule.py                      # MACDRule -> RuleResult
│   │       ├── rsi_rule.py                        # RSIRule -> RuleResult
│   │       └── bollinger_rule.py                   # BollingerRule -> RuleResult
│   ├── ai/                      # Motor de decisión de IA (Etapa 4)
│   │   ├── context.py              # Modelo MarketContext + build_market_context()
│   │   ├── recommendation.py         # RecommendationAction, RiskLevel, AIRecommendation
│   │   ├── explanation.py             # AIExplanation + build_explanation()
│   │   ├── models.py                    # Reexporta los 3 modelos anteriores
│   │   ├── base.py                        # Interfaz AIProvider + AIProviderResponse
│   │   ├── providers/                       # Implementaciones de AIProvider
│   │   │   ├── dummy_provider.py               # DummyProvider (en uso, sin IA real)
│   │   │   ├── openai_provider.py               # OpenAIProvider (stub, NO implementado)
│   │   │   └── claude_provider.py               # ClaudeProvider (stub, NO implementado)
│   │   ├── prompt_builder.py                # PromptBuilder (MarketContext -> texto)
│   │   ├── decision_engine.py                 # DecisionEngine (cálculo puro, sin I/O)
│   │   ├── repository.py                        # Interfaz AIRepository
│   │   ├── sqlite_repository.py                    # ai_recommendations (SQLite, en uso)
│   │   └── service.py                                # AIService (orquesta señal + motor + repositorio)
│   ├── models/                 # Modelos de datos (Pydantic)
│   │   ├── market_data.py       # MarketTicker
│   │   ├── indicator_data.py    # IndicatorSnapshot
│   │   └── signal_data.py       # SignalSnapshot
│   ├── utils/                   # Utilidades transversales
│   │   ├── config.py              # Settings: lee config.yaml + .env
│   │   └── logger.py              # Configuración de logging
│   ├── dashboard/                 # Reservado para el dashboard (Etapa futura). Vacío.
│   ├── alerts/                    # Reservado para evaluación de alertas (Etapa futura). Vacío.
│   └── telegram/                  # Reservado para notificaciones Telegram (Etapa futura). Vacío.
```

Nota de organización: los repositorios de `market_data`/`market_indicators`
viven bajo `src/database/` (organización por capa técnica), mientras que
todo lo de señales (repositorio incluido) vive bajo `src/signals/`
(organización por funcionalidad). Es una decisión explícita para esta
etapa: agrupar todo el módulo de señales en un solo lugar, dado que es un
conjunto de piezas (reglas + agregador + motor + servicio + repositorio)
que solo tiene sentido en conjunto. Ambos estilos conviven porque respetan
el mismo principio de fondo: interfaces primero, sin dependencias
invertidas entre capas.

## Flujo de un ciclo (`python -m src.main`)

1. `main.py` llama a `load_settings()` (`src/utils/config.py`), que combina
   `config/config.yaml` (comportamiento) con `.env` (credenciales, si
   existe).
2. `main.py` configura logging (`src/utils/logger.py`).
3. `main.py` (`build_services()`) construye un `BinanceExchangeClient`, los
   4 repositorios SQLite (`market_data`, `market_indicators`,
   `market_signals`, `ai_recommendations`) y el `AIProvider` activo
   (`_build_ai_provider()`, según `settings.ai_engine.provider`), y con
   ellos arma `MarketDataService`, `IndicatorService`, `SignalService` y
   `AIService`. Esta construcción es el único lugar del proyecto que sabe
   que "hoy" el exchange es Binance, la base de datos es SQLite y el
   proveedor de IA activo es `DummyProvider`.
4. `main.py` llama a `run_full_cycle()` una vez, y luego programa que se
   repita cada `interval_minutes` usando la librería `schedule`.
5. `run_full_cycle()` ejecuta, en orden:
   a. `MarketDataService.run_cycle()`: pide los tickers al `ExchangeClient`,
      los valida (objetos `MarketTicker` gracias a Pydantic), los guarda en
      `market_data`, y registra actividad en el log.
   b. `IndicatorService.run_cycle()`: para cada símbolo, lee su historial de
      precios ya actualizado (`MarketDataRepository.fetch_by_symbol`), le
      calcula los indicadores disponibles (`IndicatorEngine`), y guarda el
      resultado en `market_indicators` (`IndicatorRepository`).
   c. `SignalService.run_cycle()`: para cada símbolo, lee el último
      indicador calculado (`IndicatorRepository.fetch_latest`) y el precio
      más reciente (`MarketDataRepository.fetch_by_symbol(..., limit=1)`),
      genera una señal (`SignalEngine`), y la guarda en `market_signals`
      (`SignalRepository`).
   d. `AIService.run_cycle()` (si `settings.ai_engine.enabled` es `true`):
      para cada símbolo, lee la última señal (`SignalRepository.fetch_latest`)
      y su historial reciente, arma un `MarketContext`, ejecuta
      `DecisionEngine` (que arma el prompt y llama al `AIProvider` activo),
      y guarda la `AIRecommendation` resultante en `ai_recommendations`
      (`AIRepository`).

`main.py` no sabe cómo se consulta Binance, ni cómo se guarda en SQLite, ni
cómo se calcula un RSI, una señal o una recomendación de IA: solo sabe que
existen esas piezas y las conecta. Esa es la definición de "coordinar" en
este proyecto.

## Modelos de datos (Pydantic)

`MarketTicker` (`src/models/market_data.py`) reemplaza los diccionarios
sueltos de la Etapa 1. Sus campos son: `exchange`, `symbol`, `price`,
`volume_24h`, `price_change_percent_24h` y `queried_at`. Ventajas concretas:

- Si Binance (o cualquier exchange futuro) devuelve un dato mal formado
  (ej. un precio que no es un número), Pydantic lo detecta inmediatamente
  con un error claro, en el punto exacto donde ocurre.
- El resto del código usa `ticker.price` en vez de `ticker["price"]`,
  evitando errores de tipeo en las claves.
- El campo `exchange` identifica de qué exchange vino cada dato. Hoy su
  valor por defecto es `"Binance"` (el único exchange implementado); cada
  clase de `src/market/` declara su propio `exchange_name` (ver
  `ExchangeClient` en `src/market/base.py`) y lo usa al construir sus
  `MarketTicker`, para que un futuro Bybit/Coinbase/Kraken quede
  correctamente identificado en vez de asumirse como Binance.

`SQLiteMarketDataRepository` guarda y lee el campo `exchange` como una
columna más de la tabla `market_data`. Si encuentra una base de datos
creada antes de que existiera esta columna, la agrega automáticamente
(`ALTER TABLE ... ADD COLUMN`) la primera vez que se llama a `init()`, sin
perder los registros ya guardados (a esos registros históricos se les
asigna `"Binance"`, que es el único exchange que existía hasta ahora).

## Motor de indicadores técnicos (Etapa 2)

`IndicatorEngine` (`src/services/indicator_engine.py`) es lógica de negocio
pura: recibe el historial de precios de un símbolo (lista de `MarketTicker`,
ordenada del más antiguo al más reciente) y `IndicatorSettings`, y devuelve
un `IndicatorSnapshot` (`src/models/indicator_data.py`) con:

- `sma`, `ema_fast`, `ema_medium`, `ema_slow`
- `rsi`
- `macd_line`, `macd_signal`, `macd_histogram`
- `bollinger_upper`, `bollinger_middle`, `bollinger_lower`
- `vwap`

Todos los campos son opcionales: mientras no haya suficiente historial para
un indicador puntual (ej. `ema_slow` necesita al menos 200 lecturas), ese
campo queda en `None` en vez de forzar un valor incorrecto. El motor no sabe
nada de Binance, SQLite, ni de otros exchanges, por lo que se prueba
directamente con listas de precios de prueba (ver `tests/test_indicator_engine.py`).

`IndicatorService` (`src/services/indicator_service.py`) es quien conecta el
motor con el resto del sistema: por cada símbolo, pide su historial al
`MarketDataRepository`, se lo pasa al `IndicatorEngine`, y guarda el
resultado con el `IndicatorRepository`.

### Tabla `market_indicators`, separada de `market_data`

`market_data` (Etapa 1/1.5) sigue conteniendo únicamente datos crudos:
precio, volumen, variación, fecha. No se le agregó ninguna columna en esta
etapa. Los indicadores calculados se guardan en una tabla nueva e
independiente, `market_indicators` (`SQLiteIndicatorRepository`). Esta
separación permite:

- Recalcular indicadores históricos si cambian los periodos de
  `config.yaml`, sin volver a consultar Binance.
- Migrar cada tabla a PostgreSQL de forma independiente en el futuro.
- Que un futuro motor de señales o de IA lea `market_indicators`
  directamente, sin tener que recalcular nada.

### Limitación conocida: ATR y ADX

`config.yaml` incluye los periodos `atr` y `adx`, y `IndicatorSettings` los
valida, pero **el motor no los calcula todavía**. Ambos requieren datos de
máximo/mínimo por vela (OHLC), que el endpoint que usa este proyecto
(`/api/v3/ticker/24hr`) no provee por intervalo de 5 minutos (solo da el
máximo/mínimo acumulado de las últimas 24 horas). Implementarlos
correctamente requeriría consultar el endpoint de velas de Binance
(`/api/v3/klines`), una fuente de datos adicional fuera del alcance de esta
etapa. Ver [ALCANCE_ETAPA_2.md](ALCANCE_ETAPA_2.md).

### Aproximación del VWAP

El VWAP se calcula ponderando el precio de cada lectura por su
`volume_24h` (volumen acumulado de 24h que reporta Binance), dentro de una
ventana de `sma` lecturas. No es el VWAP exacto de un exchange (que usa el
volumen negociado por intervalo), pero es una aproximación razonable con
los datos disponibles hoy. Está documentado en el código.

## Motor de señales (Etapa 3)

Transforma los indicadores ya calculados en una señal estructurada, **sin
usar inteligencia artificial**: solo reglas determinísticas y configurables.

**Nota de revisión**: la arquitectura se ajustó dos veces antes de cerrar
esta etapa. Primero, cada regla pasó de devolver un Enum propio suelto
(ej. `TrendResult.STRONG_BULLISH`) a devolver un modelo común `RuleResult`
(`direction`, `strength`, `reason`). Después, el campo `label` de
`RuleResult` (que hasta entonces era un `str` libre) pasó a ser también un
Enum tipado por regla (`TrendLabel`, `EMALabel`, etc.), y se agregó la
fuerza individual de cada regla (`*_rule_strength`) a `SignalSnapshot`. Ver
[ALCANCE_ETAPA_3.md](ALCANCE_ETAPA_3.md) para el detalle de cada revisión.

### Diagrama de flujo completo

```
MarketData (Etapa 1/1.5)
    │  MarketTicker: exchange, symbol, price, volume_24h,
    │  price_change_percent_24h, queried_at → tabla market_data
    ▼
Indicators (Etapa 2)
    │  IndicatorEngine calcula sobre el historial: sma, ema_fast/medium/slow,
    │  rsi, macd_line/signal/histogram, bollinger_upper/middle/lower, vwap
    │  → IndicatorSnapshot → tabla market_indicators
    ▼
Rules (Etapa 3 — 5 componentes independientes, sin conocerse entre sí)
    │  TrendRule, EMARule, MACDRule, RSIRule, BollingerRule
    │  cada una lee solo los indicadores que necesita (BollingerRule
    │  además lee el precio actual) y devuelve RuleResult[XLabel]
    │  (direction, strength 0-1, reason, label tipado)
    ▼
Aggregator (src/signals/aggregator.py)
    │  combina los 5 RuleResult:
    │    score       = 50 + (Σ peso_i·signo(dirección_i)·strength_i / Σ peso_i)·50
    │    confidence  = max(cuenta Bullish, Neutral, Bearish) / 5 × 100
    │    trend_strength = derivado del label de TrendRule
    │    signal_type = clasifica el score final (Bullish/Neutral/Bearish)
    ▼
SignalSnapshot (src/models/signal_data.py)
    │  resultado final + reason y rule_strength de cada regla
    │  (detalle completo, listo para explicar la señal sin recalcular nada)
    ▼
SQLite (SQLiteSignalRepository)
    │  persistido en la tabla market_signals (23 columnas, migración
    │  automática e idempotente desde esquemas anteriores)
    ▼
IA (Etapa 4 — implementada, en revisión)
    │  AIService lee la última señal (+ historial reciente) y la interpreta
    │  con el AI Decision Engine (ver diagrama completo más abajo), sin
    │  recalcular ningún indicador ni volver a ejecutar ninguna regla.
    ▼
Dashboard / Paper Trading / Trading Automático (Etapas futuras, NO implementadas)
```

### Diagrama de flujo completo (con la Etapa 4)

```
MarketData
    ↓
IndicatorEngine
    ↓
SignalEngine
    ↓
SignalSnapshot
    ↓
AIService
    ↓
MarketContext
    ↓
PromptBuilder
    ↓
AIProvider
    ↓
DecisionEngine
    ↓
AIRecommendation
    ↓
AIRepository
    ↓
ai_recommendations
```

**La IA interpreta las señales, pero no sustituye al motor determinístico**
(`SignalEngine`): `AIService` solo lee una señal ya calculada por las
reglas de la Etapa 3, nunca recalcula ninguna regla ni ningún indicador.

Con el primer eslabón (de dónde vienen los datos) y los siguientes
(etapas futuras, todavía sin implementar):

```
Binance -> MarketData -> ... -> ai_recommendations
  -> Dashboard (Etapa futura, NO implementada)
  -> Paper Trading (Etapa futura, NO implementada)
  -> Trading Automático (Etapa futura, NO implementada)
```

### Enums comunes (`src/signals/enums.py`)

Centralizan el vocabulario de todo el módulo, para no tener strings sueltos
repartidos por el código:

- **`Direction`**: `Bullish` / `Neutral` / `Bearish`. Inclinación de **una
  regla individual** (campo `RuleResult.direction`).
- **`TrendStrength`**: `Weak` / `Medium` / `Strong`. Fuerza de la tendencia
  general, derivada de `TrendRule`.
- **`ConfidenceLevel`**: `Very Low` / `Low` / `Medium` / `High` / `Very
  High`. Nivel de acuerdo entre las 5 reglas.
- **`SignalType`**: `Bullish` / `Neutral` / `Bearish`. Veredicto de **la
  señal agregada final** (el score ya ponderado), distinto de `Direction`
  aunque comparta los mismos 3 valores de texto — uno es por regla, el
  otro es el resultado combinado de las 5.
- **Enums de `label`** (categoría detallada de cada regla, ver más abajo):
  `TrendLabel` (5 valores), `EMALabel`, `MACDLabel`, `RSILabel` y
  `BollingerLabel` (3 valores cada uno).

### `RuleResult` (`src/signals/rule_result.py`) — genérico y tipado

Todas las reglas devuelven un `RuleResult`, nunca un string ni un Enum
propio suelto directamente:

```python
RuleResult[TrendLabel](
    direction=Direction.BULLISH,
    strength=0.82,
    reason="EMA rápida está +4.76% sobre la EMA media.",
    label=TrendLabel.BULLISH,
)
```

- **`direction`**: inclinación de la regla (`Direction`).
- **`strength`**: magnitud de la señal, normalizada de 0.0 a 1.0
  (validado por Pydantic con `Field(ge=0.0, le=1.0)`: cualquier valor fuera
  de ese rango se rechaza al construir el objeto). Cada regla la calcula
  distinto, saturando en 1.0 en su propio umbral "máximo" (ver tabla más
  abajo), sin necesitar configuración adicional.
- **`reason`**: explicación en texto de por qué se llegó a ese resultado
  (ver "Preparación para IA" más abajo).
- **`label`**: categoría específica y más detallada que `direction` (ej.
  "Strong Bullish", "Oversold", "Bullish Cross", "Upper Band"). Es lo que
  se guarda en los campos `trend`/`ema_signal`/`macd_signal`/`rsi_signal`/
  `bollinger_signal` de `SignalSnapshot`.

**Por qué es genérico (`RuleResult[TrendLabel]`, `RuleResult[EMALabel]`,
etc.)**: varios valores de texto se repiten entre los 5 enums de label
(ej. "Neutral" existe en los 5; "Bullish"/"Bearish" existen en `TrendLabel`
y `EMALabel`). Un `Union[TrendLabel, EMALabel, ...]` simple sería ambiguo
en esos casos. Al parametrizar `RuleResult` por regla, Pydantic valida y
**normaliza** el `label` al tipo exacto solicitado: si por error se pasara
un `EMALabel.BULLISH` a un `RuleResult[TrendLabel]`, el resultado queda
tipado como `TrendLabel.BULLISH` (nunca como `EMALabel`), y un valor que no
exista en absoluto en el enum solicitado (ej. `RSILabel.OVERSOLD` dentro de
`RuleResult[BollingerLabel]`) se rechaza con `ValidationError`. Esto se
verificó explícitamente (`tests/test_signals_rule_result.py`).

### Reglas independientes (`src/signals/rules/`)

Cada regla es una clase con una sola responsabilidad, que recibe
únicamente los indicadores que necesita y devuelve un `RuleResult[XLabel]`.
Ninguna regla conoce a las demás ni al agregador (verificado: ningún
archivo de `src/signals/rules/` importa a otro):

| Regla | Entradas | Enum de `label` | Cómo se calcula `strength` |
|---|---|---|---|
| `TrendRule` | `ema_fast`, `ema_medium`, `ema_slow` | `TrendLabel` (5 valores) | `min(\|diff%\| / strong_diff_pct, 1)` |
| `EMARule` | `ema_fast`, `ema_medium` | `EMALabel` (3 valores) | `min(\|diff%\| / (neutral_band_pct×10), 1)` |
| `MACDRule` | `macd_line`, `macd_signal` | `MACDLabel` (3 valores) | `min(\|línea−señal\| / (\|línea\|+\|señal\|), 1)` |
| `RSIRule` | `rsi` | `RSILabel` (3 valores) | distancia al umbral, normalizada contra el extremo (0 o 100) |
| `BollingerRule` | precio actual, `bollinger_upper`, `bollinger_lower` | `BollingerLabel` (3 valores) | qué tan adentro de la zona de proximidad está el precio |

Todas, salvo `MACDRule` (que solo compara dos valores ya calculados sin
umbrales propios), reciben sus umbrales desde `config.yaml -> signals.rules`.

Agregar una regla nueva (Open/Closed Principle) significa crear un archivo
nuevo en `src/signals/rules/` con su propio enum de `label` en
`src/signals/enums.py`, que devuelva `RuleResult[SuLabel]`, y conectarlo en
`SignalEngine` y en el agregador, sin modificar ninguna regla existente.

### Agregador (`src/signals/aggregator.py`)

Es el único lugar que sabe combinar las 5 reglas. Su docstring documenta
explícitamente 4 conceptos que **no deben confundirse**:

| Concepto | Alcance | Qué responde |
|---|---|---|
| `strength` (en `RuleResult`) | Por regla individual | "¿Qué tan fuerte es la señal de ESTA regla?" |
| `score` (0-100) | Señal agregada, ponderada | "¿Qué tan alcista/bajista es la señal en conjunto, y con qué convicción?" |
| `confidence` | Señal agregada, sin ponderar | "¿Qué tan de acuerdo están las 5 reglas entre sí?" |
| `trend_strength` | Solo de `TrendRule` | "¿Qué tan fuerte es la tendencia principal?" (no resume las otras 4 reglas) |

Es posible tener un `score` alto con `confidence` bajo: por ejemplo, una
sola regla con mucho peso y fuerza máxima puede dominar el score aunque las
otras 4 apunten en sentido contrario — el score refleja a la regla
dominante, pero la confianza es baja porque no hay consenso.

**Cálculo exacto de `score`**:
```
score = 50 + (Σ peso_i × signo(dirección_i) × strength_i / Σ peso_i) × 50
```
donde `signo(Bullish)=+1`, `signo(Neutral)=0`, `signo(Bearish)=-1`, y los
pesos vienen de `config.yaml -> signals.weights` (`trend`, `ema`, `macd`,
`rsi`, `bollinger`). Los pesos no necesitan sumar 100: el agregador siempre
normaliza por la suma total (verificado en
`test_weights_are_normalized_even_if_they_dont_sum_to_100`).

**Cálculo exacto de `confidence`** (determinístico, ver más abajo):
```
mayoría = max(cuenta(Bullish), cuenta(Neutral), cuenta(Bearish))
confidence_score = mayoría / 5 × 100
```
clasificado luego según `config.yaml -> signals.confidence`.

**`trend_strength`**: se deriva directamente del `RuleResult` de
`TrendRule` (su `label` es `STRONG_BULLISH`/`STRONG_BEARISH` → Strong;
dirección no neutral → Medium; neutral → Weak).

**`signal_type`**: clasifica el `score` final (ya ponderado) en
Bullish/Neutral/Bearish, usando `config.yaml -> signals.score`
(`bullish`/`bearish` como límites; `neutral` es solo referencia
informativa). Es el veredicto general, no el de una regla individual (eso
es `direction`).

#### Determinismo de `confidence` y comportamiento en empates

`confidence` **no necesita saber CUÁL** dirección es mayoritaria, solo
**CUÁNTAS** reglas comparten la más frecuente. Por eso, un empate entre dos
o tres inclinaciones (ej. 2 reglas alcistas y 2 bajistas, con 1 neutral) no
es ambiguo: el tamaño del grupo más grande es igual (2 en ese ejemplo) sin
importar cuál de los grupos empatados se mire primero.

La implementación calcula `directions.count(BULLISH)`,
`directions.count(NEUTRAL)` y `directions.count(BEARISH)` por separado (no
usa `collections.Counter`), y aplica `max()` sobre esos 3 números enteros.
Esto es determinístico por construcción: no depende del orden de un
diccionario ni del orden en que llegan las reglas. Se probaron
explícitamente los 5 casos pedidos (`tests/test_signals_aggregator.py`):

| Caso | Direcciones | % acuerdo | Confidence |
|---|---|---|---|
| 5 alineadas | 5 Bullish | 100% | Very High |
| 4 alineadas + 1 neutral | 4 Bullish, 1 Neutral | 80% | High |
| 3 vs 2 | 3 Bullish, 2 Bearish | 60% | Medium |
| Empate | 2 Bullish, 2 Bearish, 1 Neutral | 40% | Low |
| Todas neutrales | 5 Neutral | 100% | Very High |

### `SignalEngine` y `SignalService`

`SignalEngine` (`src/signals/engine.py`) es lógica de negocio pura (sin
I/O), igual en espíritu que `IndicatorEngine`: recibe un `IndicatorSnapshot`
y el precio actual, ejecuta las 5 reglas + el agregador, y devuelve un
`SignalSnapshot` con el detalle completo (incluyendo el `reason` y la
`strength` de cada regla). No modifica ni conoce `IndicatorEngine`,
`IndicatorService` ni `MarketDataService` — son módulos separados que
`main.py` conecta.

`SignalService` (`src/signals/service.py`) es quien conecta el motor con el
resto del sistema: lee el último `IndicatorSnapshot` (`IndicatorRepository`),
lee el precio más reciente (`MarketDataRepository.fetch_by_symbol(...,
limit=1)`), llama a `SignalEngine.calculate()`, y guarda el resultado con
`SignalRepository`. Al loguear, usa `.value` explícitamente sobre cada
campo Enum (`signal.trend.value`, no `signal.trend`), para garantizar un
log legible ("Bullish") sin depender de cómo `Enum.__str__`/`__format__` se
comporte según la versión de Python.

### Tabla `market_signals`, separada de `market_data` y `market_indicators`

`SQLiteSignalRepository` crea y usa una tabla independiente,
`market_signals`, con 23 columnas:

```
id, exchange, symbol,
trend, trend_strength, ema_signal, macd_signal, rsi_signal, bollinger_signal,
trend_reason, ema_reason, macd_reason, rsi_reason, bollinger_reason,
trend_rule_strength, ema_rule_strength, macd_rule_strength,
rsi_rule_strength, bollinger_rule_strength,
score, confidence, signal_type, generated_at
```

Ni `market_data` ni `market_indicators` se modifican en esta etapa.

Los campos de categoría de `SignalSnapshot` (`trend`, `ema_signal`, etc.,
`confidence`, `signal_type`) son **Enums**, no `str` sueltos: Pydantic los
valida al construir el modelo, y `SQLiteSignalRepository` los serializa
explícitamente a texto (`.value`) al guardarlos (columnas `TEXT`),
reconstruyéndolos como Enum automáticamente al leerlos de vuelta (Pydantic
coerciona el texto plano al Enum del campo).

**Migración automática, idempotente**: si `init()` encuentra una base de
datos creada con una versión anterior de `market_signals` (sin las
columnas `*_reason`/`signal_type`, sin las `*_rule_strength`, o sin
ninguna de las dos ampliaciones), agrega las columnas faltantes
(`ALTER TABLE ... ADD COLUMN`) con valores por defecto (`''` para
`*_reason`, `'Neutral'` para `signal_type`, `0.0` para `*_rule_strength`),
sin perder ni alterar ningún registro existente. Se puede llamar
`init()` cualquier cantidad de veces sin error (verificado con 3 llamadas
consecutivas en `tests/test_signals_sqlite_repository.py`).

### Preparación para IA (Etapa 4)

Cada `SignalSnapshot` guarda, además del resultado final:
- el `reason` de cada una de las 5 reglas (para "¿por qué apareció esta señal?");
- la `strength` individual de cada regla (para "¿qué tan fuerte fue cada componente?");
- el `label` detallado de cada regla (para "¿qué regla cambió?", comparando
  contra el historial en `market_signals` con `fetch_history`);
- el `signal_type` (veredicto general).

Esto permite que una futura IA (Etapa 4) responda esas preguntas leyendo
directamente `market_signals`, **sin tener que recalcular ningún indicador
ni volver a ejecutar ninguna regla**.

### Ejemplo completo de `SignalSnapshot`

```python
SignalSnapshot(
    exchange="Binance", symbol="BTCUSDT",
    trend=TrendLabel.STRONG_BULLISH, trend_strength=TrendStrength.STRONG,
    ema_signal=EMALabel.BULLISH, macd_signal=MACDLabel.BULLISH_CROSS,
    rsi_signal=RSILabel.OVERBOUGHT, bollinger_signal=BollingerLabel.UPPER_BAND,
    trend_reason="EMA rápida +10.00% sobre la EMA lenta, con las 3 EMA alineadas al alza.",
    ema_reason="EMA rápida está +4.76% sobre la EMA media.",
    macd_reason="MACD (1.5000) por encima de su línea de señal (1.0000).",
    rsi_reason="RSI en 75.00, por encima del umbral de sobrecompra (70).",
    bollinger_reason="Precio (109.0000) cerca o sobre la banda superior (110.0000).",
    trend_rule_strength=1.0, ema_rule_strength=1.0, macd_rule_strength=0.2,
    rsi_rule_strength=0.1667, bollinger_rule_strength=0.5,
    score=83.25, confidence=ConfidenceLevel.VERY_HIGH, signal_type=SignalType.BULLISH,
    generated_at=datetime.now(timezone.utc),
)
```

### Límites actuales del motor de señales

- **ATR y ADX no alimentan ninguna regla** (siguen sin calcularse desde la
  Etapa 2; ver más abajo).
- **`MACDRule` no detecta el instante exacto de un cruce**: refleja la
  relación *actual* entre `macd_line` y `macd_signal`, no un evento
  detectado en ese ciclo. Detectar el cruce real requeriría comparar
  contra el `IndicatorSnapshot` anterior (posible con
  `IndicatorRepository.fetch_history(limit=2)`, no implementado aún).
- **`RSIRule` usa la interpretación de seguimiento de tendencia** (no
  contrarian): "Overbought" es alcista, "Oversold" es bajista.
- **El factor de normalización de `strength` en `EMARule`** (10× la banda
  neutral) es una elección de diseño razonable, no un valor pedido
  explícitamente.
- **Los `*_reason` no se validan como "no vacíos" a nivel de modelo**: las
  5 reglas actuales siempre producen un `reason` no vacío para señales
  nuevas (verificado en cada prueba de regla), pero el modelo permite
  leer registros migrados con `reason=''` (valor por defecto histórico),
  para no romper la lectura de datos ya guardados.
- **`SignalType` se agregó como campo adicional de `SignalSnapshot`** (más
  allá del mínimo pedido originalmente) para darle un uso real al enum,
  reutilizando los umbrales de `signals.score` que antes solo servían
  como puntaje fijo por regla.

Ver más detalle y justificación en [ALCANCE_ETAPA_3.md](ALCANCE_ETAPA_3.md).

## Motor de decisión de IA (Etapa 4)

Interpreta, explica y prioriza las señales ya generadas por el motor de
reglas de la Etapa 3, **sin reemplazarlo**: el motor de reglas sigue siendo
la única fuente oficial de las señales; la IA solo consume su salida.

### `MarketContext` (`src/ai/context.py`)

Modelo Pydantic que agrupa todo lo que el AI Decision Engine necesita para
razonar sobre un símbolo: `exchange`, `symbol`, `current_price`,
`indicators` (último `IndicatorSnapshot`, opcional), `latest_signal`
(último `SignalSnapshot`, opcional) y `recent_signals` (historial de hasta
5 señales anteriores, sin repetir la última). `AIService` lo arma con
`build_market_context()` a partir de datos que ya obtuvo de
`IndicatorRepository`/`SignalRepository`/`MarketDataRepository`: la función
no hace ninguna consulta por sí misma.

### `PromptBuilder` (`src/ai/prompt_builder.py`) y `PromptVersion`

Convierte un `MarketContext` en texto plano: precio, indicadores, y — si
hay una señal disponible — su `trend`/`ema_signal`/`macd_signal`/
`rsi_signal`/`bollinger_signal` con su `reason` y `rule_strength`
individuales, además de `score`, `confidence` y `signal_type`. **El prompt
no contiene ninguna lógica de negocio**: solo expone información ya
calculada por las Etapas 2 y 3, siempre en el mismo orden y con las mismas
etiquetas.

`PromptVersion` es un Enum (`V1 = "v1"`, hoy el único valor), no un `str`
suelto: `AIRecommendation.prompt_version` solo acepta una versión de
formato de prompt conocida y válida. `CURRENT_PROMPT_VERSION` (constante
del módulo) es lo que `DecisionEngine` usa para completar cada
`AIRecommendation` nueva. Si el formato del prompt cambiara de forma
incompatible con versiones anteriores, se agregaría un nuevo miembro (ej.
`V2`) en vez de reemplazar `V1`, para poder seguir reconstruyendo
recomendaciones históricas ya guardadas.

### `AIProvider` (`src/ai/base.py`) y `providers/`

Interfaz que abstrae "quién genera la recomendación": `DecisionEngine` no
sabe si el proveedor activo es `DummyProvider`, `OpenAIProvider` o
`ClaudeProvider`.

| Proveedor | Estado | Comportamiento |
|---|---|---|
| `DummyProvider` | **Conectado** | Determinista: deriva `recommendation`/`risk_level` de la línea `"Signal Type: ..."` que `PromptBuilder` ya escribió (el mismo veredicto que el motor de señales calculó). No usa IA real ni texto aleatorio. `dummy_delay` simula latencia de un proveedor real. |
| `OpenAIProvider` | Estructura preparada, NO conectado | `generate()` lanza `NotImplementedError`, igual que los stubs de PostgreSQL. |
| `ClaudeProvider` | Estructura preparada, NO conectado | Ídem. |

Cambiar de proveedor es un cambio de una línea en `config.yaml ->
ai.provider` (`_build_ai_provider()` en `src/main.py`, el único lugar que
decide qué clase instanciar); ningún otro módulo necesita cambiar.

### `DecisionEngine` (`src/ai/decision_engine.py`)

Lógica pura, igual en espíritu que `SignalEngine`: recibe un
`MarketContext`, construye el prompt (`PromptBuilder`), llama al
`AIProvider` activo, y arma la `AIRecommendation` final agregando los
campos que el proveedor no conoce (`exchange`, `symbol`, `timestamp`,
`provider`, `prompt_version`, `processing_time_ms`) y copiando el resto
(incluyendo `raw_response`) tal cual. **No sabe leer de SQLite, no sabe
consultar Binance y no conoce ningún Dashboard.**

`processing_time_ms` se mide con `time.perf_counter()` (reloj monotónico,
no afectado por ajustes del reloj del sistema) **únicamente alrededor de
`provider.generate(prompt)`**, no del armado del prompt ni de nada
posterior:

```python
start = time.perf_counter()
response = self.provider.generate(prompt)
processing_time_ms = (time.perf_counter() - start) * 1000
```

`DecisionEngine.decide()` **no atrapa ninguna excepción** que lance
`provider.generate()`: si el proveedor falla (ej. un error de red de un
proveedor real en el futuro), el error se propaga tal cual a `AIService`,
en vez de ocultarse silenciosamente.

### `AIRecommendation` (`src/ai/recommendation.py`)

```python
AIRecommendation(
    exchange="Binance", symbol="BTCUSDT", timestamp=datetime.now(timezone.utc),
    recommendation=RecommendationAction.BUY, confidence=60.0, risk_level=RiskLevel.MEDIUM,
    reasoning="El motor de señales (Etapa 3) reporta una tendencia alcista (signal_type=Bullish).",
    advantages=["La acción sugerida (Buy) está alineada con el signal_type ya calculado..."],
    risks=["DummyProvider es una simulación: no usa un modelo de lenguaje real..."],
    summary="Recomendación simulada: Buy.",
    provider="DummyProvider", model="dummy-v1", prompt_version=PromptVersion.V1,
    processing_time_ms=3.42, raw_response=None,
)
```

**`RecommendationAction`** tiene 7 valores (`Strong Buy`, `Buy`, `Weak Buy`,
`Hold`, `Weak Sell`, `Sell`, `Strong Sell`) para que un proveedor real
pueda expresar matices de convicción; los 3 originales (`Buy`/`Sell`/`Hold`)
mantienen el mismo texto que antes de ampliar el enum, así que ninguna
`AIRecommendation` ya guardada deja de poder leerse. `DummyProvider` sigue
usando solo esos 3 valores a propósito.

**`RiskLevel`** tiene 5 valores (`Very Low`, `Low`, `Medium`, `High`, `Very
High`, igual en espíritu que `ConfidenceLevel` de la Etapa 3); los 3
originales (`Low`/`Medium`/`High`) también mantienen el mismo texto.
`DummyProvider` sigue usando solo `Low`/`Medium`.

**`processing_time_ms`** (`float`, `>= 0.0`): cuánto tardó únicamente la
llamada al proveedor (ver `DecisionEngine` más arriba).

**`raw_response`** (`Optional[str]`, `None` por defecto): la respuesta
cruda del proveedor (ej. el JSON/texto tal cual lo devolvió OpenAI/Claude),
para auditoría y depuración cuando se conecte un proveedor real.
`DummyProvider` siempre devuelve `None`.

**Nota de conceptos** (para no repetir la confusión que motivó la revisión
2 de la Etapa 3): `confidence` aquí es un **número (0.0-100.0)**, la certeza
autoreportada por el proveedor sobre **su propia** recomendación. Es
distinto de `SignalSnapshot.confidence` (Etapa 3), que es un
`ConfidenceLevel` **categórico** y mide el acuerdo entre las 5 reglas del
motor de señales. `risk_level` es un concepto nuevo de esta etapa, sin
equivalente en la 3.

### `AIExplanation` (`src/ai/explanation.py`)

Vista derivada y legible de una `AIRecommendation` ya generada
(`build_explanation()`): resumen, razón principal, factores (positivos y
negativos como bullets) y conclusión. Pensada para un futuro Dashboard; no
se persiste en `ai_recommendations` (no agrega información nueva sobre la
que ya guarda `AIRecommendation`, solo la reformatea).

### `AIService` (`src/ai/service.py`)

Conecta el motor con el resto del sistema: por cada símbolo, lee la última
señal (`SignalRepository.fetch_latest`) y su historial reciente
(`fetch_history(limit=6)`, del cual se descarta el último elemento —
`history[:-1]` — porque corresponde a la misma fila que `latest_signal`),
los indicadores más recientes y el precio actual, arma el `MarketContext`,
ejecuta `DecisionEngine`, y guarda el resultado con `AIRepository`. Si
todavía no hay señal o precio disponible para un símbolo, lo omite y
registra un `logger.warning` (igual que `SignalService` con
indicadores/precio faltantes) — nunca falla en silencio. Se probó
explícitamente con 1, 3, 6 y 8 señales totales en el historial
(`tests/test_ai_service.py::TestRecentSignalsHistory`), confirmando que
`recent_signals` nunca repite `latest_signal`, siempre queda ordenado del
más antiguo al más reciente, y respeta el límite de 5 señales anteriores.

**`ai.enabled=false`**: `build_services()` (`src/main.py`) devuelve `None`
como `AIService` cuando está deshabilitado — ni `AIService`, ni
`DecisionEngine`, ni el `AIProvider` activo, ni siquiera
`SQLiteAIRepository.init()` (la tabla `ai_recommendations` no se crea) se
ejecutan. `run_full_cycle()` simplemente omite el 4to paso cuando recibe
`None`, sin afectar a `MarketDataService`/`IndicatorService`/`SignalService`.

### Tabla `ai_recommendations`, separada de las 3 tablas anteriores

`SQLiteAIRepository` crea y usa una tabla independiente, con 16 columnas:

```
id, exchange, symbol, recommendation, confidence, risk_level,
reasoning, advantages, risks, summary,
provider, model, prompt_version,
processing_time_ms, raw_response, created_at
```

`advantages` y `risks` (listas de texto) se guardan como JSON en una
columna `TEXT` (`json.dumps`/`json.loads`). `prompt_version` es un Enum:
se serializa explícitamente a texto (`.value`) al guardar, igual que
`recommendation`/`risk_level`. `raw_response` es `TEXT` nullable (`sqlite3`
traduce `None <-> NULL` automáticamente). Se guardan **todos** los campos
de `AIRecommendation` (no solo el mínimo original de 10 campos): omitir
`advantages`/`risks`/`prompt_version`/`processing_time_ms`/`raw_response`
habría perdido justo los datos de explicabilidad y auditoría que esta
etapa exige poder consultar después. Ni `market_data`, ni
`market_indicators`, ni `market_signals` se modifican.

**Migración idempotente**: la tabla se creó por primera vez sin
`processing_time_ms` ni `raw_response`. `_migrate_missing_columns()`
agrega ambas columnas si faltan (mismo patrón `PRAGMA table_info` + `ALTER
TABLE ... ADD COLUMN` que `SQLiteSignalRepository`), sin perder ni alterar
ningún registro existente. Probado explícitamente con una base construida
manualmente con el esquema anterior, un registro insertado con ese
esquema, y 3 llamadas consecutivas a `init()`
(`tests/test_ai_sqlite_repository.py::test_migration_adds_processing_time_ms_and_raw_response_without_losing_existing_rows`).

### `PostgresAIRepository` (`src/ai/postgres_repository.py`)

Stub NO implementado, mismo patrón que
`PostgresMarketDataRepository`/`PostgresIndicatorRepository`/
`PostgresSignalRepository`: sus 4 métodos lanzan `NotImplementedError`.

### Límites actuales del motor de IA

- **Ningún proveedor real está conectado**: `DummyProvider` es
  determinista y útil para probar el pipeline, pero no interpreta nada con
  IA de verdad.
- **`AIRecommendation.confidence` es autoreportada por el proveedor**: con
  `DummyProvider` siempre vale 60.0 (constante), ya que no hay un modelo
  real evaluando su propia certeza.
- **El límite de historial reciente (5 señales) no es configurable** desde
  `config.yaml`: es un límite de contexto del prompt, no un umbral de
  negocio.
- **`DummyProvider` no usa todavía los niveles fuertes/débiles de
  `RecommendationAction` ni los extremos de `RiskLevel`**: quedan
  disponibles en el modelo para cuando se conecte un proveedor real capaz
  de expresar esos matices.

Ver más detalle y justificación en [ALCANCE_ETAPA_4.md](ALCANCE_ETAPA_4.md).

## Configuración: `config.yaml` + `.env`

- `config/config.yaml`: monedas, intervalo, límites de alerta, rutas de
  archivos, motor de base de datos. No contiene secretos y sí se sube a
  git.
- `.env` (basado en `.env.example`, nunca se sube a git): credenciales.
  En esta etapa existen los campos para Binance, OpenAI, Anthropic,
  Telegram, CoinGecko y NewsAPI, pero **ninguno se usa todavía** para
  conectarse a un servicio real.

`src/utils/config.py` combina ambas fuentes en un objeto `Settings`
(dataclasses inmutables), que es lo que reciben el resto de los módulos.

## Preparación para múltiples exchanges

Para agregar un exchange nuevo (ej. Bybit) en una etapa futura:

1. Crear `src/market/bybit.py` con una clase `BybitExchangeClient` que
   implemente `ExchangeClient` (el mismo método `get_tickers`).
2. Ese archivo es el único lugar que conoce los detalles de la API de
   Bybit.
3. `MarketDataService`, `main.py` (salvo el punto donde se decide qué
   cliente instanciar) y todo lo demás siguen funcionando sin cambios.

## Preparación para PostgreSQL

`src/database/postgres_repository.py` (para `market_data`) y
`src/database/postgres_indicator_repository.py` (para `market_indicators`)
ya existen como estructura (todos sus métodos lanzan `NotImplementedError`
a propósito). Para activarlos en el futuro:

1. Agregar un driver de PostgreSQL a `requirements.txt`.
2. Implementar los métodos de cada uno usando ese driver y la variable de
   entorno `DATABASE_URL` (ya preparada en `.env.example` y en
   `Settings.database.postgres_url`).
3. Cambiar, en `src/main.py` (`build_services()`), qué repositorios se
   instancian. Nada más en el proyecto necesita cambiar.

## Módulos reservados (todavía vacíos, a propósito)

`src/dashboard/`, `src/alerts/` y `src/telegram/` existen como carpetas con
un `__init__.py` que documenta su propósito futuro, pero sin ningún código
funcional todavía. Se crearon para que, cuando se autorice cada etapa, el
código nuevo tenga un lugar natural donde vivir, sin tener que reorganizar
el proyecto otra vez. `src/ai/` dejó de estar en esta lista desde la
Etapa 4: ya contiene código funcional (ver "Motor de decisión de IA" más
arriba). `src/dashboard/` tiene su diseño completo definido en la
Iteración 5.1 (ver más abajo), pendiente de aprobación antes de
implementarse en la Iteración 5.2.

## Dashboard (Etapa 5 — en diseño, sin implementar todavía)

La Etapa 5 agrega un Dashboard de **solo lectura** sobre las 4 tablas ya
generadas por las Etapas 1 a 4 (`market_data`, `market_indicators`,
`market_signals`, `ai_recommendations`), sin recalcular ni modificar
ningún dato. Tecnología seleccionada: **Streamlit** (Python puro, un solo
proceso, sin backend adicional). El diseño separa la consulta de datos
(`src/dashboard/data_access.py`, que reutiliza los 4 repositorios
existentes solo con `fetch_latest`/`fetch_history`) de la presentación
(páginas Streamlit), precisamente para poder migrar esa capa de consulta
a una futura API sin reescribirla. Ver el diseño completo, las páginas,
los componentes y los filtros globales en
[ARQUITECTURA_DASHBOARD.md](ARQUITECTURA_DASHBOARD.md) y el alcance en
[ALCANCE_ETAPA_5.md](ALCANCE_ETAPA_5.md).

## Qué NO cambia para el usuario

El comando para ejecutar el bot sigue siendo el mismo:

```bash
python -m src.main
```

El comportamiento de la Etapa 1/1.5 (qué monedas consulta, cada cuánto, qué
guarda en `market_data`, qué registra en logs) no cambió. La Etapa 2 se
sumó sin reemplazar nada (indicadores en `market_indicators`), la Etapa 3
tampoco reemplaza nada (señales en `market_signals`), y la Etapa 4 sigue el
mismo patrón: cada ciclo, además, interpreta la última señal con IA
(`DummyProvider`, sin conexión a ninguna API real) y guarda el resultado en
`ai_recommendations`. Si `config.yaml -> ai.enabled` es `false`, este paso
se omite sin afectar a las 3 etapas anteriores.
