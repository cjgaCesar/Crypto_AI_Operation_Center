# Arquitectura de Paper Trading (Etapa 6.0 — diseño, sin implementar)

> **Este documento es exclusivamente de diseño.** Ninguna clase, tabla,
> archivo de configuración ni prueba descrita aquí existe todavía en el
> código. Todo nombre de archivo, clase o tabla mencionado es una
> **propuesta**, sujeta a tu aprobación antes de implementarse. No hay
> compra ni venta, simulada o real, en esta etapa.

## 0. Análisis del código existente

Antes de diseñar nada nuevo se revisó completamente el código real de
las Etapas 1 a 5 (`src/database/`, `src/services/`, `src/signals/`,
`src/ai/`, `src/models/`, `src/dashboard/`, `src/utils/config.py`,
`src/main.py`, `config/config.yaml`, `tests/`). El resumen ejecutivo
está en [ALCANCE_ETAPA_6.md](ALCANCE_ETAPA_6.md#análisis-del-código-existente);
aquí el detalle que fundamenta cada decisión de diseño de las secciones
siguientes.

### Convenciones confirmadas que este diseño reutiliza

- **Un repositorio por tabla**, siempre con una interfaz abstracta en un
  `base.py`/`repository.py` (`MarketDataRepository`, `IndicatorRepository`
  en `src/database/base.py`; `SignalRepository` en `src/signals/base.py`;
  `AIRepository` en `src/ai/repository.py`) y una implementación
  `SQLite*Repository` concreta, más un stub `Postgres*Repository` (todos
  sus métodos lanzan `NotImplementedError`, preparado pero no conectado).
- **Conexión SQLite nueva por llamada**: cada método abre su propia
  `sqlite3.connect(...)`, siempre en `try/finally: conn.close()`, con
  `commit()` explícito tras escribir. No hay conexión persistente ni pool.
- **Migración idempotente sin framework**: `init()` hace `CREATE TABLE IF
  NOT EXISTS` y luego `_migrate_missing_columns()` (`PRAGMA table_info` +
  `ALTER TABLE ... ADD COLUMN` solo para las columnas que falten),
  verificado con 3 llamadas consecutivas a `init()` sin perder filas.
- **Motor puro separado del servicio con I/O**: `IndicatorEngine`,
  `SignalEngine` (implícito en `src/signals/engine.py`) y `DecisionEngine`
  no conocen SQLite ni Binance; reciben datos ya obtenidos y devuelven un
  modelo Pydantic. `IndicatorService`/`SignalService`/`AIService` son los
  que conectan el motor con los repositorios, cada uno con un único
  método público `run_cycle() -> None`, iterando `for symbol in
  self.symbols`, sin fallar en silencio (`logger.warning` + `continue`
  cuando falta un dato previo).
- **Configuración**: `Settings` (`src/utils/config.py`) es un árbol de
  `@dataclass(frozen=True)`, una por sección. `config.yaml` (comportamiento,
  se sube a git) + `.env` (secretos, nunca se sube a git). Cada sección de
  comportamiento nueva (ej. `AIEngineSettings`) se valida a mano con una
  función `_validate_*_config()` propia, sin librería de esquemas.
- **`main.py` como Composition Root**: `build_services()` arma todo;
  `run_full_cycle()` ejecuta cada servicio en orden fijo. Un servicio
  opcional (`AIService`) se apaga por completo (ni se instancia) cuando
  `settings.ai_engine.enabled` es `false` — el mismo mecanismo que este
  diseño reutiliza para `paper_trading.enabled`.
- **Extensión de solo lectura del Dashboard**: `DashboardRepository`
  reutiliza los métodos `fetch_latest`/`fetch_history` de los 4
  repositorios existentes para todo lo que ya tienen, y solo abre su
  propia conexión `mode=ro` para las 2 consultas que no tienen
  equivalente (`get_available_symbols`, `get_table_status`). Nunca llama
  a `save()` ni `init()` de ningún repositorio.
- **Modelos Pydantic**: `Optional[X] = None` para todo lo que puede no
  estar disponible todavía (nunca un valor inventado); `Field(ge=...,
  le=...)` para numéricos acotados; campos de categoría siempre como
  `class X(str, Enum)`, nunca `str` suelto; timestamps como `datetime`
  (serializados `.isoformat()`, reconstruidos automáticamente por
  Pydantic al leer).

### Qué se reutiliza, qué se extiende, qué se aísla

| | Decisión | Detalle |
|---|---|---|
| **Reutilizar tal cual** | `MarketTicker`, `IndicatorSnapshot`, `SignalSnapshot`, `AIRecommendation` | Entrada de solo lectura para el motor de Paper Trading; ninguno se modifica. |
| **Reutilizar el patrón** | Repository/Service/Engine, conexión SQLite, migración idempotente, `Settings`, extensión read-only del Dashboard, convención de nombres de pruebas | Se copia la forma, no el código: Paper Trading tendrá sus propias clases siguiendo el mismo molde. |
| **Extender (aditivo)** | `Settings`, `config.yaml`, `main.py`, `DashboardRepository`/`DashboardService` | Se agregan piezas nuevas sin tocar las existentes — mismo mecanismo de apagado que `ai_engine.enabled`. |
| **Aislar (módulo nuevo)** | `src/paper_trading/`, tablas `paper_trading_*` | Cero código previo de órdenes/posiciones/cartera/riesgo/PnL en todo el proyecto (confirmado con búsqueda exhaustiva): esto es enteramente nuevo. |

## 1. Arquitectura general

```
Repository   (única capa que toca SQLite: paper_trading_*)
    ↓
Service      (PaperTradingService.run_cycle(): orquesta cada ciclo)
    ↓
Domain       (Order, Position, Portfolio, Trade, Execution, ... — Pydantic puro)
    ↓
Paper Trading Engine   (PaperTradingEngine + RiskEngine: lógica pura, sin I/O)
    ↓
Dashboard    (lee vía DashboardRepository extendido — solo lectura, sin páginas nuevas todavía)
```

**Nota sobre la dirección real de las dependencias** (para no confundir
esta lista con una tubería estrictamente secuencial, como si cada capa
solo llamara a la siguiente): `PaperTradingService` es quien realmente
coordina — llama al `Repository` para leer/guardar, invoca el `Paper
Trading Engine` (motores puros) pasándole los modelos de `Domain`, y el
`Dashboard` consume todo exclusivamente a través del `Repository` (nunca
a través del `Service` ni del `Engine` directamente, igual que hoy con
`market_signals`/`ai_recommendations`). El orden de la lista respeta el
mismo espíritu que el flujo ya documentado en `ARQUITECTURA.md`
(`MarketData → IndicatorEngine → SignalEngine → ... → Dashboard`): de
"quién guarda el dato crudo" a "quién lo consume al final".

### Diagrama de flujo end-to-end (con las etapas ya aprobadas)

```
Binance -> MarketData -> IndicatorEngine -> SignalEngine -> AIService -> AIRecommendation
                                                                              │
                                                                              ▼  (futuro, Etapa 6.2+, NO implementado)
                                                          StrategyEngine / acción manual (Dashboard)
                                                                              │
                                                                              ▼
                                                                      Order (estado NEW)
                                                                              │
                                                                              ▼
                                                                RiskEngine.validate(order, portfolio)
                                                                    /                        \
                                                             rechaza                        acepta
                                                                │                              │
                                                            REJECTED                       PENDING
                                                                                                │
                                                                                                ▼
                                                                        OrderBook simulado (fill sim., ver §5)
                                                                                                │
                                                                              PARTIALLY_FILLED / FILLED
                                                                                                │
                                                                                                ▼
                                                        Execution -> actualiza Position -> Trade (si cierra posición)
                                                                                                │
                                                                                                ▼
                                                                CashBalance + PortfolioSnapshot + PnLSnapshot
                                                                                                │
                                                                                                ▼
                                                        paper_trading_* (SQLite — única capa que escribe)
                                                                                                │
                                                                                                ▼
                                            Dashboard (solo lectura, página futura, NO implementada en esta etapa)
```

**La IA no ejecuta órdenes directamente**, igual que hoy la IA no
reemplaza al motor de señales: un futuro `StrategyEngine` solo
*propondría* una `Order`, que siempre pasa por `RiskEngine.validate()`
antes de aceptarse — la IA nunca bypasea el control de riesgo.

## 2. Modelo de dominio

Todos los modelos son Pydantic puros (mismo criterio que `models/`,
`signals/`, `ai/`): sin SQLite, sin Streamlit, sin lógica de negocio
dentro del modelo (eso vive en el motor). Vivirían en un paquete nuevo
`src/paper_trading/` (`enums.py` + un archivo por modelo, mismo patrón
que `src/ai/`).

### 2.1 `Order`

La intención de operar (simulada), desde que se crea hasta que se
resuelve.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | `str` (UUID) | Identidad estable durante todo el ciclo de vida. |
| `exchange` | `str` | Igual convención que las 4 tablas existentes (`"Binance"` hoy). |
| `symbol` | `str` | `Field(min_length=1)`. |
| `side` | `OrderSide` (enum) | `BUY` / `SELL`. |
| `order_type` | `OrderType` (enum) | `MARKET` / `LIMIT` (ver §5 — limitación de datos). |
| `quantity` | `float` | `Field(gt=0.0)`. Cantidad solicitada. |
| `limit_price` | `Optional[float]` | Requerido si `order_type=LIMIT`; `None` si `MARKET`. |
| `status` | `OrderStatus` (enum) | Ver §4. |
| `filled_quantity` | `float` | `Field(ge=0.0)`; invariante: `filled_quantity <= quantity`. |
| `average_fill_price` | `Optional[float]` | `None` hasta la primera ejecución. |
| `source` | `OrderSource` (enum) | `MANUAL` / `AI_RECOMMENDATION` / `STRATEGY` (ver §14). |
| `linked_recommendation_id` | `Optional[str]` | Trazabilidad hacia la `AIRecommendation` que originó la orden, si aplica. |
| `rejection_reason` | `Optional[str]` | Solo si `status=REJECTED`. |
| `cancellation_reason` | `Optional[str]` | Solo si `status=CANCELLED`. |
| `created_at` | `datetime` | Momento de creación (estado `NEW`). |
| `updated_at` | `datetime` | Última transición de estado. |
| `expires_at` | `Optional[datetime]` | Si se define, habilita la transición a `EXPIRED`. |

**Invariantes**: `filled_quantity <= quantity`; `average_fill_price` solo
puede ser `None` cuando `filled_quantity == 0`; `limit_price` es
obligatorio si y solo si `order_type == LIMIT`.

### 2.2 `Execution` (fill)

Un evento de ejecución individual contra una `Order`. Una orden puede
tener 0 (todavía no ejecutada), 1 (llenado total en un solo evento) o
varias `Execution` (llenados parciales sucesivos).

| Campo | Tipo | Notas |
|---|---|---|
| `id` | `str` (UUID) | |
| `order_id` | `str` | FK lógica a `Order.id`. |
| `exchange`, `symbol` | `str` | Duplicado de la orden a propósito, para poder leer una ejecución sin resolver su orden (mismo criterio que `market_signals` duplica `exchange`/`symbol` en vez de solo guardar un ID). |
| `quantity` | `float` | `Field(gt=0.0)`. Cantidad de esta ejecución puntual. |
| `price` | `float` | `Field(gt=0.0)`. Precio simulado de esta ejecución (ver §5). |
| `fee` | `float` | `Field(ge=0.0)`. Comisión simulada (config: `paper_trading.fee_percent`). |
| `executed_at` | `datetime` | |

### 2.3 `Trade` (round-trip cerrado)

Distinto de `Execution`: una `Execution` es **un llenado** (evento a
nivel de orden); un `Trade` es el **cierre, total o parcial, de una
posición** (evento a nivel de posición, el que realiza PnL). Abrir una
posición no genera un `Trade` todavía — el `Trade` se genera cuando una
ejecución en sentido contrario reduce o cierra una posición existente.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | `str` (UUID) | |
| `exchange`, `symbol` | `str` | |
| `side` | `TradeSide` (enum) | `LONG` / `SHORT` — dirección de la posición que se cerró. |
| `quantity` | `float` | `Field(gt=0.0)`. Cantidad cerrada por este trade. |
| `entry_price` | `float` | Precio promedio de entrada de la porción cerrada. |
| `exit_price` | `float` | Precio de la ejecución que cerró. |
| `realized_pnl` | `float` | `(exit_price - entry_price) * quantity * signo(side)`, menos comisiones. |
| `opened_at`, `closed_at` | `datetime` | |
| `entry_execution_ids` | `list[str]` | Trazabilidad hacia las ejecuciones de apertura. |
| `exit_execution_id` | `str` | Trazabilidad hacia la ejecución de cierre. |

### 2.4 `Position`

Estado agregado y **actual** (no histórico) de la exposición en un
símbolo, derivado de sus ejecuciones.

| Campo | Tipo | Notas |
|---|---|---|
| `exchange`, `symbol` | `str` | Clave natural (una posición vigente por símbolo). |
| `side` | `PositionSide` (enum) | `LONG` / `SHORT` / `FLAT` (cantidad 0). |
| `quantity` | `float` | `Field(ge=0.0)`. Siempre positiva; `side` da la dirección. |
| `average_entry_price` | `Optional[float]` | `None` si `side=FLAT`. Recalculado en cada ejecución que **aumenta** la posición (promedio ponderado); no cambia con ejecuciones que la **reducen**. |
| `realized_pnl_to_date` | `float` | Acumulado de todos los `Trade` de este símbolo. |
| `opened_at` | `Optional[datetime]` | Cuándo pasó de `FLAT` a con cantidad, la vez más reciente. |
| `updated_at` | `datetime` | |

`unrealized_pnl` **no se persiste como campo de `Position`**: se calcula
al vuelo como `(precio_actual - average_entry_price) * quantity *
signo(side)`, usando el último `MarketTicker.price` — nunca un precio
guardado ni recalculado por otro módulo. Si se necesita historizarlo
para el Dashboard, eso es exactamente el propósito de `PnLSnapshot`
(§2.9), no de `Position`.

### 2.5 `CashBalance`

Capital disponible de la cuenta de Paper Trading (una sola cuenta
simulada por ahora; no hay sub-cuentas ni multi-usuario en esta etapa).

| Campo | Tipo | Notas |
|---|---|---|
| `currency` | `str` | `"USDT"` por defecto (config), simulada. |
| `total_balance` | `float` | `Field(ge=0.0)`. |
| `reserved_balance` | `float` | `Field(ge=0.0)`. Capital apartado por órdenes `PENDING`/`PARTIALLY_FILLED` sin llenar todavía. |
| `available_balance` | `float` | Propiedad calculada: `total_balance - reserved_balance`, nunca un campo guardado por separado (evita que quede desincronizado). |
| `updated_at` | `datetime` | |

### 2.6 `OrderBook` (simulado)

**No es un order book real.** Ver §5 para la limitación completa; aquí
solo el modelo mínimo que representa la "vista de mercado" que el motor
usa para decidir si una orden se llena:

| Campo | Tipo | Notas |
|---|---|---|
| `exchange`, `symbol` | `str` | |
| `reference_price` | `float` | El último `MarketTicker.price` disponible — el único dato de precio que existe hoy en el proyecto. |
| `timestamp` | `datetime` | `MarketTicker.queried_at` del dato usado. |

No hay `bid`/`ask`, ni niveles de profundidad: el endpoint de Binance que
usa este proyecto (`/api/v3/ticker/24hr`) no los provee. Esto se declara
explícitamente, no se inventa un spread.

### 2.7 `RiskLimits`

Configuración de reglas de riesgo (ver §8), leída de
`config.yaml -> paper_trading.risk` (no hay UI para editarlas en esta
etapa).

| Campo | Tipo | Notas |
|---|---|---|
| `max_position_size` | `float` | Cantidad máxima (no notional) por símbolo. |
| `max_portfolio_exposure_pct` | `float` | `Field(gt=0.0, le=100.0)`. % del equity total que puede estar en posiciones abiertas. |
| `max_loss_per_trade_pct` | `float` | `Field(gt=0.0, le=100.0)`. Pérdida máxima tolerada en un solo trade, como % del equity. |
| `max_daily_loss_pct` | `float` | `Field(gt=0.0, le=100.0)`. Circuit breaker diario (§8). |
| `min_order_quantity` | `float` | `Field(gt=0.0)`. |
| `max_order_quantity` | `float` | `Field(gt=0.0)`. |

### 2.8 `PortfolioSnapshot`

Fila periódica (una por ciclo, mismo cadencia que `market_data`) con el
estado agregado de toda la cuenta — para graficar la evolución del
equity en el Dashboard sin recalcular nada históricamente.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | `int` (autoincrement) | |
| `timestamp` | `datetime` | |
| `cash_balance` | `float` | |
| `positions_value` | `float` | Suma de `quantity * precio_actual` de todas las posiciones abiertas. |
| `total_equity` | `float` | `cash_balance + positions_value`. |
| `unrealized_pnl_total` | `float` | Suma del no-realizado de todas las posiciones. |
| `realized_pnl_cumulative` | `float` | Acumulado histórico de todos los `Trade`. |

### 2.9 `PnLSnapshot`

Igual cadencia que `PortfolioSnapshot`, pero **por símbolo** (mientras
que `PortfolioSnapshot` es a nivel de cuenta completa) — permite graficar
"cómo le fue a BTCUSDT" por separado de "cómo le fue a la cuenta".

| Campo | Tipo | Notas |
|---|---|---|
| `id` | `int` (autoincrement) | |
| `timestamp` | `datetime` | |
| `exchange`, `symbol` | `str` | |
| `position_quantity` | `float` | Contexto: cuánto había en ese instante. |
| `unrealized_pnl` | `float` | Mark-to-market con el precio de ese instante. |
| `realized_pnl_cumulative` | `float` | Acumulado histórico de ese símbolo únicamente. |

### `Portfolio` — ¿por qué no aparece como tabla propia?

`Portfolio` (mencionado en el pedido) se modela como la **combinación en
memoria** de `CashBalance` + la lista de `Position` vigentes — no como
una tabla nueva. Persistir un "Portfolio" por separado duplicaría datos
que ya viven en `CashBalance`/`Position`, exactamente el mismo criterio
ya aplicado en la Etapa 4 para no persistir `AIExplanation` (vista
derivada, no dato nuevo). `PortfolioSnapshot` sí es una tabla propia
porque captura un **instante histórico** que de otro modo se perdería
(las tablas de estado actual se sobrescriben).

## 3. Flujo completo de una orden

1. **Origen** (futuro, NO implementado en 6.0): una acción manual desde
   el Dashboard, o un `StrategyEngine` que traduce una `AIRecommendation`
   en una propuesta de orden (ver §14). Cualquiera sea el origen, el
   resultado es siempre un objeto `Order` en estado `NEW`, con `source`
   ya asignado.
2. **Validación de riesgo**: `RiskEngine.validate(order, portfolio,
   risk_limits) -> RiskCheckResult` (aprobada/rechazada + motivo). Revisa,
   en orden: cantidad dentro de rango (`min_order_quantity`/
   `max_order_quantity`), capital disponible suficiente
   (`CashBalance.available_balance`), posición resultante dentro de
   `max_position_size`, exposición total dentro de
   `max_portfolio_exposure_pct`.
3. **Rechazo**: si `RiskEngine` rechaza, la orden pasa a `REJECTED` con
   `rejection_reason`, no se reserva capital, se emite un evento
   `OrderRejected` (§10). Fin del flujo para esa orden.
4. **Aceptación**: si `RiskEngine` aprueba, la orden pasa a `PENDING`, se
   reserva capital en `CashBalance.reserved_balance` (el notional
   estimado de la orden), se emite `OrderCreated` + `OrderValidated`.
5. **Simulación de llenado** (`PaperTradingEngine`, motor puro, ver §5):
   usa el `OrderBook` simulado (último `MarketTicker.price`) para decidir
   si la orden se llena, total o parcialmente, en este ciclo.
   - `MARKET`: se llena de inmediato y por completo al precio de
     referencia actual (liquidez simulada infinita — ver limitación en
     §5).
   - `LIMIT`: se compara el precio de referencia contra `limit_price`; si
     lo "toca" en la dirección favorable, se llena (ver §5 para el
     detalle de esta simplificación); si no, la orden permanece
     `PENDING` para el siguiente ciclo.
6. **Ejecución**: cada llenado crea una `Execution`, actualiza `Position`
   (promedio de entrada si aumenta, o genera un `Trade` con su
   `realized_pnl` si reduce/cierra), ajusta `CashBalance` (libera lo
   reservado, debita/acredita el efectivo real, cobra `fee`), y emite
   `OrderFilled`/`OrderPartiallyFilled` + `PositionUpdated` + (si aplica)
   `TradeClosed`.
7. **Resolución del estado de la orden**: `FILLED` si
   `filled_quantity == quantity`; permanece `PARTIALLY_FILLED` si quedó
   remanente sin llenar; puede pasar a `CANCELLED` (cancelación explícita
   del remanente) o `EXPIRED` (si `expires_at` se cumplió sin llenarse
   del todo) en un ciclo posterior.
8. **Snapshots periódicos**: al final de cada ciclo (misma cadencia que
   `market_data`), `PaperTradingService.run_cycle()` genera un
   `PortfolioSnapshot` y un `PnLSnapshot` por símbolo con posición
   abierta — para que el Dashboard pueda graficar la evolución sin
   recalcular el histórico completo cada vez.
9. **Consumo por el Dashboard** (futuro, NO implementado en 6.0): una
   extensión de solo lectura de `DashboardRepository` expone todo lo
   anterior — nunca escribe.

## 4. Estados de una orden

```
                 ┌──────────┐
                 │   NEW    │  (creada, todavía sin validar)
                 └────┬─────┘
             aprueba  │  rechaza
        ┌─────────────┴─────────────┐
        ▼                           ▼
  ┌───────────┐               ┌───────────┐
  │  PENDING  │               │ REJECTED  │  (terminal)
  └─────┬─────┘               └───────────┘
        │
   ┌────┼─────────────┬───────────────┐
   │llenado│cancela   │expira         │llenado
   │parcial│          │               │total
   ▼       ▼          ▼               ▼
┌────────────────┐ ┌───────────┐ ┌─────────┐  ┌──────────┐
│PARTIALLY_FILLED│ │ CANCELLED │ │ EXPIRED │  │  FILLED  │
└───────┬─────────┘ └───────────┘ └─────────┘  └──────────┘
        │  (terminal)              (terminal)   (terminal)
  ┌─────┼─────────┬──────────┐
  │llenado│cancela│expira    │
  │total  │       │          │
  ▼       ▼       ▼
FILLED  CANCELLED EXPIRED
```

### Tabla de transiciones válidas

| Desde | Hacia | Disparador |
|---|---|---|
| `NEW` | `PENDING` | `RiskEngine` aprueba la orden. |
| `NEW` | `REJECTED` | `RiskEngine` rechaza la orden (capital insuficiente, límite excedido, cantidad fuera de rango). |
| `PENDING` | `PARTIALLY_FILLED` | El motor llena una parte de la cantidad. |
| `PENDING` | `FILLED` | El motor llena toda la cantidad en una sola ejecución. |
| `PENDING` | `CANCELLED` | Cancelación explícita antes de cualquier llenado. |
| `PENDING` | `EXPIRED` | Se cumple `expires_at` sin ningún llenado. |
| `PARTIALLY_FILLED` | `FILLED` | El motor llena el remanente. |
| `PARTIALLY_FILLED` | `CANCELLED` | Cancelación explícita del remanente sin llenar. |
| `PARTIALLY_FILLED` | `EXPIRED` | Se cumple `expires_at` con remanente sin llenar. |

### Transiciones inválidas (deben rechazarse explícitamente en el motor)

| Transición inválida | Por qué |
|---|---|
| `NEW → FILLED` (saltando `PENDING`) | Toda orden debe pasar por una validación de riesgo auditable, aunque el llenado ocurra en el mismo ciclo — la transición a `PENDING` deja un evento propio (`OrderValidated`), necesario para la auditoría (§11). |
| `PARTIALLY_FILLED → REJECTED` | El rechazo solo tiene sentido **antes** de cualquier ejecución real; una vez que hubo un llenado parcial, la única salida es completar, cancelar o expirar el remanente. |
| Cualquier transición **desde** `FILLED`, `CANCELLED`, `REJECTED` o `EXPIRED` | Los 4 son estados terminales. Ninguna orden vuelve a cambiar de estado una vez alcanzado uno de estos — invariante que una prueba futura debe verificar explícitamente. |
| `PENDING → NEW` o `PARTIALLY_FILLED → PENDING` (retroceder) | El estado nunca retrocede; cada transición es un evento nuevo hacia adelante, nunca una corrección del pasado. |

## 5. Limitación central: no existe un order book real

**Esta es la limitación de diseño más importante de todo el documento,
declarada explícitamente para no fingir una simulación más realista de
la que los datos permiten** (mismo criterio que ya se aplicó con ATR/ADX
en la Etapa 2 y con `DummyProvider` en la Etapa 4).

El proyecto solo consulta `/api/v3/ticker/24hr` de Binance (ver
`src/market/binance.py`), que entrega **un único precio** por símbolo y
ciclo (`MarketTicker.price`), sin `bid`/`ask`, sin niveles de
profundidad, y con una cadencia de minutos (`interval_minutes`), no en
tiempo real tick a tick. En consecuencia, el "OrderBook simulado"
(§2.6) **no simula profundidad de mercado real**:

- **Sin spread bid/ask**: compras y ventas se simulan al mismo precio de
  referencia. Un futuro `paper_trading.simulated_spread_percent`
  (configurable, default `0.0`) podría aproximar un spread, pero eso es
  una decisión de diseño para la etapa de implementación, no de esta.
- **Órdenes MARKET**: se asume liquidez simulada infinita — se llenan
  100% al precio de referencia del ciclo actual, sin slippage salvo que
  se configure uno simulado explícitamente.
- **Órdenes LIMIT**: se simulan con una comprobación de "toque" simple
  (`reference_price` cruza `limit_price` en la dirección favorable),
  evaluada una vez por ciclo — no hay forma de saber, con los datos
  disponibles, si el precio tocó el límite *entre* dos ciclos y volvió;
  esto es una aproximación deliberada, no una simulación de microestructura de
  mercado.
- **Llenados parciales de una orden LIMIT**: el diseño por defecto es
  "todo o nada" por ciclo (se llena completa o no se llena), porque no
  hay datos de profundidad para decidir cuánta cantidad "cabría" a ese
  precio. Un modelo de llenado parcial más realista queda como una
  posible mejora de una etapa de implementación futura, no de este
  diseño.

## 6. Modelo de posiciones — detalle de cálculo

- **Aumentar una posición** (ejecución en el mismo sentido que la
  posición actual, o abrir una nueva desde `FLAT`): el nuevo
  `average_entry_price` es el promedio ponderado por cantidad:
  `(qty_vieja × precio_viejo + qty_nueva × precio_nuevo) / (qty_vieja +
  qty_nueva)`. No genera `Trade` (no se cierra nada).
- **Reducir una posición** (ejecución en sentido contrario, cantidad
  menor a la posición abierta): genera un `Trade` por la cantidad
  cerrada, con `realized_pnl = (precio_ejecución - average_entry_price) ×
  cantidad_cerrada × signo(side)`; `average_entry_price` de la posición
  **no cambia** (sigue siendo el de la porción que queda abierta).
- **Cerrar completamente una posición** (ejecución en sentido contrario,
  cantidad igual a la posición abierta): igual que reducir, pero
  `Position` vuelve a `side=FLAT`, `quantity=0`,
  `average_entry_price=None`.
- **Revertir una posición** (ejecución en sentido contrario, cantidad
  mayor a la posición abierta): se trata como **cerrar** la posición
  existente (genera `Trade`) y luego **abrir** una nueva en el sentido
  contrario con el remanente de la ejecución, con su propio
  `average_entry_price` nuevo. No se mezclan ambos tramos en un solo
  cálculo.

## 7. Modelo de cartera (Portfolio)

Como se explicó en §2, `Portfolio` es la combinación en memoria de
`CashBalance` + `list[Position]` vigentes, no una tabla propia:

```
total_equity = cash_balance.total_balance
             + Σ (position.quantity × precio_actual del símbolo)  [solo posiciones no-FLAT]
```

`PaperTradingService` es quien arma este objeto en memoria bajo demanda
(para pasarlo a `RiskEngine.validate()` o para generar un
`PortfolioSnapshot`), leyendo `CashBalance` + todas las `Position` desde
el repositorio — nunca se persiste como una entidad combinada.

## 8. Riesgo

`RiskEngine` (motor puro, sin I/O, mismo espíritu que `IndicatorEngine`/
`SignalEngine`/`DecisionEngine`) valida una orden propuesta contra 5
reglas, en este orden (falla en la primera que no se cumpla, devuelve
`RiskCheckResult(approved: bool, reason: Optional[str])`):

1. **Cantidad por operación**: `RiskLimits.min_order_quantity <=
   order.quantity <= RiskLimits.max_order_quantity`.
2. **Capital disponible**: el notional estimado de la orden
   (`quantity × precio_referencia`, más una estimación de `fee`) no puede
   superar `CashBalance.available_balance`.
3. **Posición máxima**: la cantidad resultante tras la orden
   (`|posición_actual ± quantity|`) no puede superar
   `RiskLimits.max_position_size` para ese símbolo.
4. **Exposición de cartera**: `Σ |valor de cada posición abierta,
   incluyendo esta orden| / total_equity` no puede superar
   `RiskLimits.max_portfolio_exposure_pct`.
5. **Circuit breaker diario**: si la pérdida acumulada del día
   (`realized_pnl` + `unrealized_pnl` desde la medianoche UTC) ya supera
   `RiskLimits.max_daily_loss_pct` del equity, se rechazan **todas** las
   órdenes nuevas hasta el día siguiente — un interruptor de cartera
   completa, no por símbolo.

**`max_loss_per_trade_pct`** (también parte de `RiskLimits`) no se valida
en la aceptación de la orden (no se puede saber la pérdida futura de un
trade que todavía no ocurrió): es una regla que un futuro mecanismo de
stop-loss automático debería consultar, diseño explícitamente fuera del
alcance de esta etapa (ver §15, "Explícitamente fuera de esta etapa").

## 9. Capital disponible

`CashBalance.available_balance` (calculado, no persistido, ver §2.5) es
la única cifra que `RiskEngine` consulta para la regla de capital. El
ciclo de vida de la reserva:

1. **Al aceptar una orden** (`NEW → PENDING`): `reserved_balance +=
   notional_estimado`.
2. **Al llenarse (total o parcialmente)**: `reserved_balance -=
   notional_de_esa_ejecución` (se libera lo reservado); `total_balance`
   se ajusta con el efectivo real intercambiado, menos `fee`.
3. **Al cancelar o expirar el remanente**: `reserved_balance -=
   notional_del_remanente_no_llenado` (se libera sin afectar
   `total_balance`, porque nunca se gastó).

Esto evita el error clásico de simulación de "doble gasto": sin esta
reserva, dos órdenes `PENDING` simultáneas podrían ambas pasar la
validación de capital usando el mismo saldo, y llenarse ambas
"gastando" más efectivo del que existe.

## 10. Eventos del sistema

Registro de eventos append-only (nunca se actualiza ni se borra una fila
ya escrita) — la misma tabla cumple el rol de auditoría (§11), sin
duplicar información en dos lugares.

**Tipos de evento propuestos** (`PaperTradingEventType`, enum):
`OrderCreated`, `OrderValidated`, `OrderRejected`, `OrderFilled`,
`OrderPartiallyFilled`, `OrderCancelled`, `OrderExpired`,
`PositionOpened`, `PositionIncreased`, `PositionReduced`,
`PositionClosed`, `TradeClosed`, `RiskLimitBreached`,
`CashBalanceAdjusted`.

**Modelo `PaperTradingEvent`**:

| Campo | Tipo | Notas |
|---|---|---|
| `id` | `str` (UUID) | |
| `event_type` | `PaperTradingEventType` | |
| `timestamp` | `datetime` | |
| `exchange`, `symbol` | `Optional[str]` | `None` para eventos de cuenta completa (ej. circuit breaker). |
| `order_id` | `Optional[str]` | Si aplica. |
| `description` | `str` | Texto legible (mismo criterio que `reason`/`summary` ya usados en Señales/IA). |
| `payload` | `dict` | Serializado como JSON en una columna `TEXT` (mismo patrón que `advantages`/`risks` de `ai_recommendations`): datos estructurados específicos del evento (ej. cantidades, precios). |

**Invariante a verificar en una prueba futura**: toda transición de
estado de una `Order` (§4) debe generar al menos un evento
correspondiente — "ningún cambio de estado silencioso".

## 11. Auditoría

No existe una tabla de auditoría separada: **`paper_trading_events` (§10)
es el registro de auditoría**, por diseño — mismo criterio que evitó
duplicar `AIExplanation` en la Etapa 4 (una vista derivada no se
persiste dos veces). Principios de auditoría que este diseño exige:

- **Nunca actualizar ni borrar un evento ya escrito** (tabla
  estrictamente append-only, a diferencia de `paper_trading_orders`/
  `paper_trading_positions`, que sí son de estado mutable — ver §12).
- **Todo cálculo monetario debe ser reconstruible desde `Execution` +
  `Trade`**, nunca solo desde un número cacheado: si `PortfolioSnapshot`
  o `Position.realized_pnl_to_date` alguna vez no coincidieran con la
  suma de los `Trade` reales, eso sería un defecto a corregir, no una
  discrepancia aceptable.
- **Todo evento con impacto monetario referencia sus IDs de origen**
  (`order_id`, y dentro de `payload`, `execution_id`/`trade_id` cuando
  aplique), para poder reconstruir la cadena completa de una operación
  desde el evento hasta la fila de `Execution`/`Trade` que la originó.

## 12. Persistencia (diseño de tablas — no se crean en esta etapa)

Mismo patrón que las 4 tablas existentes: una tabla por entidad
persistente, nombres en `snake_case` con prefijo `paper_trading_` (para
que ningún nombre choque con `market_data`/`market_indicators`/
`market_signals`/`ai_recommendations`), migración idempotente al estilo
`SQLiteSignalRepository`/`SQLiteAIRepository`.

**Diferencia arquitectónica deliberada frente a las 4 tablas existentes**:
`market_data`, `market_indicators`, `market_signals` y
`ai_recommendations` son **append-only** (cada ciclo agrega una fila
nueva, nunca se actualiza una existente). Las órdenes y posiciones, por
naturaleza, **sí necesitan actualizarse en el lugar** (una orden cambia
de estado; una posición cambia de cantidad) — esto es nuevo en el
proyecto y se declara explícitamente, no se oculta:

| Tabla propuesta | Naturaleza | Contenido |
|---|---|---|
| `paper_trading_orders` | **Mutable** (UPDATE en cada transición de estado) | Una fila por `Order`, actualizada en el lugar. Columnas: todas las de §2.1. |
| `paper_trading_executions` | Append-only | Una fila por `Execution` (§2.2). |
| `paper_trading_trades` | Append-only | Una fila por `Trade` cerrado (§2.3). |
| `paper_trading_positions` | **Mutable** (estado actual) | Una fila por `(exchange, symbol)`, actualizada en el lugar (§2.4). |
| `paper_trading_cash_balance` | **Mutable** (fila única) | El `CashBalance` de la cuenta simulada (§2.5). |
| `paper_trading_portfolio_snapshots` | Append-only | Una fila por ciclo (§2.8). |
| `paper_trading_pnl_snapshots` | Append-only | Una fila por símbolo por ciclo (§2.9). |
| `paper_trading_events` | Append-only, inmutable | El registro de eventos/auditoría (§10-11). |

**Repositorio propuesto**: `PaperTradingRepository` (interfaz en un
`src/paper_trading/base.py`), con `SQLitePaperTradingRepository`
(implementación) y `PostgresPaperTradingRepository` (stub
`NotImplementedError`, mismo patrón que los otros 4 pares). Métodos que
**sí implican escritura** (`save_order`, `update_order_status`,
`save_execution`, `save_trade`, `upsert_position`,
`update_cash_balance`, `save_portfolio_snapshot`, `save_pnl_snapshot`,
`append_event`) conviven con métodos de lectura
(`get_order`/`get_open_orders`/`fetch_positions`/`fetch_portfolio_history`/
etc.) en la misma interfaz — a diferencia de `DashboardRepository`, que
es **puramente** de lectura porque consume estas tablas desde afuera, sin
ser el dueño de escribirlas.

**No se crea ninguna migración ni archivo `.db` en esta etapa** — el
diseño de columnas de arriba es la única entrega.

## 13. Auditoría de solo lectura — quién puede escribir estas tablas

Solo `PaperTradingService` (a través de `SQLitePaperTradingRepository`)
puede escribir en las 8 tablas de §12. Ni el Dashboard, ni ningún motor
(`PaperTradingEngine`, `RiskEngine`), ni ninguna integración futura de IA
tienen acceso de escritura — exactamente el mismo principio que ya
protege `market_data`/`market_indicators`/`market_signals`/
`ai_recommendations` del Dashboard actual.

## 14. Integración con el Dashboard (sin implementar páginas nuevas)

Se extendería `DashboardRepository`/`SQLiteDashboardRepository` con
métodos de solo lectura nuevos, reutilizando los métodos de lectura de
`PaperTradingRepository` (nunca duplicando su SQL) — el mismo patrón
exacto que ya siguen `get_latest_signal`/`get_signal_history` hoy:

```python
get_latest_position(exchange, symbol) -> Optional[Position]
get_position_history(exchange, symbol, limit) -> list[PortfolioSnapshot]  # o PnLSnapshot
get_latest_portfolio_snapshot() -> Optional[PortfolioSnapshot]
get_portfolio_history(limit) -> list[PortfolioSnapshot]
get_order_history(exchange, symbol, limit) -> list[Order]
get_trade_history(exchange, symbol, limit) -> list[Trade]
```

Una futura página `src/dashboard/pages/paper_trading.py` (**no se crea en
esta etapa**) seguiría la misma arquitectura de página ya validada en las
5 páginas actuales: `DashboardService.get_paper_trading_page()` arma un
View Model (`PortfolioSummaryView`, reutilizando `Order`/`Trade`
directamente para el historial, mismo criterio que ya se aplicó con
`IndicatorSnapshot`/`SignalSnapshot`/`AIRecommendation`), un gráfico de
evolución del equity (`charts.line_chart()`, igual que el score de
Señales o la confianza de IA), y una tabla cronológica de
órdenes/trades (categóricos + montos, mismo criterio "tabla, no gráfico
engañoso" ya aplicado a señal/confianza/tendencia y a
recomendación/riesgo). Reutilizaría `layout.render_view_mode_selector()`
sin crear un selector de Vista propio.

**Garantía de solo lectura del Dashboard, sin excepción**: la extensión
de `DashboardRepository` **nunca** llamaría a `save_order`,
`update_order_status`, ni a ningún otro método de escritura de
`PaperTradingRepository` — el Dashboard jamás podría crear, modificar ni
cancelar una orden, ni ahora ni en ninguna etapa futura de Paper
Trading (esa capacidad, si alguna vez se agrega a una interfaz de
usuario, sería un cambio explícito y aprobado por separado, fuera del
rol de "panel de solo lectura" que el Dashboard tiene hoy).

## 15. Integración futura con IA (sin implementar todavía)

`AIRecommendation` (Etapa 4, ya aprobada) ya contiene todo lo que un
futuro `StrategyEngine` necesitaría para proponer una orden:
`recommendation` (seven niveles de `RecommendationAction`, de `Strong
Sell` a `Strong Buy`), `confidence` (0-100), `risk_level`. Nada de esto
se modifica en esta etapa.

**Cómo se preserva la trazabilidad desde el día 1** (aunque nada la use
todavía): `Order.source` (`OrderSource`: `MANUAL` / `AI_RECOMMENDATION` /
`STRATEGY`) y `Order.linked_recommendation_id` (§2.1) existen
precisamente para que, cuando se implemente un `StrategyEngine` en una
etapa futura, cada orden generada automáticamente pueda rastrearse hasta
la `AIRecommendation` exacta que la originó — sin tener que rediseñar el
modelo de `Order` en ese momento.

**La IA nunca ejecuta una orden directamente.** El flujo propuesto (para
una etapa futura, no esta) sería: `AIRecommendation` → (si
`paper_trading.auto_execute_ai_recommendations` está habilitado,
default `false`) → `StrategyEngine` traduce la recomendación en una
`Order` propuesta con `source=AI_RECOMMENDATION` → **la misma
`RiskEngine.validate()` de §8 la evalúa igual que cualquier otra
orden** — ninguna orden de origen IA se acepta sin pasar por el control
de riesgo. Esto replica exactamente el principio ya establecido en la
Etapa 4 ("la IA interpreta, nunca reemplaza al motor determinístico"):
aquí, "la IA puede proponer, nunca puede forzar la aceptación".

## 16. Estrategia de pruebas (diseño — ninguna prueba se escribe en esta etapa)

Seguiría la convención de nombres ya confirmada en `tests/`
(`test_<dominio>_<sujeto>.py`):

| Archivo propuesto | Qué cubre | Mismo patrón que |
|---|---|---|
| `test_paper_trading_models.py` | Validación Pydantic: `Field` (ge/le/gt/min_length), invariantes (`filled_quantity <= quantity`, coherencia `limit_price`/`order_type`), coerción de Enums. | `test_models_signal_data.py`, `test_ai_models.py` |
| `test_paper_trading_engine.py` | `PaperTradingEngine` puro: simulación de llenado MARKET/LIMIT, matemática de posición (aumentar/reducir/cerrar/revertir), cálculo de `Trade.realized_pnl` — con listas de `MarketTicker` en memoria, sin SQLite. | `test_indicator_engine.py`, `test_signals_*_rule.py`, `test_ai_decision_engine.py` |
| `test_paper_trading_risk.py` | `RiskEngine` en aislamiento: cada una de las 5 reglas de §8 por separado y combinadas, casos límite (exactamente en el borde de un límite). | `test_signals_aggregator.py` (reglas combinadas) |
| `test_paper_trading_service.py` | `PaperTradingService.run_cycle()` con un repositorio Fake (mismo patrón `FakeDashboardRepository`/Fake usados en `test_dashboard_service.py`/`test_signals_service.py`/`test_ai_service.py`). | `test_ai_service.py` |
| `test_paper_trading_sqlite_repository.py` | Round-trip de las 8 tablas, migración idempotente (3 llamadas a `init()`), aislamiento por símbolo/exchange. | `test_ai_sqlite_repository.py`, `test_signals_sqlite_repository.py` |
| `test_paper_trading_postgres_stub.py` | Confirma `NotImplementedError` en los 4+ métodos del stub. | `test_ai_postgres_stub.py` |
| `test_integration_paper_trading.py` | `build_services()` instancia (o no) `PaperTradingService` según `paper_trading.enabled`, igual que hoy con `ai_engine.enabled`; ciclo completo de punta a punta con datos de prueba. | `test_integration_full_cycle.py` |
| `test_dashboard_paper_trading_page.py` | (Cuando exista la página) AppTest de la página nueva, mismo patrón que las 5 páginas actuales. | `test_dashboard_signals_page.py` |

**Escenarios explícitos a cubrir antes de aceptar cualquier código de
Paper Trading como completo** (checklist para la etapa de
implementación, no para esta):

1. Las 9 transiciones válidas de estado (§4) ocurren correctamente; las 4
   inválidas se rechazan/no existen ningún camino de código que las
   produzca.
2. Ningún estado terminal (`FILLED`/`CANCELLED`/`REJECTED`/`EXPIRED`)
   vuelve a cambiar.
3. Simulación de llenado con 0, 1 y varios ticks de precio disponibles
   (incluyendo el caso "todavía no hay ningún `MarketTicker`").
4. Matemática de posición verificada con un ejemplo resuelto a mano
   (aumentar, reducir, cerrar, revertir) — no solo aserciones triviales.
5. `realized_pnl` vs `unrealized_pnl` no se confunden nunca (mismo
   cuidado conceptual que ya se documentó para `confidence` en la Etapa
   4, para no repetir esa clase de confusión).
6. Las 5 reglas de `RiskEngine` rechazan correctamente cada una por
   separado, y una orden puede fallar por más de una regla a la vez sin
   ambigüedad sobre cuál motivo se reporta.
7. `CashBalance.reserved_balance` nunca queda "atascado" (toda reserva se
   libera exactamente una vez: al llenarse, cancelarse o expirar).
8. Migraciones idempotentes verificadas con una base construida
   manualmente con un esquema anterior (igual que las 4 tablas
   existentes).
9. La extensión de solo lectura del Dashboard nunca puede escribir —
   verificado explícitamente igual que `tests/test_dashboard_readonly.py`
   ya hace con las 4 tablas actuales.
10. Ningún cambio de estado de una `Order` ocurre sin un evento
    correspondiente en `paper_trading_events` (§10).

## 17. Explícitamente fuera de esta etapa (6.0)

- ❌ Cualquier archivo `.py` de Paper Trading (modelos, motores,
  servicio, repositorio, configuración).
- ❌ Compra o venta, simulada o real.
- ❌ Cualquier tabla, migración o archivo de base de datos nuevo.
- ❌ Página de Dashboard nueva.
- ❌ Conexión a un `StrategyEngine`, Backtesting, Live Trading, Broker
  API real o WebSockets.
- ❌ Stop-loss/take-profit automáticos (el campo `max_loss_per_trade_pct`
  queda diseñado, pero su aplicación automática es una etapa futura).
- ❌ Multi-cuenta o multi-usuario (una sola cuenta de Paper Trading
  simulada).
- ❌ Cualquier modificación a `market_data`, `market_indicators`,
  `market_signals`, `ai_recommendations` o a las 6 páginas del Dashboard
  ya aprobadas.

## 18. Criterio de cierre de esta etapa (6.0)

Ver [ALCANCE_ETAPA_6.md](ALCANCE_ETAPA_6.md#criterio-de-cierre-de-la-etapa-60).
