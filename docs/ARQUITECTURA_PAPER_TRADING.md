# Arquitectura de Paper Trading (Etapa 6.0 — diseño; implementación en curso desde 6.1)

> **Este documento sigue siendo la referencia de diseño.** Lo que **sí
> existe ya**, implementado y con pruebas, es el dominio
> (`src/paper_trading/models.py`, `enums.py`, `validators.py`,
> `exceptions.py`, Etapa 6.1), los motores puros (`fill_engine.py`,
> `position_engine.py`, `pnl_engine.py`, `risk_engine.py`, Etapa 6.2), la
> persistencia SQLite (`base.py`, `sqlite_repository.py`,
> `postgres_repository.py`, `serialization.py`, Etapa 6.3), la capa de
> servicio (`service.py`/`PaperTradingService`, `service_results.py`,
> Etapa 6.4), la Composition Root con integración manual controlada
> (`composition.py`, `application.py`, `price_provider.py`,
> `runtime.py`, más una sección `paper_trading:` en `config.yaml` y una
> integración mínima en `main.py`, Etapa 6.5) y el Dashboard read-only
> (`src/dashboard/paper_trading_models.py`, `paper_trading_repository.py`,
> `paper_trading_service.py`, `pages/paper_trading.py`, Etapa 6.6) — ver
> las notas de implementación justo debajo. No hay compra ni venta real
> (con dinero real) en ninguna etapa de Paper Trading.

> **Nota de implementación (Etapa 6.6 — Dashboard read-only)**: la
> página "Paper Trading" del Dashboard (Streamlit) es estrictamente de
> consulta -- no existe ningún botón, formulario ni acción que pueda
> ejecutar, crear, cancelar o modificar una orden.
> - **Fuente de datos**: `RepositoryPaperTradingDashboardRepository`
>   envuelve `PaperTradingRepository` (Etapa 6.3) reutilizando
>   únicamente sus métodos de lectura (`get_cash_balance`,
>   `fetch_positions`, `fetch_orders`, `fetch_executions`, `fetch_trades`,
>   `fetch_portfolio_history`, `fetch_pnl_history`,
>   `calculate_realized_pnl`, `check_position_pnl_consistency`) — nunca
>   llama a `save_*`, `save_fill_transaction`, `seed_initial_cash_balance`
>   ni `.init()`. `get_status()` es la única consulta SQL propia (una
>   introspección `mode=ro` de `sqlite_master`, igual que
>   `SQLiteDashboardRepository.get_table_status()` de la Etapa 5),
>   necesaria para distinguir "nunca inicializado" de "inicializado pero
>   vacío".
> - **Sin `build_paper_trading_context()`**: el Dashboard construye
>   `SQLitePaperTradingRepository(database_path)` directamente, sin
>   llamar a ningún método de escritura — nunca siembra `CashBalance`
>   (verificado con una prueba dedicada, ver
>   `tests/test_paper_trading_dashboard_readonly.py`).
> - **Métricas del resumen**: `available_balance = total_balance -
>   reserved_balance`; `positions_value`/`total_equity`/
>   `unrealized_pnl_total`/`realized_pnl_cumulative` provienen siempre
>   del último `PortfolioSnapshot` persistido (nunca se recalculan); si
>   no existe ningún snapshot, esos campos quedan en `None` ("N/D" en
>   pantalla) — nunca se inventa un valor ni se consulta un precio
>   externo.
> - **Auditoría de PnL**: por cada `(exchange, symbol)` con `Position` y/o
>   `Trade`, se informa `Consistente`/`Inconsistente`/`Sin posición`/
>   `Sin trades`, comparando `Position.realized_pnl_to_date` contra
>   `calculate_realized_pnl()` (`SUM(Trade.net_pnl)` exacto en Decimal).
>   El indicador global solo se marca "Existen inconsistencias" ante una
>   fila explícitamente `Inconsistente` — un error real, detectado y
>   corregido durante esta etapa, contaba erróneamente `Sin trades` como
>   inconsistencia. El Dashboard nunca corrige una inconsistencia.
> - **Gráficos**: patrimonio/PnL realizado acumulado/PnL no realizado
>   provienen de la serie histórica de `PortfolioSnapshot` (no de
>   `PnLSnapshot`, que solo se usa para un detalle opcional por símbolo);
>   la distribución de PnL neto por símbolo suma `Trade.net_pnl` con
>   Decimal. `Decimal` se mantiene en toda la capa de servicio;
>   `float(...)` solo se aplica en la última línea antes de pasarle los
>   datos a Plotly.
> - **`enabled=false`**: se muestra una advertencia clara, pero los datos
>   históricos ya existentes se siguen mostrando con normalidad (nunca se
>   ocultan) — ningún control operacional aparece en ningún caso.
> - **Base sin tablas**: `get_status()` reporta `initialized=False`; la
>   página muestra "Paper Trading aún no ha sido inicializado" y no
>   intenta leer nada más, sin stacktrace.
> - **Automatización sigue sin existir**: `src/signals/`, `src/ai/` y el
>   resto del Dashboard no referencian `paper_trading` en absoluto
>   (auditoría de imports); `run_full_cycle()`/el scheduler de `main.py`
>   no cambiaron.
> - **Pendiente**: reserva real de `CashBalance.reserved_balance`/
>   `Position.reserved_quantity` (sigue en 0); cualquier ejecución desde
>   el Dashboard, Signals o IA; migración PostgreSQL real.

> **Nota de implementación (Etapa 6.5 — Composition Root e integración
> controlada)**: Paper Trading tiene, desde esta etapa, una forma real
> (aunque manual) de ejecutarse, sin que eso active nada automático.
> - **`PaperTradingConfig`** (`src/utils/config.py`, siguiendo el mismo
>   patrón `@dataclass(frozen=True)` que el resto de `Settings`) agrega
>   `config.yaml -> paper_trading` (`enabled`, `database_path`,
>   `initial_capital`, `currency`, `fee_rate`, `max_order_value`,
>   `max_position_value`, `rules_version`). Los 4 campos monetarios se
>   escriben **entre comillas** en el YAML a propósito: se leen como
>   `str` y se convierten con `Decimal(value)` directamente, nunca
>   pasando por `float` (evitando el error de precisión de convertir un
>   float ya impreciso). `enabled: false` es el valor por defecto.
> - **`build_paper_trading_context()`** (`src/paper_trading/
>   composition.py`) es la única función autorizada para construir
>   `SQLitePaperTradingRepository`/`PaperTradingService`/
>   `PaperTradingApplication` concretos: llama `repository.init()`,
>   siembra el capital inicial (`seed_initial_cash_balance()`, idempotente
>   -- nunca resetea ni duplica un saldo ya existente) y devuelve un
>   `PaperTradingContext` (repository + service + application + config).
>   No mantiene conexiones abiertas ni usa singletons.
> - **`Clock`/`IdGenerator`** (`src/paper_trading/runtime.py`, protocolos)
>   reemplazan `datetime.now()`/`uuid.uuid4()` directos dentro de
>   `application.py`/`composition.py`; `SystemClock`/`UUIDIdGenerator`
>   son las únicas implementaciones que sí los usan, inyectadas desde
>   `main.py`.
> - **`MarketPriceProvider`** (`src/paper_trading/price_provider.py`,
>   protocolo) + `RepositoryMarketPriceProvider` (adaptador real):
>   reutiliza `MarketDataRepository` ya existente (Etapa 1) para leer el
>   último `MarketTicker`, convirtiéndolo con `Decimal(str(value))`
>   (nunca `Decimal(value)` sobre un float). Sin conexión nueva a
>   Binance; falla explícitamente si no hay precio o si es ≤ 0.
> - **`PaperTradingApplication.submit_manual_market_order()`**
>   (`src/paper_trading/application.py`) es el único caso de uso de
>   aplicación: valida `enabled` primero (antes de precios/IDs/Order/
>   Service — `PaperTradingDisabledError`, definida en `application.py`,
>   no en `exceptions.py`, porque es un error de disponibilidad de caso
>   de uso, no un invariante de dominio), arma `Order(status=NEW,
>   order_type=MARKET)`, obtiene precios de todas las posiciones
>   abiertas no-FLAT más el símbolo operado, y delega el resto a
>   `PaperTradingService.submit_market_order()` sin recalcular nada.
> - **Integración con `main.py`**: `build_paper_trading(settings)` sigue
>   exactamente el criterio ya usado para `ai_engine.enabled` — si
>   `paper_trading.enabled` es `false`, no se instancia absolutamente
>   nada (ni el repositorio). El contexto devuelto queda disponible en
>   `main()` para uso manual/futuro; **ningún ciclo, señal ni
>   recomendación de IA lo invoca todavía** (confirmado por auditoría de
>   imports: `src/signals/`, `src/ai/` y `src/dashboard/` no referencian
>   `paper_trading` en absoluto).
> - **Pendiente para una etapa futura**: página de Dashboard de Paper
>   Trading; reserva real de `CashBalance.reserved_balance`/
>   `Position.reserved_quantity` (sigue en 0); scheduler o ejecución
>   automática desde señales/IA; migración real a PostgreSQL (el stub
>   sigue sin implementar).

> **Nota de implementación (Etapa 6.4 — servicio)**: `PaperTradingService`
> (`src/paper_trading/service.py`) es, desde esta etapa, **la única capa
> autorizada para ejecutar una orden de Paper Trading de punta a
> punta**: `submit_market_order()` obtiene `Position`/`CashBalance` del
> repositorio, invoca `RiskEngine.validate_order()`, `FillEngine.
> execute_market_order()`, `PositionEngine.apply_execution()`,
> `PnLEngine.build_portfolio_snapshot()`/`build_pnl_snapshot()`, y
> persiste el resultado completo con un único
> `PaperTradingRepository.save_fill_transaction()` — nunca abre una
> conexión SQLite directamente ni recalcula ninguna regla que ya viva en
> un motor. Precisiones sobre el flujo implementado, distintas del
> ciclo de vida completo descrito en §4/§9 (`NEW→PENDING` con reserva de
> capital/cantidad, luego `PENDING→FILLED` en un paso separado):
> - **Una sola llamada, sin reserva.** `submit_market_order()` valida y
>   llena en la misma invocación: la orden pasa por `PENDING`
>   únicamente en memoria (para satisfacer la precondición de
>   `FillEngine`), sin persistirse como estado intermedio, y sin tocar
>   `CashBalance.reserved_balance`/`Position.reserved_quantity` (quedan
>   en 0, igual que en 6.2/6.3). El ciclo de reserva-al-aceptar/
>   libera-al-llenar de §9 queda para una iteración futura que separe
>   "aceptar" de "llenar" en dos llamadas.
> - **Actualización de `CashBalance` en el servicio, no en el motor ni
>   en el repositorio**: `total_balance -= (cantidad×precio) + fee` en
>   BUY, `total_balance += (cantidad×precio) - fee` en SELL — la única
>   lógica de este tipo que vive fuera de un motor, porque ningún motor
>   de 6.2 conoce `CashBalance` (`PositionEngine` es explícito en no
>   conocerlo, ver position_engine.py).
> - **Snapshot de cartera con precios explícitos.** `current_prices` es
>   un parámetro opcional para cuando la cuenta tiene posiciones abiertas
>   en otros símbolos además del operado; si falta el precio de alguna,
>   `PnLEngine` falla explícitamente (nunca inventa un precio).
> - **Requiere `CashBalance` ya sembrado.** Si no existe una fila para la
>   moneda pedida, el servicio lanza `ValueError` en vez de inventar un
>   saldo inicial — sembrar `initial_capital` (§9.2) sigue siendo
>   responsabilidad de una futura Composition Root (`config.yaml`/
>   `main.py`, Etapa 6.5+), no de este servicio.
> - **Rechazos de riesgo son resultados, no excepciones**:
>   `SubmitOrderResult(success=False, risk_result=...)`, sin persistir
>   nada. Cualquier excepción (`OverFillError`, `InvalidOrderTransitionError`,
>   `PaperTradingDomainError`, `ValueError`, `sqlite3.IntegrityError`)
>   se propaga sin ocultarse.

> **Nota de implementación (Etapa 6.3 — persistencia)**: las 7 tablas
> (`paper_trading_orders`, `_executions`, `_trades`, `_positions`,
> `_cash_balances`, `_portfolio_snapshots`, `_pnl_snapshots`, ver §12)
> quedaron implementadas exactamente como se diseñó en §12.1, con estas
> confirmaciones concretas de código:
> - **Decimal como `TEXT`.** Todo campo monetario/cantidad se guarda con
>   `str(value)` y se reconstruye con `Decimal(value)`
>   (`serialization.py`) — nunca `REAL`, que perdería precisión.
> - **Históricos vía `INSERT`; estado actual vía `UPSERT`.**
>   `Execution`/`Trade`/`PortfolioSnapshot`/`PnLSnapshot` son
>   append-only (una colisión de PK falla con `IntegrityError`, nunca se
>   oculta con `OR REPLACE`/`OR IGNORE`); `Order`/`Position`/
>   `CashBalance` usan `INSERT ... ON CONFLICT DO UPDATE`
>   (`Order.created_at` nunca se sobrescribe en el upsert).
> - **`PRAGMA foreign_keys = ON`** en cada conexión; FK reales de
>   `paper_trading_executions.order_id` y
>   `paper_trading_trades.exit_execution_id`.
> - **`save_fill_transaction()`** implementa la Unit of Work de §12.2:
>   una única conexión, orden Order → Execution → Position →
>   CashBalance → Trade → PortfolioSnapshot → PnLSnapshot, un solo
>   `commit()` final, `rollback()` completo ante cualquier excepción
>   (verificado con pruebas que fuerzan una `Execution`/`Trade`
>   duplicada a mitad de la transacción).
> - **Fuente de verdad del PnL realizado confirmada en código**:
>   `paper_trading_trades` es la fuente histórica;
>   `Position.realized_pnl_to_date` es un estado materializado para
>   lectura rápida. `calculate_realized_pnl()` sólo lee `net_pnl` como
>   texto y suma con `Decimal` en Python (nunca `SUM()` en SQL sobre una
>   columna `TEXT`, que SQLite convertiría a `REAL`).
>   `check_position_pnl_consistency()` compara ambas fuentes sin
>   modificar ninguna; **no se recalcula automáticamente en cada
>   lectura** — cuándo reconciliar es decisión de un futuro Service
>   (Etapa 6.4).
> - **`PostgresPaperTradingRepository` sigue siendo un stub** (`NotImplementedError`
>   en los 21 métodos de la interfaz), sin ninguna dependencia nueva.
> - Persistencia implementada; **el `Service` que coordine motores +
>   repositorio todavía no existe** (Etapa 6.4).

> **Nota de implementación (Etapas 6.1 y 6.2)**: dos decisiones de esta
> sección quedaron implementadas de forma distinta a lo que este
> documento recomendaba, por decisión explícita del usuario al aprobar
> cada etapa (no por corrección de un error de la auditoría 6.0.1):
> - **Precisión numérica: `Decimal`, no `float`.** El punto 1 de
>   ["Decisiones aprobables antes de Etapa 6.1"](#20-decisiones-aprobables-antes-de-la-etapa-61)
>   recomendaba `float` con recomputo desde la fuente. El usuario
>   decidió `Decimal` en todo el dominio para la implementación real
>   (Etapa 6.1). Esto también hace irrelevante, en la práctica, el
>   riesgo de "deriva de redondeo" que motivaba evitar `+=` incremental
>   en `Position.realized_pnl_to_date` (§2.4): con `Decimal`, la suma
>   incremental es exacta. Aun así, `PositionEngine.apply_execution`
>   (Etapa 6.2) actualiza `realized_pnl_to_date` de forma incremental
>   **solo porque todavía no existe ningún repositorio** del cual
>   recalcularlo vía `SUM(Trade.net_pnl)` (§12.2) — cuando la Etapa 6.3
>   agregue persistencia, recalcular desde la fuente sigue siendo la
>   estrategia preferida y no exige cambiar esta función.
> - **`RiskEngine` no reserva nada.** §8 ya decía que el motor de riesgo
>   es puro; la Etapa 6.2 lo confirma en código: `RiskEngine.validate_order()`
>   no modifica `CashBalance.reserved_balance` ni
>   `Position.reserved_quantity` — devuelve únicamente un
>   `RiskValidationResult`. Reservar capital/cantidad al aceptar una
>   orden es responsabilidad de un futuro servicio (Etapa 6.4), todavía
>   sin construir.
>
> El resto de las decisiones de implementación de 6.1-6.2 (solo MARKET,
> solo LONG/FLAT, llenado del 100% del remanente en una sola ejecución,
> `Trade.fees` = solo la comisión de cierre, comisión de apertura no
> reasignada retroactivamente) coinciden exactamente con lo ya descrito
> en las secciones de abajo — no fue necesario cambiarlas.

> **Nota de revisión (Etapa 6.0.1 — auditoría de arquitectura)**: tras la
> versión original de este documento, se hizo una auditoría exhaustiva
> (matriz de estados, ejemplos numéricos de PnL, análisis de doble
> contabilización, transaccionalidad) que encontró 7 correcciones reales
> antes de aprobar la implementación: (1) `Trade` tenía un campo
> `entry_execution_ids` incompatible con el promedio ponderado ya descrito
> en §6 (bajo ese método no existen "lotes" de entrada individuales que
> rastrear) — eliminado; (2) `Trade.realized_pnl` no distinguía
> ganancia/pérdida bruta de comisiones — se separó en `gross_pnl`/`fees`/
> `net_pnl`; (3) `OrderBook` (simulado) resultó ser 100% redundante con
> `MarketTicker` (mismos 3 datos con otro nombre) — eliminado como
> entidad, el motor usa `MarketTicker` directamente; (4) faltaba una
> reserva de **cantidad** de posición para órdenes de venta que reducen un
> LONG (solo se reservaba capital, nunca cantidad) — se agregó
> `Position.reserved_quantity`; (5) no existía una decisión explícita
> sobre atomicidad: un fill afecta 5-6 tablas y necesita una transacción
> única (Unit of Work), no "un commit por método" como las 4 tablas
> existentes; (6) SHORT no tiene un modelo de margen/colateral definido
> (una posición corta simulada con solo 100% de colateral no acota la
> pérdida máxima, a diferencia de un LONG) — se recomienda diferir SHORT
> hasta diseñar ese modelo por separado; (7) faltaba precisar
> `float` vs `Decimal` y la estrategia de redondeo. El detalle completo
> de cada hallazgo, con ejemplos numéricos resueltos a mano, está aplicado
> directamente en las secciones de abajo (cada una indica explícitamente
> qué cambió y por qué). Ver la nueva sección
> ["Decisiones aprobables antes de Etapa 6.1"](#20-decisiones-aprobables-antes-de-la-etapa-61)
> al final de este documento para el resumen de lo que falta confirmar.

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

> **Corrección de auditoría (6.0.1)**: la versión original incluía
> `entry_execution_ids: list[str]`, asumiendo que un `Trade` podía
> rastrear qué ejecuciones de apertura específicas cerró. Esto es
> **incompatible** con el método de costeo que §6 ya establece (promedio
> ponderado, no FIFO/LIFO por lotes): bajo promedio ponderado, todas las
> entradas se mezclan en un solo `average_entry_price` y **no existen
> "lotes" individuales que un cierre pueda referenciar** — llevar
> `entry_execution_ids` habría sido información que parece precisa pero
> no se puede calcular correctamente (o habría forzado, en silencio, a
> implementar costeo FIFO más adelante, contradiciendo este documento).
> Se eliminó el campo: `entry_price` (ya presente) es suficiente bajo
> promedio ponderado — es exactamente "el costo base de la porción
> cerrada" que un método FIFO habría repartido entre varios lotes. Si una
> etapa futura decide cambiar a costeo FIFO/LIFO (fuera de alcance de
> 6.0-6.5), ese cambio debe rediseñar `Trade` explícitamente, no asumir
> que este campo ya lo soporta.
>
> También se separó `realized_pnl` (un solo número ambiguo sobre si
> incluía comisiones) en 3 campos explícitos, seguir el mismo criterio
> que el proyecto ya aplica en `SignalSnapshot` (nunca ocultar el detalle
> que explica un resultado final: guarda `reason`/`rule_strength` de cada
> regla, no solo el `score` agregado).

| Campo | Tipo | Notas |
|---|---|---|
| `id` | `str` (UUID) | |
| `exchange`, `symbol` | `str` | |
| `side` | `TradeSide` (enum) | `LONG` (`SHORT` queda reservado en el enum; ver §5.1 — diferido). |
| `quantity` | `float` | `Field(gt=0.0)`. Cantidad cerrada por este trade. |
| `entry_price` | `float` | Precio promedio de entrada (`Position.average_entry_price` en el momento del cierre) de la porción cerrada — bajo costeo por promedio ponderado, esto es lo único que existe como "precio de entrada": no hay lotes individuales que enumerar. |
| `exit_price` | `float` | Precio de la ejecución que cerró. |
| `gross_pnl` | `float` | `(exit_price - entry_price) × quantity × signo(side)` — solo precio, sin comisiones. |
| `fees` | `float` | `Field(ge=0.0)`. **Únicamente** la comisión de la ejecución que cerró (`exit_execution_id`); la comisión de apertura ya se descontó del efectivo en su momento y NO se vuelve a restar aquí (ver §6.1, "por qué no se cuentan las comisiones dos veces"). |
| `net_pnl` | `float` | `gross_pnl - fees`. **Este es el valor que se persiste como el PnL realizado oficial de este trade** (lo que otras tablas suman — ver §6.2, tabla de fuente de verdad). |
| `opened_at`, `closed_at` | `datetime` | |
| `exit_execution_id` | `str` | Trazabilidad hacia la ejecución que cerró (siempre exactamente 1: incluso en una reversión, ver §6, el cierre y la apertura del nuevo lado son eventos separados). |

### 2.4 `Position`

Estado agregado y **actual** (no histórico) de la exposición en un
símbolo, derivado de sus ejecuciones.

> **Corrección de auditoría (6.0.1)**: el diseño original solo
> reservaba **capital** (`CashBalance.reserved_balance`) al aceptar una
> orden, asumiendo implícitamente que toda orden es una compra. Una
> orden de **venta que reduce una posición LONG existente** no consume
> capital (no se está comprando nada) — consume **cantidad de la
> posición**: si dos órdenes de venta por 0.5 BTC cada una quedan
> `PENDING` simultáneamente sobre una posición de solo 0.7 BTC, sin una
> reserva de cantidad ambas pasarían la validación de riesgo y, al
> llenarse las dos, se "vendería" más de lo que realmente se tiene — el
> mismo error de "doble gasto" que la reserva de capital ya evita para
> compras, pero sin cubrir el lado de venta. Se agregó
> `reserved_quantity`, con el mismo ciclo de vida que
> `CashBalance.reserved_balance` (§9): se reserva al aceptar la orden de
> venta, se libera al llenarse/cancelarse/expirar.

| Campo | Tipo | Notas |
|---|---|---|
| `exchange`, `symbol` | `str` | Clave natural y primaria (una única fila por símbolo, para siempre — ver §12). |
| `side` | `PositionSide` (enum) | `LONG` / `FLAT` en el alcance inicial. `SHORT` queda reservado en el enum, sin usarse todavía (mismo criterio que `RecommendationAction`/`RiskLevel` ya reservan niveles sin usar) — ver §5.1, diferido hasta definir un modelo de margen. |
| `quantity` | `float` | `Field(ge=0.0)`. Siempre positiva; `side` da la dirección. **Invariante reforzada**: `quantity == 0` si y solo si `side == FLAT` (nunca `side=LONG` con `quantity=0`, ni viceversa) — se valida en el modelo, no solo por convención. |
| `reserved_quantity` | `float` | `Field(ge=0.0)`. Cantidad de `quantity` ya comprometida por órdenes de venta `PENDING`/`PARTIALLY_FILLED` que reducirían esta posición. **Invariante**: `reserved_quantity <= quantity`. La "cantidad realmente disponible para vender" es `quantity - reserved_quantity` (calculada, no persistida por separado). |
| `average_entry_price` | `Optional[float]` | `None` si y solo si `side=FLAT`. Recalculado en cada ejecución que **aumenta** la posición (promedio ponderado); no cambia con ejecuciones que la **reducen**. |
| `realized_pnl_to_date` | `float` | Caché de `SUM(Trade.net_pnl)` para este símbolo — nunca se actualiza incrementalmente (`+=`); se **recalcula desde `paper_trading_trades`** en cada actualización, para no acumular error de redondeo de `float` a lo largo de miles de operaciones (ver §6.3). |
| `opened_at` | `Optional[datetime]` | Cuándo pasó de `FLAT` a con cantidad, la vez más reciente. |
| `updated_at` | `datetime` | |

`unrealized_pnl` **no se persiste como campo de `Position`**: se calcula
al vuelo como `(precio_actual - average_entry_price) * quantity *
signo(side)`, usando el último `MarketTicker.price` — nunca un precio
guardado ni recalculado por otro módulo. Si se necesita historizarlo
para el Dashboard, eso es exactamente el propósito de `PnLSnapshot`
(§2.9), no de `Position`.

**Nota sobre reconstrucción (relevante para Backtesting, ver §14)**: a
diferencia de `realized_pnl_to_date` (una simple suma, siempre
recalculable con una consulta agregada), `quantity`/`average_entry_price`
**no** son una agregación trivial de `Execution` — dependen del **orden
exacto** en que ocurrieron las ejecuciones y de las reglas de §6
(aumentar/reducir/cerrar/revertir aplicadas secuencialmente). Reconstruir
una `Position` desde cero exige **repetir (replay) la historia ordenada
de `Execution` de ese símbolo a través del mismo motor**, no una
consulta `SUM`/`AVG` directa. Esto es intencional y es precisamente lo
que hace posible el Backtesting con el mismo motor (§14).

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

### 2.6 `OrderBook` (simulado) — **eliminado por auditoría (6.0.1)**

> **Corrección de auditoría**: se auditó si `OrderBook` era una entidad
> real o solo un envoltorio. Comparando sus 3 campos originales
> (`exchange`, `symbol`, `reference_price`, `timestamp`) contra
> `MarketTicker` (`exchange`, `symbol`, `price`, `queried_at`, ya
> existente y ya persistido en `market_data`), resultan **exactamente
> los mismos datos con otro nombre** — `OrderBook` no agregaba ninguna
> información nueva, solo un nivel de indirección. Se elimina como
> modelo: el motor de llenado (§9) recibe un `MarketTicker` directamente
> (el mismo que ya devuelve `MarketDataRepository`/`DashboardRepository`
> hoy), sin envoltorio intermedio. Esto también resuelve por sí solo la
> pregunta de nombre que plantea §9 ("¿es correcto llamarlo 'OrderBook'
> si no hay profundidad real?"): al no existir la entidad, no hay nombre
> que justificar.
>
> La limitación real (sin `bid`/`ask`, sin niveles de profundidad, el
> endpoint de Binance usado — `/api/v3/ticker/24hr` — no los provee)
> sigue plenamente vigente y se explica en detalle en §5; simplemente ya
> no requiere un modelo propio para documentarse.

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

> **Corrección de auditoría**: ¿`RiskLimits` debe ser configuración,
> modelo persistido, o ambas cosas? Sigue siendo **solo configuración**
> (`config.yaml`, una única versión "activa" a la vez, sin tabla propia)
> — pero esto por sí solo rompería la reproducibilidad de Backtesting y
> la auditoría histórica ("¿por qué se rechazó esta orden hace 3
> semanas, con qué límites?") si el archivo cambia con el tiempo. La
> resolución: **cada `RiskCheckResult` (§8) y su evento
> `RISK_CHECK_COMPLETED` (§10) incluyen una copia congelada de los
> valores de `RiskLimits` efectivamente usados en ese chequeo puntual**,
> dentro de su `payload`. Así, la configuración activa vive en un solo
> lugar (sin duplicarse en una tabla versionada, evitando
> sobreingeniería), y cada decisión histórica queda de todas formas
> perfectamente reconstruible desde el evento que la registró.

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

### Matriz de transiciones válidas (origen, destino, evento, precondiciones, efectos)

| Desde | Hacia | Evento que la provoca | Precondiciones | Efectos |
|---|---|---|---|---|
| `NEW` | `PENDING` | `RiskEngine.validate()` aprueba. | Orden recién creada, sin validar. | Reserva capital (compra) o `reserved_quantity` (venta que reduce, §2.4); evento `ORDER_ACCEPTED` + `RISK_CHECK_COMPLETED`. |
| `NEW` | `REJECTED` | `RiskEngine.validate()` rechaza. | Ídem. | `rejection_reason` fijado; **ninguna** reserva de capital/cantidad se realiza; evento `ORDER_REJECTED` + `RISK_CHECK_COMPLETED`. |
| `PENDING` | `PARTIALLY_FILLED` | El motor llena una parte de la cantidad restante. | `status ∈ {PENDING}`; `execution.quantity < quantity - filled_quantity`. | Ver §6 y la transacción única de §12.3. |
| `PENDING` | `FILLED` | El motor llena toda la cantidad restante en una sola ejecución. | `status ∈ {PENDING}`; `execution.quantity == quantity - filled_quantity`. | Ídem; libera cualquier reserva restante. |
| `PENDING` | `CANCELLED` | Cancelación explícita, sin ningún llenado previo. | `status == PENDING`; `filled_quantity == 0`. | Libera el 100% de la reserva (capital o cantidad); `cancellation_reason` fijado; evento `ORDER_CANCELLED`. |
| `PENDING` | `EXPIRED` | Se cumple `expires_at` sin ningún llenado. | `status == PENDING`; `expires_at` en el pasado; `filled_quantity == 0`. | Libera el 100% de la reserva; evento `ORDER_EXPIRED`. |
| `PARTIALLY_FILLED` | `FILLED` | El motor llena el remanente exacto. | `status == PARTIALLY_FILLED`; `execution.quantity == quantity - filled_quantity`. | Igual que arriba, sobre el remanente. |
| `PARTIALLY_FILLED` | `CANCELLED` | Cancelación explícita del remanente sin llenar. | `status == PARTIALLY_FILLED`. | Libera **solo la reserva del remanente** (lo ya llenado no se toca); `filled_quantity` **queda en el valor que ya tenía, mayor que 0** (ver casos especiales abajo). |
| `PARTIALLY_FILLED` | `EXPIRED` | Se cumple `expires_at` con remanente sin llenar. | `status == PARTIALLY_FILLED`; `expires_at` en el pasado. | Igual que `CANCELLED`, con `expires_at` como disparador en vez de una acción explícita. |

### Transiciones inválidas (deben rechazarse explícitamente en el motor)

| Transición inválida | Por qué |
|---|---|
| `NEW → FILLED` (saltando `PENDING`) | Toda orden debe pasar por una validación de riesgo auditable, aunque el llenado ocurra en el mismo ciclo — la transición a `PENDING` deja un evento propio (`ORDER_ACCEPTED`), necesario para la auditoría (§11). |
| `PARTIALLY_FILLED → REJECTED` | El rechazo solo tiene sentido **antes** de cualquier ejecución real; una vez que hubo un llenado parcial, la única salida es completar, cancelar o expirar el remanente. |
| Cualquier transición **desde** `FILLED`, `CANCELLED`, `REJECTED` o `EXPIRED` | Los 4 son estados terminales. Ninguna orden vuelve a cambiar de estado una vez alcanzado uno de estos — invariante que una prueba futura debe verificar explícitamente. |
| `PENDING → NEW` o `PARTIALLY_FILLED → PENDING` (retroceder) | El estado nunca retrocede; cada transición es un evento nuevo hacia adelante, nunca una corrección del pasado. |

### Casos especiales (Paso 4 de la auditoría)

- **Cancelación después de ejecución parcial**: **sí es válido** terminar
  `CANCELLED` con `filled_quantity > 0`. La cancelación solo afecta el
  **remanente** (`quantity - filled_quantity`): lo ya ejecutado se
  mantiene ejecutado (no se revierte ninguna `Execution` ni `Trade` ya
  generados). Se representa exactamente así: `status=CANCELLED`,
  `filled_quantity` conserva el valor que tenía al momento de cancelar
  (puede ser `> 0`), `cancellation_reason` describe que fue una
  cancelación **parcial** del remanente.
- **Expiración después de ejecución parcial**: idéntico razonamiento que
  la cancelación — `status=EXPIRED` con `filled_quantity > 0` es válido y
  esperado; solo el remanente se anula.
- **Rechazo de una orden parcialmente ejecutada**: **inválido** (ver
  tabla de arriba) — no existe ningún camino de código que permita
  `PARTIALLY_FILLED → REJECTED`.
- **Ejecución recibida después de cancelación**: el motor **nunca** debe
  generar una `Execution` para una orden que no esté en `PENDING` o
  `PARTIALLY_FILLED` en el instante de intentar el llenado — es una
  precondición dura de `simulate_fill()` (§9), verificada antes de
  escribir nada. Dado que todo el ciclo de un símbolo se procesa dentro
  de un único proceso Python sin concurrencia real (§12.3), este caso
  solo podría ocurrir por un error de programación, no por una
  condición de carrera genuina — pero el motor debe protegerse
  explícitamente de todas formas (falla ruidosa, nunca un llenado
  silencioso sobre una orden terminal).
- **`filled_quantity == quantity`**: transición a `FILLED` (cualquier
  camino: una sola ejecución total, o la última de varias parciales).
- **Múltiples fills**: soportado desde el diseño — `Execution` es 1:N
  respecto de `Order` precisamente para esto.
- **Fill mayor que la cantidad restante (over-fill)**: **debe rechazarse
  como un error del motor, nunca clampearse en silencio.** Invariante
  dura: `execution.quantity <= order.quantity - order.filled_quantity`
  en todo momento; si el motor de llenado alguna vez calculara una
  ejecución que la viole, es un defecto que debe fallar ruidosamente
  (excepción), no una entrada válida que se recorta silenciosamente —
  recortar en silencio ocultaría un bug real de cálculo en vez de
  exponerlo.
- **Reintentos idempotentes / doble procesamiento del mismo fill**: ver
  §12.2 (unicidad `(order_id, sequence_number)`) y §12.3 (transacción
  única por fill). Con ambos mecanismos, reintentar un ciclo que ya se
  aplicó por completo no puede duplicar una `Execution`: o el
  `Order.status` ya refleja el resultado (y un servicio bien escrito
  nunca reintenta sobre una orden que ya no está en un estado llenable),
  o, si de todas formas se intentara, la restricción `UNIQUE` de
  `paper_trading_executions` lo rechaza de forma ruidosa.

## 5. Limitación central: no existe un order book real

**Esta es la limitación de diseño más importante de todo el documento,
declarada explícitamente para no fingir una simulación más realista de
la que los datos permiten** (mismo criterio que ya se aplicó con ATR/ADX
en la Etapa 2 y con `DummyProvider` en la Etapa 4).

El proyecto solo consulta `/api/v3/ticker/24hr` de Binance (ver
`src/market/binance.py`), que entrega **un único precio** por símbolo y
ciclo (`MarketTicker.price`), sin `bid`/`ask`, sin niveles de
profundidad, y con una cadencia de minutos (`interval_minutes`), no en
tiempo real tick a tick. En consecuencia, el motor de llenado simulado
(§9 — antes descrito alrededor de un modelo `OrderBook` ya eliminado,
ver §2.6) **no simula profundidad de mercado real**:

- **Sin spread bid/ask**: compras y ventas se simulan al mismo precio de
  referencia (`MarketTicker.price`). Un futuro
  `paper_trading.simulated_spread_percent` (configurable, default `0.0`)
  podría aproximar un spread, pero eso es una decisión de diseño para la
  etapa de implementación, no de esta.
- **Órdenes MARKET**: se asume liquidez simulada infinita — se llenan
  100% al precio de referencia del ciclo actual, sin slippage salvo que
  se configure uno simulado explícitamente.
- **Órdenes LIMIT — diferidas a una iteración posterior (decisión de
  auditoría, ver §19)**: con solo un precio por ciclo (sin profundidad,
  sin saber si el precio "tocó" el límite entre dos ciclos y volvió),
  cualquier simulación de LIMIT sería una aproximación de baja fidelidad
  disfrazada de función completa. Siguiendo el mismo criterio ya usado
  en el proyecto para ATR/ADX y para `DummyProvider` ("mejor no
  implementar algo a medias que fingir que es preciso"), la
  recomendación de esta auditoría es que **la primera implementación
  (6.1-6.5) soporte únicamente `MARKET`**, y que `LIMIT` (con su
  comprobación de "toque" y sus llenados parciales) se diseñe con más
  detalle recién cuando se aborde explícitamente en una iteración
  futura.

### 5.1 SHORT — diferido a una iteración posterior (decisión de auditoría)

Al auditar los ejemplos numéricos de posiciones cortas (ver §6.2), se
encontró que **una posición SHORT no puede simularse de forma segura
con el modelo de `CashBalance` de este documento (§2.5, §9), que asume
una cuenta de solo efectivo (cash account) sin margen**. Una venta en
corto real recibe efectivo al abrir pero conlleva una obligación de
recomprar más tarde, con **pérdida potencialmente ilimitada** si el
precio sube — a diferencia de un LONG, donde la pérdida máxima está
acotada por el capital invertido (el precio no puede bajar de 0). Ni
siquiera reservar el 100% del valor nocional como "colateral" al abrir
un SHORT acota correctamente ese riesgo (el precio puede subir por
encima de esa reserva). Simularlo de forma responsable requeriría un
modelo de margen (colateral de mantenimiento, llamadas de margen o
liquidación forzosa) que este documento no diseña.

**Recomendación de esta auditoría**: la primera implementación
(6.1-6.5) soporta **únicamente posiciones LONG**. `PositionSide.SHORT` y
`TradeSide.SHORT` quedan reservados en sus enums (sin usarse), y las
fórmulas de §6.2 se presentan igualmente para SHORT (para dejar
constancia de que la matemática de PnL ya está pensada para ambos
sentidos), pero **su implementación y el diseño del modelo de margen
correspondiente quedan explícitamente fuera de esta ronda de
aprobación** (ver §17 y §19).

## 6. Modelo de posiciones — detalle de cálculo

### 6.1 Reglas generales

- **Aumentar una posición** (ejecución en el mismo sentido que la
  posición actual, o abrir una nueva desde `FLAT`): el nuevo
  `average_entry_price` es el promedio ponderado por cantidad:
  `(qty_vieja × precio_viejo + qty_nueva × precio_nuevo) / (qty_vieja +
  qty_nueva)`. No genera `Trade` (no se cierra nada). **La comisión de
  esta ejecución de apertura se descuenta del efectivo (§9) en el
  momento, pero no se incorpora al `average_entry_price`** (el precio
  promedio es un precio puro, sin comisiones mezcladas) — ver más abajo
  "por qué no se cuentan las comisiones dos veces".
- **Reducir una posición** (ejecución en sentido contrario, cantidad
  menor a la posición abierta): genera un `Trade` por la cantidad
  cerrada, con:
  - `gross_pnl = (precio_ejecución - average_entry_price) × cantidad_cerrada × signo(side)`
  - `fees = fee de esta ejecución de cierre únicamente`
  - `net_pnl = gross_pnl - fees` (este es el valor que se persiste como `Trade.net_pnl`)

  `average_entry_price` de la posición **no cambia** (sigue siendo el de
  la porción que queda abierta); `reserved_quantity` (§2.4) se libera en
  la cantidad correspondiente.
- **Cerrar completamente una posición** (ejecución en sentido contrario,
  cantidad igual a la posición abierta): igual que reducir, pero
  `Position` vuelve a `side=FLAT`, `quantity=0`,
  `average_entry_price=None`, `reserved_quantity=0`.
- **Revertir una posición** (ejecución en sentido contrario, cantidad
  mayor a la posición abierta): se trata como **cerrar** la posición
  existente (genera `Trade`) y luego **abrir** una nueva en el sentido
  contrario con el remanente de la ejecución, con su propio
  `average_entry_price` nuevo. No se mezclan ambos tramos en un solo
  cálculo — son dos operaciones matemáticamente independientes aplicadas
  en secuencia dentro de la misma transacción (§12.3). **Diferida junto
  con SHORT (§5.1)** cuando la reversión implica cruzar a un sentido que
  todavía no se soporta.

### 6.2 ¿Por qué no se cuentan las comisiones dos veces?

La comisión de **abrir** una posición ya se descontó del efectivo en el
momento de esa ejecución (§9) — es un costo ya "realizado" como salida
de caja, aunque la posición siga abierta. Al **cerrar** (total o
parcialmente), solo la comisión de **esa** ejecución de cierre entra en
`Trade.fees`. Si se restara también la comisión de apertura en el
`Trade` de cierre, se contaría dos veces el mismo costo (una vez como
salida de caja al abrir, otra vez dentro del PnL realizado al cerrar).

**Consecuencia documentada explícitamente**: `unrealized_pnl` (calculado
como `(precio_actual - average_entry_price) × quantity × signo(side)`,
ver §2.4) es una referencia de precio puro — **no** descuenta la
comisión de apertura ya pagada ni una comisión de cierre estimada. No
debe interpretarse como "lo que se realizaría exactamente si se cerrara
ahora mismo"; para eso habría que restarle la comisión de cierre
estimada. Esta distinción se documenta para que un futuro Dashboard no
muestre el número equivocado con una etiqueta engañosa.

### 6.3 Ejemplos numéricos resueltos a mano (LONG; fee simulado = 0.1%)

Todos los ejemplos parten de una cuenta con `initial_capital = 10 000`
(ver §9). Las columnas muestran el estado **después** de aplicar cada
ejecución.

| # | Escenario | Posición antes | Ejecución | Posición después | `Trade` (gross / fees / net) | Efectivo tras la ejecución |
|---|---|---|---|---|---|---|
| 1 | Apertura LONG | FLAT (qty 0) | BUY 0.1 @ 50 000, fee 5 | LONG qty 0.1 @ 50 000 | — (no cierra nada) | 10 000 − 5 005 = **4 995** |
| 2 | Aumento de LONG | LONG qty 0.1 @ 50 000 | BUY 0.05 @ 52 000, fee 2,60 | LONG qty 0.15 @ **50 666,67** (`(0.1×50000+0.05×52000)/0.15`) | — | 4 995 − 2 602,60 = **2 392,40** |
| 3 | Reducción parcial de LONG | LONG qty 0.15 @ 50 666,67 | SELL 0.05 @ 53 000, fee 2,65 | LONG qty 0.10 @ 50 666,67 (sin cambio) | gross = (53000−50666,67)×0,05 = 116,67 / fees 2,65 / **net 114,02** | 2 392,40 + (2 650 − 2,65) = **5 039,75** |
| 4 | Cierre total de LONG | LONG qty 0.10 @ 50 666,67 | SELL 0.10 @ 54 000, fee 5,40 | FLAT (qty 0, precio `None`) | gross = (54000−50666,67)×0,10 = 333,33 / fees 5,40 / **net 327,93** | 5 039,75 + (5 400 − 5,40) = **10 434,35** |

Verificación de consistencia (§6.4): `realized_pnl_to_date` tras los
ejemplos 3+4 = 114,02 + 327,93 = **441,95**. Efectivo final 10 434,35 =
`initial_capital (10 000) + realized_pnl_to_date (441,95) − comisiones
de apertura ya pagadas y no reflejadas en realized_pnl (5 + 2,60 = 7,60,
ya restadas del efectivo en los pasos 1-2, ninguna posición abierta al
final para "deberlas")` → 10 000 + 441,95 − 7,60 = 10 434,35 ✓. La
cuadratura exacta, ejecución por ejecución, es precisamente la prueba
que `test_paper_trading_engine.py` (§16) debe automatizar.

### 6.4 SHORT — fórmulas espejo (documentadas, no implementadas — ver §5.1)

Mismas reglas que §6.1, con `signo(LONG) = +1` y `signo(SHORT) = -1` en
la fórmula general `gross_pnl = (precio_salida − precio_entrada) ×
cantidad × signo(side)`: abrir un SHORT es una venta que aumenta la
posición corta (mismo cálculo de promedio ponderado); reducir/cerrar un
SHORT es una compra ("buy to cover") que genera un `Trade` con
`side=SHORT`. Los escenarios 5-8 (apertura/aumento/reducción/cierre de
SHORT) y 9-10 (reversión LONG↔SHORT) de esta auditoría se resuelven con
la misma aritmética que la tabla de §6.3, cambiando el signo — **no se
tabulan aquí en detalle porque no se implementan hasta que exista un
modelo de margen (§5.1)**, y tabular ejemplos numéricos completos de
algo que no se va a construir todavía sería documentación que se
desactualiza sin uso real.

## 7. Modelo de cartera (Portfolio)

Como se explicó en §2, `Portfolio` es la combinación en memoria de
`CashBalance` + `list[Position]` vigentes, no una tabla propia:

```
total_equity = cash_balance.available_balance
             + cash_balance.reserved_balance
             + Σ (position.quantity × precio_actual del símbolo)  [solo posiciones no-FLAT]
```

Como `available_balance + reserved_balance == total_balance` por
definición (§2.5), esto es equivalente a `total_equity =
cash_balance.total_balance + Σ (position.quantity × precio_actual)` — la
misma fórmula que ya aparecía aquí, solo que ahora explícitamente
conciliada con el invariante contable de §9
(`equity = available_cash + reserved_cash + market_value_positions`).

`PaperTradingService` es quien arma este objeto en memoria bajo demanda
(para pasarlo a `RiskEngine.validate()` o para generar un
`PortfolioSnapshot`), leyendo `CashBalance` + todas las `Position` desde
el repositorio — nunca se persiste como una entidad combinada.

## 8. Riesgo

`RiskEngine` (motor puro, sin I/O, mismo espíritu que `IndicatorEngine`/
`SignalEngine`/`DecisionEngine`) **nunca modifica una orden, la cartera
ni la base de datos directamente** — solo lee los datos que se le pasan
como parámetros y devuelve un veredicto (`RiskCheckResult`). Quien aplica
ese veredicto (reservar capital, marcar `REJECTED`, etc.) es
`PaperTradingService`, no el motor.

### 8.1 Validaciones previas a aceptar una orden (bloqueantes)

En este orden (falla en la primera que no se cumpla):

1. **Cantidad por operación**: `RiskLimits.min_order_quantity <=
   order.quantity <= RiskLimits.max_order_quantity`.
2. **Disponibilidad de recursos — corregida por auditoría**: depende del
   sentido de la orden, no es siempre "capital":
   - **Compra, o venta que abre/aumenta exposición** (en el alcance
     LONG-únicamente de 6.1-6.5, esto es siempre una compra): el
     notional estimado (`quantity × precio_referencia`, más una
     estimación de `fee`) no puede superar
     `CashBalance.available_balance`.
   - **Venta que reduce una posición LONG existente**: `order.quantity
     <= Position.quantity - Position.reserved_quantity` (§2.4) — esto
     **no** consume capital, consume cantidad de la posición. Antes de
     esta auditoría, el diseño original solo validaba capital y nunca
     cantidad, lo que habría permitido "vender" más de lo realmente
     disponible con dos órdenes de venta simultáneas (ver §2.4).
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
stop-loss automático debería consultar — diseño explícitamente fuera del
alcance de esta etapa (ver §17, "Explícitamente fuera de esta etapa";
corregida la referencia cruzada de la versión original, que apuntaba
por error a §15).

### 8.2 Validaciones posteriores a un fill (defensivas, no bloqueantes)

Dado que este proyecto procesa un ciclo a la vez en un único proceso sin
concurrencia real (§12.3), una violación de límites **después** de un
fill ya aplicado no debería ocurrir en la práctica — pero el diseño no
asume que "no debería pasar" es lo mismo que "nunca pasa". Tras aplicar
un fill, `PaperTradingService` vuelve a evaluar exposición/posición
resultante como una **verificación de integridad**, no como una
segunda oportunidad de rechazo (el fill ya ocurrió, el dinero simulado
ya se movió): si detecta una violación, emite `RISK_LIMIT_BREACHED`
como alerta para revisión humana, sin revertir nada.

### 8.3 Alertas de monitoreo (informativas, no bloqueantes)

Ej.: pérdida diaria acumulada superó el 80% de `max_daily_loss_pct`, o
la exposición de cartera superó el 80% de `max_portfolio_exposure_pct`.
Se emiten como eventos informativos (§10) para un futuro banner de alerta
en el Dashboard — no bloquean ninguna orden todavía.

### 8.4 Acciones automáticas futuras (NO implementadas)

Auto-liquidación al violar un stop-loss/take-profit, auto-cierre de
posiciones al activarse el circuit breaker diario. Fuera de alcance de
esta etapa y de las iteraciones 6.1-6.5 (ver §17).

### 8.5 `RiskCheckResult` — forma exacta del resultado

```python
RiskCheckResult(
    approved: bool,
    code: str,              # ej. "OK", "INSUFFICIENT_CAPITAL", "MAX_POSITION_EXCEEDED"
    message: str,            # texto legible para logs/auditoría
    metrics_used: dict,       # ej. {"available_balance": 4995.0, "order_notional": 5005.0}
    limits_used: dict,        # copia congelada de los RiskLimits vigentes en este chequeo (ver §2.7)
    timestamp: datetime,
    rules_version: str,       # bump manual si el conjunto de reglas cambia de forma significativa
)
```

Todo `RiskCheckResult` (aprobado o rechazado) genera un evento
`RISK_CHECK_COMPLETED` (§10) con este mismo contenido en el `payload` —
es la forma en que este diseño logra reproducibilidad histórica sin
necesitar una tabla de configuración versionada (§2.7).

## 9. Capital disponible

### 9.1 Qué se guarda y qué se calcula

| Campo | Naturaleza |
|---|---|
| `total_balance` | Guardado (ledger acumulado de movimientos de caja). |
| `reserved_balance` | Guardado (suma de reservas activas). |
| `available_balance` | **Calculado**: `total_balance - reserved_balance`. Nunca un campo propio. |
| `initial_capital` | Guardado **una sola vez**, al inicializar la cuenta (ver 9.2) — nunca se vuelve a escribir. |

### 9.2 Capital inicial (`initial_capital`) — pieza faltante en el diseño original

La versión original de este documento no explicaba de dónde sale el
primer valor de `CashBalance.total_balance`. Se agrega
`paper_trading.initial_capital` (config, ej. `10000.0`): la primera vez
que `SQLitePaperTradingRepository.init()` se ejecuta y no encuentra
ninguna fila en `paper_trading_cash_balance`, siembra una única fila con
`total_balance = initial_capital`, `reserved_balance = 0`. Ejecuciones
posteriores de `init()` **no** reinician este valor (mismo criterio de
idempotencia que ya usan las 4 tablas existentes: `init()` nunca
sobrescribe datos ya guardados).

### 9.3 Libro contable conceptual (con el ejemplo numérico de §6.3)

| Evento | `total_balance` | `reserved_balance` | `available_balance` |
|---|---|---|---|
| Depósito inicial (`initial_capital=10 000`) | 10 000 | 0 | 10 000 |
| Orden BUY 0.1 @ ~50 000 aceptada (`NEW→PENDING`) | 10 000 | +5 005 → 5 005 | 4 995 |
| Ejecución de compra (fill @ 50 000, fee 5) | 10 000−5 005 = **4 995** | −5 005 → 0 | 4 995 |
| Orden BUY 0.05 @ ~52 000 aceptada | 4 995 | +2 602,60 | 2 392,40 |
| Ejecución de compra (fill @ 52 000, fee 2,60) | 4 995−2 602,60 = **2 392,40** | −2 602,60 → 0 | 2 392,40 |
| Orden SELL 0.05 (reduce) aceptada — **reserva cantidad, no capital** (§8.1) | 2 392,40 (sin cambio) | 0 (sin cambio) | 2 392,40 |
| Ejecución de venta (fill @ 53 000, fee 2,65) | 2 392,40+2 647,35 = **5 039,75** | 0 | 5 039,75 |
| Cancelación de una orden BUY hipotética 0.02 @ ~1002 antes de llenar | 5 039,75 (sin cambio) | −1 002 (se libera) | +1 002 |
| Expiración de una orden `PENDING` sin llenar | Sin cambio | Se libera lo reservado del remanente | Aumenta en lo liberado |
| Rechazo de una orden (`RiskEngine` la rechaza) | Sin cambio | **Nunca llegó a reservarse** | Sin cambio |

### 9.4 Invariantes

```
available_balance >= 0
reserved_balance   >= 0
total_balance      == available_balance + reserved_balance   (por construcción, no una coincidencia a verificar)
equity             == available_balance + reserved_balance + market_value_positions
                    == total_balance + market_value_positions
```

Con el alcance LONG-únicamente de esta ronda (§5.1), `available_balance`
nunca puede volverse negativo por una pérdida de una posición ya
abierta: el máximo que un LONG puede perder está acotado por el capital
ya invertido (el precio no puede bajar de 0). Este invariante **no**
se sostiene automáticamente si en el futuro se agrega SHORT sin un
modelo de margen — otra razón, además de la ya dada en §5.1, para no
implementarlo todavía.

### 9.5 Reserva de cantidad (Position.reserved_quantity) — ciclo de vida espejo

Mismo mecanismo que 9.3, aplicado a `Position.reserved_quantity` (§2.4)
en vez de `CashBalance.reserved_balance`, para órdenes de venta que
reducen una posición:

1. **Al aceptar la orden de venta** (`NEW → PENDING`):
   `reserved_quantity += order.quantity`.
2. **Al llenarse (total o parcialmente)**: `reserved_quantity -=
   execution.quantity` (se libera); `Position.quantity` se reduce por la
   misma cantidad (§6.1).
3. **Al cancelar o expirar el remanente**: `reserved_quantity -=
   remanente_no_llenado` (se libera sin afectar `Position.quantity`,
   porque nunca se vendió).

Esto evita, para el lado de venta, el mismo error de "doble gasto" que
la reserva de capital ya evitaba solo para el lado de compra: sin esta
reserva, dos órdenes de venta `PENDING` simultáneas sobre la misma
posición podrían ambas pasar la validación de riesgo usando la misma
cantidad, y llenarse ambas "vendiendo" más de lo que realmente se tiene.

## 10. Eventos del sistema

> **Corrección de auditoría (6.0.1)**: el modelo original carecía de
> `aggregate_id`/`aggregate_type` (no se podía saber a qué entidad
> pertenece un evento sin adivinarlo de `order_id`), de
> `correlation_id`/`causation_id` (no se podía reconstruir la cadena
> "esta orden causó este fill que causó este cierre de posición"), y de
> `schema_version` (no habría forma de evolucionar el `payload` sin
> romper lectores antiguos). Se agregan los cuatro. También faltaban los
> eventos de riesgo y snapshot que Paso 8/12 requieren
> (`RISK_CHECK_COMPLETED`, `PORTFOLIO_SNAPSHOT_CREATED`) y el de
> reversión (`POSITION_REVERSED`, documentado pero sin uso mientras
> SHORT esté diferido — ver §5.1).
>
> **Aclaración explícita de alcance (Paso 11)**: esta tabla es un
> **híbrido de evento de dominio + auditoría**, no _Event Sourcing_: el
> estado autoritativo de una `Order`/`Position`/`CashBalance` vive en sus
> tablas mutables (§12), no se reconstruye jamás reproduciendo eventos
> desde cero. Tampoco es un mecanismo de **integración** (no hay bus de
> eventos, no hay suscriptores, nadie reacciona a un evento publicado
> aquí): es un registro append-only de lo que ya ocurrió, para
> trazabilidad y auditoría. Diseñar un Event Sourcing completo sería
> sobreingeniería para el alcance de Paper Trading (Paso 11, YAGNI).

Registro de eventos append-only (nunca se actualiza ni se borra una fila
ya escrita) — la misma tabla cumple el rol de auditoría (§11), sin
duplicar información en dos lugares.

**Tipos de evento propuestos** (`PaperTradingEventType`, enum, en
`SCREAMING_SNAKE_CASE` para ser consistente con la matriz de
transiciones de §4): `ORDER_CREATED`, `ORDER_ACCEPTED`, `ORDER_REJECTED`,
`ORDER_PARTIALLY_FILLED`, `ORDER_FILLED`, `ORDER_CANCELLED`,
`ORDER_EXPIRED`, `POSITION_OPENED`, `POSITION_INCREASED`,
`POSITION_REDUCED`, `POSITION_CLOSED`, `POSITION_REVERSED` (reservado,
sin uso mientras SHORT esté diferido, §5.1), `RISK_CHECK_COMPLETED`,
`PORTFOLIO_SNAPSHOT_CREATED`, `CASH_BALANCE_ADJUSTED`.

**Modelo `PaperTradingEvent`**:

| Campo | Tipo | Notas |
|---|---|---|
| `id` | `str` (UUID) | |
| `event_type` | `PaperTradingEventType` | |
| `aggregate_type` | `str` | `"order"` / `"position"` / `"cash_balance"` / `"portfolio"` — a qué tipo de entidad pertenece este evento. |
| `aggregate_id` | `str` | El `id` de esa entidad (`order_id`, `f"{exchange}:{symbol}"` para posición, etc.) — reemplaza la ambigüedad del `order_id` opcional original. |
| `timestamp` | `datetime` | |
| `exchange`, `symbol` | `Optional[str]` | `None` para eventos de cuenta completa (ej. circuit breaker). |
| `order_id` | `Optional[str]` | Si aplica (puede diferir de `aggregate_id` si el evento es de una posición, no de la orden). |
| `correlation_id` | `str` | Mismo valor para todos los eventos que se originan en una misma operación de negocio (ej. un fill que genera `ORDER_FILLED` + `POSITION_REDUCED` + `CASH_BALANCE_ADJUSTED` comparten `correlation_id`) — permite reconstruir la cadena completa de una operación. |
| `causation_id` | `Optional[str]` | El `id` del evento que directamente causó este (ej. `POSITION_REDUCED` fue causado por el evento `ORDER_PARTIALLY_FILLED` correspondiente). `None` para el primer evento de una cadena. |
| `schema_version` | `int` | Versión del formato de `payload` para este `event_type` (empieza en `1`); permite evolucionar el payload sin romper lectores de eventos antiguos. |
| `description` | `str` | Texto legible (mismo criterio que `reason`/`summary` ya usados en Señales/IA). |
| `payload` | `dict` | Serializado como JSON en una columna `TEXT` (mismo patrón que `advantages`/`risks` de `ai_recommendations`): datos estructurados específicos del evento (ej. cantidades, precios; para `RISK_CHECK_COMPLETED`, el `RiskCheckResult` completo de §8.5). |

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

**No se crea ninguna migración ni archivo `.db` en esta etapa** — el
diseño de columnas de abajo es la única entrega.

### 12.1 Detalle por tabla (Paso 10 de la auditoría)

| Tabla | PK | Claves lógicas / FK | UNIQUE | NOT NULL relevantes | Índices |
|---|---|---|---|---|---|
| `paper_trading_orders` | `id` (UUID) | `linked_recommendation_id` → `ai_recommendations.id` (lógica, sin FK real entre módulos, mismo criterio que el resto del proyecto no usa FKs físicas entre tablas) | — | `exchange`, `symbol`, `side`, `order_type`, `quantity`, `status`, `created_at` | `(exchange, symbol, status)` para listar órdenes abiertas por símbolo; `(status)` para el barrido de expiración. |
| `paper_trading_executions` | `id` (UUID) | `order_id` → `paper_trading_orders.id` (lógica) | **`(order_id, sequence_number)`** — garantiza idempotencia: un mismo fill no puede insertarse dos veces con la misma secuencia (Paso 4/10, ver casos especiales §4). | `order_id`, `sequence_number`, `quantity`, `price`, `fee`, `executed_at` | `(order_id)` para reconstruir el historial de fills de una orden en orden. |
| `paper_trading_trades` | `id` (UUID) | `exit_execution_id` → `paper_trading_executions.id` (lógica) | — | `exchange`, `symbol`, `side`, `quantity`, `entry_price`, `exit_price`, `gross_pnl`, `fees`, `net_pnl`, `closed_at` | `(exchange, symbol, closed_at)` para el historial de PnL por símbolo. |
| `paper_trading_positions` | `(exchange, symbol)` compuesta | — | Implícita por ser la PK: **una sola fila activa por `(exchange, symbol)`** (Paso 10), incluso en `FLAT` (no se borra la fila al cerrar, se actualiza `quantity=0`/`side=FLAT`, para conservar `realized_pnl_to_date`). | `quantity`, `reserved_quantity`, `side`, `realized_pnl_to_date`, `updated_at` | Ya cubierta por la PK compuesta. |
| `paper_trading_cash_balance` | fila única (`id` fijo, ej. `1`, o `CHECK (id = 1)`) | — | Implícita: una sola fila para toda la tabla. | `total_balance`, `reserved_balance`, `initial_capital`, `updated_at` | Ninguno necesario (una fila). |
| `paper_trading_portfolio_snapshots` | `id` (UUID) | — | `(snapshot_at)` si los snapshots son uno por ciclo y no deben duplicarse en el mismo timestamp | `snapshot_at`, `total_equity`, `available_balance`, `reserved_balance` | `(snapshot_at)` para series temporales del Dashboard. |
| `paper_trading_pnl_snapshots` | `id` (UUID) | — | `(exchange, symbol, snapshot_at)` — un snapshot por símbolo por ciclo, no más | `exchange`, `symbol`, `snapshot_at`, `realized_pnl`, `unrealized_pnl` | `(exchange, symbol, snapshot_at)`. |
| `paper_trading_events` | `id` (UUID) | `aggregate_id` (lógica, ver §10) | — | `event_type`, `aggregate_type`, `aggregate_id`, `correlation_id`, `schema_version`, `timestamp` | `(aggregate_id, timestamp)` para reconstruir la historia de una entidad; `(correlation_id)` para reconstruir una operación completa. |

`paper_trading_orders` **no** necesita una tabla separada de historial
de transiciones: `paper_trading_events` (una fila `ORDER_*` por
transición, con `aggregate_id=order.id`) ya cumple ese rol — crear una
segunda tabla de historial sería duplicar información que los eventos
ya capturan (Paso 10, evitar redundancia).

### 12.2 Atomicidad de un fill — Unit of Work (corrección de auditoría)

> El diseño original no especificaba si aplicar un fill era una o varias
> transacciones SQLite independientes. Copiar ciegamente el patrón
> actual del proyecto ("una conexión nueva y un `commit()` por método")
> sería **incorrecto** aquí: las 4 tablas existentes son append-only e
> independientes entre sí (un commit parcial nunca deja una
> inconsistencia entre tablas), pero aplicar un fill escribe/actualiza
> hasta 6 tablas relacionadas (`executions`, `orders`, `positions`,
> `cash_balance`, opcionalmente `trades`, `events`) que **deben
> avanzar juntas o no avanzar ninguna** — un corte de proceso a mitad de
> camino no puede dejar, por ejemplo, una `Execution` guardada sin que
> `CashBalance` se haya actualizado.

Se propone un único método transaccional en el repositorio, ej.:

```python
def apply_fill(
    self,
    order: Order,
    execution: Execution,
    position: Position,
    cash_balance: CashBalance,
    trade: Optional[Trade],
    events: list[PaperTradingEvent],
) -> None:
    """Escribe Execution + Order + Position + CashBalance + (Trade) +
    Events en una única transacción SQLite (una conexión, un commit al
    final, rollback completo si cualquier INSERT/UPDATE falla)."""
```

`PaperTradingEngine`/`RiskEngine` (motores puros) calculan los nuevos
valores en memoria; `PaperTradingService` construye los objetos
resultantes y se los pasa a `apply_fill()` como la única operación de
escritura de todo el ciclo de "procesar un fill" — nunca se llama a
`save_execution()`/`update_order_status()`/etc. por separado para un
mismo fill. El mismo criterio aplica a aceptar una orden (reserva de
cash o de cantidad + `ORDER_ACCEPTED`) y a cancelar/expirar (liberar
reserva + evento): cualquier operación que toque más de una tabla usa un
método transaccional dedicado, nunca una secuencia de métodos
independientes desde el servicio.

### 12.3 Concurrencia

El proyecto ejecuta un ciclo a la vez, en un solo proceso, sin hilos ni
tareas paralelas (mismo modelo que `run_full_cycle()` hoy). No hay
acceso concurrente real a estas tablas que resolver en esta ronda —
la Unit of Work de 12.2 es sobre todo una garantía de **atomicidad ante
fallos** (un crash a mitad de un fill), no una solución a condiciones de
carrera entre procesos. Si en el futuro se agrega un segundo proceso
(ej. un worker de Backtesting corriendo en paralelo al de Paper Trading
en vivo), esa es una decisión explícitamente fuera de esta auditoría.

**Repositorio propuesto**: `PaperTradingRepository` (interfaz en un
`src/paper_trading/base.py`), con `SQLitePaperTradingRepository`
(implementación) y `PostgresPaperTradingRepository` (stub
`NotImplementedError`, mismo patrón que los otros 4 pares). Métodos que
**sí implican escritura** (`save_order`, `apply_fill`, `accept_order`,
`cancel_order`, `expire_order`, `save_portfolio_snapshot`,
`save_pnl_snapshot`) conviven con métodos de lectura
(`get_order`/`get_open_orders`/`fetch_positions`/`fetch_portfolio_history`/
etc.) en la misma interfaz — a diferencia de `DashboardRepository`, que
es **puramente** de lectura porque consume estas tablas desde afuera, sin
ser el dueño de escribirlas.

## 13. Auditoría de solo lectura — quién puede escribir estas tablas

Solo `PaperTradingService` (a través de `SQLitePaperTradingRepository`)
puede escribir en las 8 tablas de §12. Ni el Dashboard, ni ningún motor
(`PaperTradingEngine`, `RiskEngine`), ni ninguna integración futura de IA
tienen acceso de escritura — exactamente el mismo principio que ya
protege `market_data`/`market_indicators`/`market_signals`/
`ai_recommendations` del Dashboard actual.

## 14. Integración con el Dashboard (sin implementar páginas nuevas)

> **Confirmación de auditoría (Paso 13)**: el diseño ya cumple, sin
> cambios, los 5 requisitos auditados — el Dashboard (a) permanece de
> solo lectura, (b) nunca crea órdenes en la primera iteración (6.5, ver
> §19), (c) nunca llama a `PaperTradingEngine`/`RiskEngine`, (d) nunca
> llama a `PaperTradingService`, solo a `DashboardService`, (e) nunca
> modifica estados. La cadena de dependencia es
> `PaperTradingRepository → DashboardRepository → DashboardService →
> View Models → Components → Page`, igual que las 5 páginas actuales.
> Lo que una futura página mostraría, clasificado como pide el Paso 13:
> **datos operativos** (`Order`/`Execution` recientes), **agregaciones**
> (`Trade` histórico, cartera actual), **métricas derivadas**
> (`unrealized_pnl`, `drawdown`, `return_percent`, calculadas en
> `DashboardService`, nunca persistidas dos veces) y **snapshots
> históricos** (`PortfolioSnapshot`/`PnLSnapshot` para las series de
> tiempo del gráfico de equity). Ninguna página se crea en esta etapa.

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

> **Confirmación de auditoría (Paso 12)**: el flujo completo futuro es
> `AIRecommendation → StrategyDecision → OrderProposal → RiskValidation →
> Order`. Se evaluó si `StrategyDecision` y `OrderProposal` necesitan ser
> entidades persistidas propias ya en esta ronda — **no es necesario**:
> `Order.source=AI_RECOMMENDATION` + `Order.linked_recommendation_id`
> (ya presentes, ver abajo) son suficientes metadata para trazar el
> origen de una orden. Crear `StrategyDecision`/`OrderProposal` como
> tablas o modelos propios sin que exista todavía ningún
> `StrategyEngine` sería diseñar infraestructura para un consumidor que
> no existe (YAGNI, Paso 14) — se documentan como pasos conceptuales del
> flujo, no como entidades a implementar en 6.1-6.5. Se confirma también
> que el sistema puede operar sin IA (`paper_trading.enabled=true` con
> `ai_engine.enabled=false` es una combinación válida, igual que hoy el
> Dashboard funciona sin recomendaciones si la IA está apagada), que
> `RiskEngine` siempre se interpone entre la propuesta y la aceptación
> (ver flujo abajo), y que la `confidence` de la IA nunca se mezcla con
> las reglas de `RiskEngine` (son fuentes de decisión independientes:
> una interpreta mercado, la otra protege capital).

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

> **Corrección de auditoría**: alineada con el alcance final (§19):
> `PaperTradingEngine` solo simula MARKET (LIMIT queda documentado en
> §5, sin pruebas todavía) y solo LONG (SHORT diferido, §5.1) — las
> pruebas de motor no deben cubrir escenarios que el código no
> implementará en 6.1-6.5. El ejemplo de §6.3 (4 filas, capital inicial
> 10 000, fee 0.1%) se adopta como el **caso de prueba canónico** de
> `test_paper_trading_engine.py`: es el mismo ejemplo ya validado a mano
> en esta auditoría, con reconciliación explícita de caja.

Seguiría la convención de nombres ya confirmada en `tests/`
(`test_<dominio>_<sujeto>.py`):

| Archivo propuesto | Qué cubre | Mismo patrón que |
|---|---|---|
| `test_paper_trading_models.py` | Validación Pydantic: `Field` (ge/le/gt/min_length), invariantes (`filled_quantity <= quantity`, `reserved_quantity <= quantity`, coherencia `limit_price`/`order_type`), coerción de Enums (incluyendo que `SHORT` exista en el enum pero no se use). | `test_models_signal_data.py`, `test_ai_models.py` |
| `test_paper_trading_engine.py` | `PaperTradingEngine` puro, **solo MARKET, solo LONG**: simulación de llenado consumiendo `MarketTicker` directamente (sin `OrderBook`, ver §2.6), matemática de posición (aumentar/reducir/cerrar — no revertir, no SHORT), usando el **ejemplo de §6.3 como caso obligatorio** más casos límite (over-fill debe lanzar excepción, fill exacto → `FILLED`) — con listas de `MarketTicker` en memoria, sin SQLite. | `test_indicator_engine.py`, `test_signals_*_rule.py`, `test_ai_decision_engine.py` |
| `test_paper_trading_risk.py` | `RiskEngine` en aislamiento: las 5 reglas de §8.1 por separado y combinadas (incluyendo la distinción cash-reservado vs cantidad-reservada del punto 2), forma exacta de `RiskCheckResult` (§8.5), casos límite (exactamente en el borde de un límite), confirmación de que `RiskEngine` no muta nada (sin efectos secundarios observables sobre los objetos que recibe). | `test_signals_aggregator.py` (reglas combinadas) |
| `test_paper_trading_service.py` | `PaperTradingService.run_cycle()` con un repositorio Fake (mismo patrón `FakeDashboardRepository`/Fake usados en `test_dashboard_service.py`/`test_signals_service.py`/`test_ai_service.py`); confirma que un fill llama a `apply_fill()` (§12.2) como única escritura, nunca a métodos sueltos. | `test_ai_service.py` |
| `test_paper_trading_sqlite_repository.py` | Round-trip de las 8 tablas (§12.1), migración idempotente (3 llamadas a `init()`), aislamiento por símbolo/exchange, `apply_fill()` atómico (simular un fallo a mitad de camino y confirmar rollback completo), UNIQUE `(order_id, sequence_number)` rechaza un fill duplicado. | `test_ai_sqlite_repository.py`, `test_signals_sqlite_repository.py` |
| `test_paper_trading_postgres_stub.py` | Confirma `NotImplementedError` en los métodos del stub. | `test_ai_postgres_stub.py` |
| `test_integration_paper_trading.py` | `build_services()` instancia (o no) `PaperTradingService` según `paper_trading.enabled`, igual que hoy con `ai_engine.enabled`; ciclo completo de punta a punta con datos de prueba. | `test_integration_full_cycle.py` |
| `test_dashboard_paper_trading_page.py` | (Cuando exista la página, iteración 6.5) AppTest de la página nueva, mismo patrón que las 5 páginas actuales; confirma ausencia total de escritura (mismo criterio que `test_dashboard_readonly.py`). | `test_dashboard_signals_page.py` |

**Escenarios explícitos a cubrir antes de aceptar cualquier código de
Paper Trading como completo** (checklist para la etapa de
implementación, no para esta):

1. Las transiciones válidas de estado (§4, matriz de la auditoría)
   ocurren correctamente; las inválidas se rechazan y no existe ningún
   camino de código que las produzca — incluyendo los 8 casos especiales
   de §4 (cancelación/expiración tras fill parcial, rechazo de ejecución
   post-cancelación, over-fill, idempotencia de fills).
2. Ningún estado terminal (`FILLED`/`CANCELLED`/`REJECTED`/`EXPIRED`)
   vuelve a cambiar.
3. Simulación de llenado MARKET con 0, 1 y varios ticks de precio
   disponibles (incluyendo el caso "todavía no hay ningún
   `MarketTicker`").
4. Matemática de posición verificada contra el ejemplo resuelto a mano
   de §6.3 (aumentar, reducir, cerrar; LONG únicamente) — no solo
   aserciones triviales, sino la reconciliación exacta de caja.
5. `realized_pnl` vs `unrealized_pnl` no se confunden nunca (mismo
   cuidado conceptual que ya se documentó para `confidence` en la Etapa
   4, para no repetir esa clase de confusión); `gross_pnl`/`fees`/
   `net_pnl` de `Trade` (§2.3) se verifican por separado para confirmar
   que la comisión de apertura no se resta dos veces (§6.2).
6. Las reglas de `RiskEngine` (§8.1) rechazan correctamente cada una por
   separado, y una orden puede fallar por más de una regla a la vez sin
   ambigüedad sobre cuál motivo se reporta (`RiskCheckResult.code`).
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
- ❌ **SHORT y reversión LONG↔SHORT** (decisión de auditoría 6.0.1,
  diferida hasta diseñar un modelo de margen/colateral — ver §5.1 y
  §20).
- ❌ **Órdenes LIMIT** (decisión de auditoría 6.0.1, diferida por falta
  de datos de mercado con la fidelidad necesaria — ver §5 y §20).
- ❌ Cualquier modificación a `market_data`, `market_indicators`,
  `market_signals`, `ai_recommendations` o a las 6 páginas del Dashboard
  ya aprobadas.

## 18. Criterio de cierre de esta etapa (6.0)

Ver [ALCANCE_ETAPA_6.md](ALCANCE_ETAPA_6.md#criterio-de-cierre-de-la-etapa-60).

> **Nota (6.0.1)**: este criterio de cierre corresponde a la Etapa 6.0
> (diseño original). El cierre de la Etapa 6.0.1 (esta auditoría) es el
> descrito en el informe entregado al usuario, no en este archivo — ver
> §19 y §20 para el resultado concreto de la auditoría.

## 19. División final de iteraciones 6.1 en adelante (Paso 15 de la auditoría)

> El ejemplo de división que traía el diseño original (6.1 Modelos y
> enums; 6.2 Motores puros; 6.3 Persistencia; 6.4 Servicio y Composition
> Root; 6.5 Dashboard read-only) se confirma como la secuencia correcta,
> con el contenido de cada paso precisado por esta auditoría y un paso
> 6.6 explícitamente diferido agregado al final.

- **6.1 — Modelos y enums.** `Order`, `Execution`, `Trade` (con
  `gross_pnl`/`fees`/`net_pnl`, sin `entry_execution_ids`), `Position`
  (con `reserved_quantity`), `CashBalance`, `RiskLimits`,
  `PortfolioSnapshot`, `PnLSnapshot`, `PaperTradingEvent` (con
  `aggregate_type`/`aggregate_id`/`correlation_id`/`causation_id`/
  `schema_version`). Sin `OrderBook` (eliminado, §2.6). Enums con
  `SHORT` reservado pero no usado. Solo Pydantic + `Field`, sin lógica de
  negocio. Pruebas: `test_paper_trading_models.py`.
- **6.2 — Motores puros.** `RiskEngine` (§8, las 5 reglas de §8.1,
  `RiskCheckResult` de §8.5) y `PaperTradingEngine` (simulación de fill,
  **solo MARKET, solo LONG**, matemática de posición de §6), consumiendo
  `MarketTicker` en memoria, sin SQLite. El ejemplo de §6.3 es la prueba
  obligatoria. Pruebas: `test_paper_trading_engine.py`,
  `test_paper_trading_risk.py`.
- **6.3 — Persistencia.** Las 8 tablas de §12.1, migración idempotente,
  `SQLitePaperTradingRepository` con el método transaccional
  `apply_fill()` (§12.2), `PostgresPaperTradingRepository` stub. Pruebas:
  `test_paper_trading_sqlite_repository.py`,
  `test_paper_trading_postgres_stub.py`.
- **6.4 — Servicio y Composition Root.** `PaperTradingService.run_cycle()`,
  extensión de `Settings`/`config.yaml` (`paper_trading:` section),
  quinto paso condicional en `build_services()`/`run_full_cycle()`.
  **Pregunta abierta que esta auditoría identifica y que 6.4 debe
  resolver explícitamente**: sin Dashboard de escritura (6.5 es
  read-only) ni `StrategyEngine` (§15, futuro), ¿de dónde salen las
  primeras órdenes para poder probar el ciclo de punta a punta? Se
  recomienda un mecanismo mínimo no-UI (ej. un método de servicio
  invocable desde un test de integración o un script manual, no una
  interfaz de usuario) — decisión a confirmar explícitamente al abrir
  6.4, no ahora. Pruebas: `test_paper_trading_service.py`,
  `test_integration_paper_trading.py`.
- **6.5 — Dashboard de solo lectura.** Extensión de
  `DashboardRepository`/`DashboardService` (§14), página nueva
  `paper_trading.py`. Pruebas: `test_dashboard_paper_trading_page.py`.
- **6.6 — Diferido, fuera de esta ronda de aprobación.** Modelo de
  margen/colateral y SHORT (§5.1), órdenes LIMIT (§5), stop-loss/
  take-profit automáticos (§8.4), reversión LONG↔SHORT (§6.4). No se
  aprueba alcance ni diseño detallado de 6.6 en esta auditoría — solo se
  confirma que nada de 6.1-6.5 lo hace imposible de agregar después
  (§17, compatibilidad futura).

Cada iteración: alcance pequeño y verificable, deja la suite de pruebas
en verde, no mezcla responsabilidades de más de un paso de esta lista, y
requiere aprobación explícita del usuario antes de continuar a la
siguiente — mismo criterio ya usado en todas las etapas anteriores del
proyecto.

## 20. Decisiones aprobables antes de la Etapa 6.1 (Paso 16 de la auditoría)

Estas son las decisiones de diseño que esta auditoría resolvió y que
requieren confirmación explícita del usuario antes de iniciar 6.1:

1. **Precisión numérica**: `float` en todos los modelos (consistente con
   el resto del proyecto, sin precedente de `Decimal`, sin soporte nativo
   en `sqlite3`), mitigado por (a) redondeo a una precisión fija
   configurable al escribir, y (b) recalcular siempre los agregados
   cacheados desde la fuente vía `SUM(...)` en SQL, nunca `+=`
   incremental (§6.2, §9.1).
2. **Alcance inicial de tipos de orden**: solo `MARKET`. `LIMIT` queda
   documentado (§5) pero diferido a 6.6, por no poder simular una
   condición de activación con fidelidad suficiente con los datos de
   mercado actuales (un solo precio por ciclo, sin bid/ask/profundidad).
3. **Alcance inicial de lado de posición**: solo `LONG`. `SHORT` y la
   reversión LONG↔SHORT quedan documentados (§5.1) pero diferidos a 6.6,
   por no existir todavía un modelo de margen/colateral que acote la
   pérdida potencial de una posición corta.
4. **Atomicidad de fills**: obligatoria vía un método transaccional
   único (`apply_fill()`, §12.2) que escribe `Execution` + `Order` +
   `Position` + `CashBalance` + (`Trade`) + `Events` en una sola
   transacción SQLite — no se copia el patrón de "un commit por método"
   de las tablas existentes para esta operación.
5. **Fuente de verdad del PnL realizado**: `paper_trading_trades.net_pnl`
   (§2.3). Cualquier otro campo con PnL realizado
   (`Position.realized_pnl_to_date`, snapshots) es una caché recalculada
   desde esa fuente vía `SUM`, nunca un valor independiente.
6. **Tratamiento de comisiones (fees)**: solo la comisión de la ejecución
   que **cierra** un `Trade` entra en `Trade.fees`/`net_pnl` (§6.2); la
   comisión de apertura ya se refleja como salida de efectivo en
   `CashBalance` al momento de abrir/aumentar, y no se resta una segunda
   vez.
7. **Estructura de `CashBalance`**: `total_balance` + `reserved_balance`
   guardados, `available_balance` calculado (§9.1); `initial_capital`
   sembrado una sola vez desde config (§9.2); espejo de reserva de
   cantidad en `Position.reserved_quantity` para el lado de venta (§9.5).
8. **Persistencia de eventos**: una sola tabla `paper_trading_events`,
   híbrido dominio+auditoría, explícitamente **no** Event Sourcing y
   **no** un bus de integración (§10).
9. **Estrategia de snapshots**: `PortfolioSnapshot`/`PnLSnapshot`
   append-only, un registro por ciclo; métricas derivadas (`drawdown`,
   `return_percent`) calculadas al leer, no cacheadas de forma
   incremental (mismo principio del punto 1).
10. **División final de iteraciones**: 6.1 Modelos y enums → 6.2 Motores
    puros → 6.3 Persistencia → 6.4 Servicio y Composition Root → 6.5
    Dashboard read-only → 6.6 diferido (SHORT/margen, LIMIT, stop-loss/
    take-profit) — ver §19.

## 21. Ciclo de vida de órdenes con reservas (Etapa 6.7 — diseño previo a implementar)

Hasta la Etapa 6.6, `PaperTradingService.submit_market_order()` pasaba
una orden de `NEW` a `FILLED` dentro de una sola llamada, sin persistir
nunca un estado `PENDING` real ni tocar `CashBalance.reserved_balance`/
`Position.reserved_quantity` (ver nota de implementación de la Etapa
6.4). La Etapa 6.7 separa **aceptar** (reservar) de **llenar** (liquidar)
y agrega **cancelar** (liberar sin liquidar) como una tercera transición
explícita, con reservas reales.

### 21.1 Matriz de estados

| Estado | Puede... | No puede... |
|---|---|---|
| `NEW` | aceptarse (→ `PENDING`, con reserva); rechazarse (→ `REJECTED`, sin reserva) | llenarse directamente; cancelarse (nunca fue aceptada) |
| `PENDING` | llenarse (→ `FILLED`, libera reserva y liquida); cancelarse (→ `CANCELLED`, libera reserva sin liquidar) | aceptarse de nuevo; rechazarse |
| `FILLED` | — (terminal) | cancelarse; llenarse de nuevo; mantener reserva activa |
| `REJECTED` | — (terminal) | — (nunca tuvo reserva) |
| `CANCELLED` | — (terminal) | crear `Execution`/`Trade`; mantener reserva activa |
| `PARTIALLY_FILLED` | fuera de alcance: `FillEngine` sigue llenando el 100% del remanente en una única `Execution` (§9, sin cambios); este estado no se produce en 6.7 |

### 21.2 Fuente de verdad de la reserva: campos en `Order`, no una entidad nueva

Se evaluaron 3 alternativas (Paso 13 de la Etapa 6.7):

- **A. Entidad `OrderReservation` persistida aparte** (con su propio
  ciclo `ACTIVE`/`RELEASED`/`CANCELLED`).
- **B. Campos de reserva directamente en `Order`.**
- **C. Reconstruir la reserva desde el precio actual al liberar.**

**C se descarta de plano**: el enunciado lo prohíbe explícitamente
("no confiar en el precio actual para liberar una reserva histórica") y
es incorrecto en general (el precio pudo cambiar entre aceptar y
liberar).

**Se elige B sobre A** porque la relación entre una `Order` y su
reserva es exactamente 1:1 y coextensiva con el propio ciclo de vida de
la orden: una reserva nace exactamente cuando la orden pasa a `PENDING`
y muere exactamente cuando la orden deja `PENDING` (hacia `FILLED` o
`CANCELLED`) — nunca se comparte entre órdenes, nunca sobrevive a la
orden, nunca tiene un ciclo propio distinto del de la orden que la
originó. Modelarla como una entidad aparte (opción A) introduciría una
tabla, una FK y un enum de estado (`ACTIVE`/`RELEASED`/`CANCELLED`) que
solo espejarían, con más piezas, exactamente lo que `Order.status` ya
expresa. Se agregan 4 campos opcionales a `Order`:

| Campo | Tipo | Aplica a | Significado |
|---|---|---|---|
| `reserved_price` | `Optional[Decimal]` | BUY y SELL | Precio de mercado usado al aceptar -- ver §21.3, política de "llenar al precio aceptado". |
| `reserved_notional` | `Optional[Decimal]` | Solo BUY | `quantity × reserved_price` reservado de `CashBalance.reserved_balance`. |
| `reserved_fee` | `Optional[Decimal]` | Solo BUY | `reserved_notional × fee_rate` reservado junto al notional. |
| `reserved_quantity` | `Optional[Decimal]` | Solo SELL | `quantity` reservada de `Position.reserved_quantity`. |

**Corrección durante esta misma auditoría de diseño**: la primera
versión de este documento proponía un invariante estricto en `Order`
("estos 4 campos son `None` si y solo si `status` nunca fue aceptado").
Al implementarlo como `@model_validator`, la regresión completa saltó
de 0 a **135 pruebas rotas**: decenas de pruebas ya aprobadas de
`fill_engine`/`position_engine`/`risk_engine`/`service`/
`sqlite_repository` construyen órdenes `PENDING`/`FILLED`/`CANCELLED`
directamente (para probar fills, posiciones o riesgo, no reservas) sin
poblar estos 4 campos nuevos. Imponer el invariante a nivel de modelo
habría exigido modificar esa gran cantidad de pruebas estables solo
para satisfacer un campo que no ejercitan, violando el principio 12
("no modificar módulos estables salvo necesidad demostrada") en la
dirección contraria: la necesidad demostrada era **no** tocarlas.

Se aplica entonces la salida que el propio enunciado de la Etapa 6.7
preveía (Paso 23: "si estas invariantes no pueden vivir en modelos
aislados, aplicar las relacionales en Service/repositorio"): `Order`
solo valida que el campo de reserva **del lado equivocado** nunca se
use (`reserved_quantity` en una BUY, o `reserved_notional`/`reserved_fee`
en una SELL, siempre rechazados) — una comprobación barata, nunca
disparada por una orden que simplemente no usa reservas. La garantía
"una orden `PENDING` real (creada por `ReservationEngine`) siempre tiene
sus campos de reserva poblados" se sostiene **por construcción**
(`reserve_for_order()` los puebla siempre, ver §21.4), no por un
invariante de Pydantic que rechazaría datos de prueba legítimos y
anteriores a esta funcionalidad.

### 21.3 Política de precio: "MARKET se llena al precio aceptado"

Si el precio de mercado cambiara entre aceptar y llenar, ¿a qué precio
se llena la orden? Se decide que **la ejecución usa siempre
`order.reserved_price`**, nunca un precio nuevo consultado al momento de
llenar. Consecuencias:

- `fill_pending_order()` no recibe `market_price` como parámetro: lo lee
  de `order.reserved_price`, garantizando exactitud matemática (mismo
  precio, misma `quantity`, mismo `fee_rate` ⇒ el `fee` de la
  `Execution` resultante coincide exactamente con `order.reserved_fee`,
  sin redondeos ni aproximaciones).
- Esto también simplifica `PaperTradingApplication.fill_manual_pending_order()`:
  no consulta `MarketPriceProvider` (Paso 18 lo pide explícitamente).

### 21.4 Motor puro de reservas: `ReservationEngine`

Nuevo módulo `src/paper_trading/reservation_engine.py` (+
`reservation_results.py`), con el mismo perfil de pureza que
`fill_engine.py`/`position_engine.py`/`risk_engine.py`/`pnl_engine.py`:
sin repositorio, sin `sqlite3`, sin `logging`, sin `datetime.now()`/
`uuid.uuid4()`, sin Application/Service.

- `reserve_for_order(order, cash_balance, position, market_price, fee_rate, timestamp) -> ReservationResult`:
  exige `order.status == NEW`; para BUY calcula `reserved_notional`/
  `reserved_fee` y aumenta `cash_balance.reserved_balance`; para SELL
  exige `position.side == LONG` y `quantity <= available_quantity`, y
  aumenta `position.reserved_quantity`. Devuelve la `Order` ya en
  `PENDING` con los 4 campos de reserva poblados, más el `CashBalance`/
  `Position` actualizados (el que no cambia se devuelve tal cual, sin
  mutar). Como `RiskEngine.validate_order()` ya se llamó antes y aprobó,
  un fallo de reserva aquí (saldo/cantidad insuficiente) es un estado
  imposible/carrera, no un rechazo normal: lanza
  `InsufficientReservedCashError`/`InsufficientReservedQuantityError`.
- `release_for_order(order, cash_balance, position, timestamp) -> ReservationReleaseResult`:
  exige `order.status == PENDING`; lee `order.reserved_notional`/
  `reserved_fee`/`reserved_quantity` (nunca recibe estos valores como
  parámetro aparte: ya viven en `order`, evitando que quien llama pase
  un valor reservado distinto por error) y disminuye
  `reserved_balance`/`reserved_quantity` exactamente por esa cantidad.
  Nunca deja un valor reservado negativo (`ReservationAlreadyReleasedError`
  si lo haría). Se usa **tanto para llenar como para cancelar**: liberar
  la reserva es idéntico en ambos casos; lo que difiere es qué pasa
  *después* de liberar (liquidar vs. no hacer nada más).

### 21.5 Persistencia: transacciones nuevas, reutilización de `save_fill_transaction`

- `save_order_acceptance_transaction(order, cash_balance, position)`:
  UPSERT atómico de los 3 (Order en `PENDING` + reserva; CashBalance o
  Position, el que cambió; el otro se re-guarda sin cambios, operación
  barata e inocua).
- `save_order_cancellation_transaction(order, cash_balance, position)`:
  misma forma exacta que la anterior (UPSERT atómico de los 3), pero con
  `Order` en `CANCELLED`. Ambos métodos públicos delegan a un mismo
  helper privado (`_save_order_and_balances_transaction`): la operación
  SQL es idéntica; solo cambia semánticamente qué transición representa,
  y se mantienen dos nombres públicos distintos por claridad en el punto
  de llamada del Service.
- **`save_pending_fill_transaction` no se crea como método nuevo**: es
  exactamente `save_fill_transaction()` ya existente (Etapa 6.3) --
  UPSERT de Order a `FILLED` + INSERT de Execution + UPSERT de Position/
  CashBalance + INSERT opcional de Trade/snapshots. La operación SQL no
  distingue si la `Order` venía de `NEW` (flujo de compatibilidad) o de
  `PENDING` con reserva (flujo nuevo): en ambos casos es "escribir el
  estado final de un fill", así que reutilizar el método existente evita
  duplicar código sin perder claridad (principio 12: no modificar
  módulos estables salvo necesidad demostrada -- aquí, no hace falta).

### 21.6 Idempotencia

- **Aceptar dos veces la misma orden**: `accept_market_order()` primero
  comprueba `repository.get_order(order.id) is None`; si ya existe,
  lanza `InvalidOrderStateError` (nunca duplica una reserva).
- **Llenar/cancelar dos veces**: `fill_pending_order()`/
  `cancel_pending_order()` releen la `Order` actual por `id` y exigen
  `status == PENDING`; una segunda llamada sobre una orden ya `FILLED`/
  `CANCELLED` lanza `InvalidOrderStateError` antes de tocar nada.
  Llenar después de cancelar, o cancelar después de llenar: ambos
  prohibidos por la misma comprobación.

### 21.7 Compatibilidad con `submit_market_order()`/`submit_manual_market_order()`

Ambos se conservan como fachadas síncronas: `submit_market_order()` pasa
a ser `accept_market_order()` seguido de `fill_pending_order()` con el
mismo `timestamp`. **No finge una atomicidad que no existe**: son dos
transacciones SQLite distintas. Si la aceptación se persiste y el
llenado falla (una excepción de motor, no un rechazo de riesgo -- el
riesgo ya se validó antes de aceptar), la orden queda legítimamente
`PENDING` con su reserva activa en la base -- un estado válido y
recuperable (puede llenarse o cancelarse después con las nuevas
llamadas explícitas), no una corrupción. `submit_manual_market_order()`
se conserva igual en `PaperTradingApplication`, delegando a
`submit_market_order()` sin cambios de comportamiento observable.

**Recuperación tras reinicio**: como la reserva vive en columnas
persistidas de `paper_trading_orders` (§21.2) y no en memoria del
proceso, una orden `PENDING` con su reserva activa sobrevive intacta a
reconstruir la Composition Root (`build_paper_trading_context()`) sobre
el mismo archivo SQLite -- la nueva instancia de `PaperTradingService`/
`PaperTradingApplication` puede leer esa orden y llenarla o cancelarla
con normalidad, sin volver a reservar ni perder el estado. Verificado en
`tests/test_paper_trading_composition.py::TestReservationSurvivesRestart`.

### 21.8 Invariantes relacionales (Order ↔ reserva)

Las invariantes de `CashBalance` (`total_balance >= 0`,
`reserved_balance >= 0`, `reserved_balance <= total_balance`) y de
`Position` (`quantity >= 0`, `reserved_quantity >= 0`,
`reserved_quantity <= quantity`, `FLAT ⇒ quantity == 0` que ya implica
`FLAT ⇒ reserved_quantity == 0`) **ya existían y no cambian** (§2.4,
§2.5) -- la Etapa 6.7 no necesita tocarlas. La única invariante nueva
que sí vive en el modelo `Order` es la comprobación barata de §21.2
(el campo de reserva del lado equivocado nunca se usa). La relación
"`PENDING` implica que la reserva efectivamente está sumada en
`CashBalance`/`Position`" es relacional entre 3 filas distintas y no
puede vivir en un único modelo (y, como se documentó en §21.2, tampoco
conviene forzarla allí): se garantiza porque `ReservationEngine` y las
transacciones de persistencia siempre mueven `Order` + `CashBalance`/`Position` juntos,
atómicamente, nunca por separado.

### 21.9 Excepciones nuevas

`InvalidOrderStateError`, `ReservationNotFoundError`,
`InsufficientReservedCashError`, `InsufficientReservedQuantityError`,
`ReservationAlreadyReleasedError` -- las 5 sugeridas, sin ampliar la
jerarquía más allá. Todas heredan de `PaperTradingDomainError`. Un
rechazo de riesgo sigue sin lanzar excepción (resultado
`success=False`); estas 5 representan estados imposibles dado el flujo
correcto (aceptar algo no-`NEW`, liberar algo no-`PENDING`, reserva
insuficiente pese a que el riesgo ya aprobó).

### 21.10 Dashboard

Sigue estrictamente read-only. Los campos nuevos de reserva en `Order`
no se agregan a `OrderRow` en esta etapa (no es necesario: `reserved_balance`
de `CashBalance` y `reserved_quantity` de `Position` ya se muestran
desde la Etapa 6.6, que es la información operativa relevante); los
estados `PENDING` que ahora sí se persisten se muestran igual que
cualquier otro `OrderStatus`, sin cambios de código.

## 22. Reconciliación y recuperación de estado (Etapa 6.8 — diseño previo a implementar)

Esta etapa no agrega ningún caso de uso operacional nuevo (no crea
órdenes, no reserva, no llena, no cancela). Agrega un subsistema
paralelo, de solo diagnóstico por defecto, que **lee** el estado
persistido de Órdenes/Ejecuciones/Trades/Posiciones/Saldo y produce un
reporte estructurado de inconsistencias, con una vía explícita
(nunca automática) para corregir únicamente los agregados de reserva
(`CashBalance.reserved_balance`/`Position.reserved_quantity`).

### 22.1 Qué significa "reconciliar" aquí

Reconciliar = comparar el estado que **debería** existir (derivado
determinísticamente de las Órdenes PENDING vigentes) contra el estado
que **efectivamente** existe (los agregados guardados en `CashBalance`/
`Position`), más un conjunto de comprobaciones relacionales sobre
Órdenes/Ejecuciones/Trades que no dependen de ningún agregado. El
resultado es siempre un `ReconciliationReport` (Paso 5): una lista de
`ReconciliationIssue` con severidad y código estable.

**Detectar vs. reparar** son dos operaciones completamente separadas,
en módulos separados:

- **Detectar** (`ReconciliationEngine.analyze`, `ReconciliationService.inspect`)
  nunca escribe. Recibe colecciones ya cargadas (o las lee el Service
  desde el repositorio, en modo solo-lectura) y devuelve un reporte.
  Se puede ejecutar tantas veces como se quiera sin ningún efecto.
- **Reparar** (`ReconciliationService.repair`) es una acción explícita,
  separada, que el arranque normal (`build_paper_trading_context()`)
  **nunca** invoca. Por defecto corre en `dry_run=True` (simula, no
  escribe). Solo con `dry_run=False` (o `--apply` en la CLI) se
  persiste algo, y solo para los códigos de issue que están en la lista
  cerrada de reparaciones permitidas (§22.7).

### 22.2 Fuente de verdad de cada dato

| Dato | Fuente de verdad | Reconciliación puede... |
|---|---|---|
| `CashBalance.reserved_balance` | Suma de `reserved_notional + reserved_fee` de las Órdenes BUY `PENDING` vigentes | Recalcular y sobrescribir (repair permitido) |
| `Position.reserved_quantity` | Suma de `reserved_quantity` de las Órdenes SELL `PENDING` vigentes, por `(exchange, symbol)` | Recalcular y sobrescribir (repair permitido) |
| `Order.reserved_price/notional/fee/quantity` | `ReservationEngine`, al aceptar (histórico, inmutable una vez escrito) | Solo leer/comparar; nunca reescribir un campo de una `Order` |
| `Position.realized_pnl_to_date` | `SUM(Trade.net_pnl)` para ese `(exchange, symbol)` (ya es la regla de `check_position_pnl_consistency`, Etapa 6.3) | Solo leer/comparar/reportar; nunca recalcular en esta etapa |
| Existencia de una `Execution`/`Trade` | Las propias tablas `paper_trading_executions`/`paper_trading_trades` | Solo leer/comparar; nunca crear una fila nueva |
| `Order.status` | La propia tabla `paper_trading_orders`, escrita únicamente por `PaperTradingService` (Etapas 6.4/6.7) | Solo leer/comparar; **nunca** cambiar un `status` desde reconciliación |

Ningún precio se reconstruye nunca desde el precio de mercado actual:
todas las comparaciones usan exclusivamente datos ya persistidos
(`reserved_price`, `reserved_notional`, `Execution.price`, etc.), nunca
`MarketPriceProvider`. Por eso `ReconciliationEngine`/`ReconciliationService`
no reciben ni usan un `MarketPriceProvider`.

### 22.3 Tipos de inconsistencia y severidad

Ver Pasos 6-7 del enunciado para el criterio completo. Códigos
finalmente implementados (`IssueCode`, `str, Enum` — mismo patrón que
`OrderStatus`/`OrderSide`): 20 códigos, los 17 sugeridos por el
enunciado más 3 adiciones justificadas:

- `ORPHAN_EXECUTION` -- necesario porque el propio Paso 30 exige un caso
  de prueba "Execution huérfana" (una `Execution.order_id` que no
  resuelve a ninguna `Order`, o cuyo `exchange`/`symbol` no coincide con
  los de la orden que dice llenar) y ningún código de la lista sugerida
  cubre exactamente ese caso (`EXECUTION_FOR_NON_FILLED_ORDER` asume que
  la orden sí existe, solo que no está `FILLED`).
- `FILLED_ORDER_EXECUTION_MISMATCH` -- para "`filled_quantity`/
  `average_fill_price` de la Order no coinciden con su única Execution"
  (Paso 12, "filled_quantity debe ser coherente"/"average_fill_price
  debe ser coherente"); distinto de `FILLED_ORDER_WITHOUT_EXECUTION`
  (cero Executions) y de `MULTIPLE_EXECUTIONS_FOR_FULL_FILL_ORDER`
  (más de una).
- `NO_ACTIVITY` -- único código de severidad `INFO`, para el caso
  "ausencia total de operaciones" del Paso 7 (ver §22.4 sobre por qué es
  el único `INFO` que se emite).

Severidad de cada código (siguiendo el criterio del Paso 7 al pie de la
letra donde el enunciado ya lo fija explícitamente):

| Severidad | Códigos |
|---|---|
| `CRITICAL` | `NEGATIVE_AVAILABLE_CASH`, `NEGATIVE_AVAILABLE_QUANTITY`, `PENDING_BUY_RESERVED_CASH_MISMATCH`, `PENDING_SELL_RESERVED_QUANTITY_MISMATCH`, `PENDING_ORDER_INVALID_RESERVED_PRICE`, `ORDER_RESERVATION_SIDE_MISMATCH`, `FILLED_ORDER_WITHOUT_EXECUTION`, `FILLED_ORDER_EXECUTION_MISMATCH`, `EXECUTION_FOR_NON_FILLED_ORDER`, `ORPHAN_EXECUTION`, `TRADE_WITHOUT_EXIT_EXECUTION`, `SELL_FILLED_WITHOUT_TRADE` |
| `ERROR` | `PENDING_BUY_MISSING_RESERVATION`, `PENDING_SELL_MISSING_RESERVATION`, `ORPHAN_CASH_RESERVATION`, `ORPHAN_POSITION_RESERVATION`, `CASH_RESERVED_BALANCE_MISMATCH`, `POSITION_RESERVED_QUANTITY_MISMATCH`, `TERMINAL_ORDER_HAS_RESERVATION` |
| `WARNING` | `POSITION_PNL_INCONSISTENT`, `MULTIPLE_EXECUTIONS_FOR_FULL_FILL_ORDER` |
| `INFO` | `NO_ACTIVITY` |

`ReconciliationReport` agrega un `error_count` además de
`critical_count`/`warning_count`/`info_count` (el enunciado del Paso 5
dice "campos mínimos": con 4 severidades declaradas en el Paso 7, faltar
un contador para `ERROR` habría sido una inconsistencia del propio
reporte). `is_consistent = (critical_count == 0 and error_count == 0
and warning_count == 0)` -- `INFO` nunca afecta la consistencia.

### 22.4 Por qué no se emite un `ReconciliationIssue` por cada entidad válida

El Paso 7 lista como ejemplos de `INFO` "estado PENDING válido", "orden
terminal consistente", "ausencia total de operaciones". Emitir una fila
`INFO` por cada Orden PENDING válida y cada Orden terminal consistente
haría el reporte ilegible en una cuenta con miles de órdenes (el propio
Paso 11 usa Decimal exacto sobre agregados completos, pensado para
escalar). Se adopta la convención estándar de un reconciliador: **el
silencio es la confirmación** -- ausencia de cualquier issue con
severidad `ERROR`/`CRITICAL`/`WARNING` sobre una entidad significa que
esa entidad es válida. El único `INFO` que se emite es un resumen único,
a nivel de todo el reporte, cuando no existe ninguna Orden ni Posición
no-`FLAT` ni saldo reservado en el sistema (`NO_ACTIVITY`) -- exactamente
el caso "ausencia total de operaciones" del enunciado.

### 22.5 Reglas por categoría (resumen; ver docstrings de
`reconciliation_engine.py` para el detalle exacto)

- **BUY PENDING** (Paso 9): con los 3 campos de reserva poblados
  (`reserved_price`/`reserved_notional`/`reserved_fee`), se valida
  `reserved_notional == quantity * reserved_price` exacto (Decimal). El
  enunciado señala explícitamente que `reserved_fee` no puede
  validarse contra `fee_rate` porque `fee_rate` no se persiste por
  orden y puede haber cambiado desde que se aceptó -- **limitación
  documentada, no se inventa**: solo se valida que `reserved_fee` sea
  parte de los campos poblados (su valor exacto no se recalcula).
- **SELL PENDING** (Paso 10): con los 2 campos de reserva poblados
  (`reserved_price`/`reserved_quantity`), se valida
  `reserved_quantity == order.quantity` exacto.
- **Agregación** (Paso 11): `expected_reserved_cash` (suma de BUY
  PENDING) vs. `CashBalance.reserved_balance` de la moneda indicada
  explícitamente a `analyze()` (el dominio solo maneja una cuenta/moneda
  por vez, igual que `PaperTradingService`); `expected_reserved_quantity`
  por `(exchange, symbol)` (suma de SELL PENDING) vs.
  `Position.reserved_quantity` de esa posición. Ambas comparaciones son
  Decimal exacto, sin tolerancia.
- **Órdenes terminales** (Paso 12): `TERMINAL_ORDER_HAS_RESERVATION`
  se acota a `REJECTED` con algún campo de reserva poblado (un rechazo
  de riesgo nunca llega a `ReservationEngine`, ver `service.py`
  `accept_market_order` -- si ocurre, es estructuralmente imposible por
  el flujo correcto). Para `FILLED`/`CANCELLED`, conservar los campos de
  reserva históricos es **correcto por diseño** (§21.2) y no se reporta
  como issue; que un `FILLED`/`CANCELLED` no siga "contribuyendo" al
  agregado ya lo garantiza que la agregación del Paso 11 solo suma
  Órdenes `PENDING` -- cualquier remanente real en el agregado que no
  provenga de una `PENDING` vigente aparece igual como
  `CASH_RESERVED_BALANCE_MISMATCH`/`ORPHAN_CASH_RESERVATION` (o sus
  equivalentes de cantidad), sin necesitar una comprobación aparte por
  cada orden terminal.
- **Executions/Trades** (Paso 13): `FILLED_ORDER_WITHOUT_EXECUTION`
  (cero), `MULTIPLE_EXECUTIONS_FOR_FULL_FILL_ORDER` (más de una, sin
  daño financiero inmediato conocido → `WARNING`),
  `FILLED_ORDER_EXECUTION_MISMATCH` (exactamente una, pero
  `quantity`/`price` no coinciden con `filled_quantity`/
  `average_fill_price`), `EXECUTION_FOR_NON_FILLED_ORDER` (existe una
  Execution para una orden cuyo `status` no es `FILLED`),
  `ORPHAN_EXECUTION` (el `order_id` no resuelve, o el
  `exchange`/`symbol` no coincide), `SELL_FILLED_WITHOUT_TRADE` (una
  SELL `FILLED` sin ningún Trade cuyo `exit_execution_id` apunte a una
  de sus Executions), `TRADE_WITHOUT_EXIT_EXECUTION` (el
  `exit_execution_id` no resuelve, o resuelve a una Execution de una
  orden que no es SELL/FILLED, o con `exchange`/`symbol` distintos).
  Nunca se crea una Execution/Trade faltante.
- **PnL** (Paso 14): por posición, `Position.realized_pnl_to_date` vs.
  `SUM(Trade.net_pnl)` para ese símbolo (misma regla que
  `check_position_pnl_consistency`, reimplementada localmente porque el
  motor es puro y no puede llamar al repositorio) → `POSITION_PNL_INCONSISTENT`
  (`WARNING`, nunca se recalcula `realized_pnl_to_date` en esta etapa).

Comprobaciones estructurales que el propio `Order`/`Position`/
`CashBalance` de Pydantic ya vuelve imposibles al cargarse desde el
repositorio (`reserved_quantity` en una BUY, `reserved_balance >
total_balance`, `available_quantity < 0`, `net_pnl != gross_pnl - fees`,
`price/fee <= 0`) se conservan igual como comprobaciones defensivas y
baratas en el motor (`ORDER_RESERVATION_SIDE_MISMATCH`,
`NEGATIVE_AVAILABLE_CASH`, `NEGATIVE_AVAILABLE_QUANTITY`) -- documentadas
explícitamente como inalcanzables por el flujo normal (cualquier fila
corrupta ya falla al reconstruirse en `get_order()`/`get_cash_balance()`/
etc.), pero mantenidas por si el motor alguna vez recibe modelos
construidos con `model_construct()` (que salta la validación) desde
fuera del repositorio real -- las pruebas del motor usan exactamente esa
vía para poder ejercitarlas.

### 22.6 `ReconciliationService`: dry-run e idempotencia

`inspect(timestamp)` simplemente lee todo el estado vía el repositorio
(usando `limit=None` en los métodos `fetch_*` ya existentes) e invoca
`ReconciliationEngine.analyze()`. El único método de lectura nuevo que
hizo falta agregar a `PaperTradingRepository` (Paso 15) es
`fetch_cash_balances() -> list[CashBalance]`: el `get_cash_balance(currency)`
ya existente devuelve una sola moneda, y `analyze()` necesita el
conjunto completo. `repair(issue_codes, timestamp, dry_run=True)`:

1. Vuelve a llamar `inspect()` (estado fresco, nunca reutiliza un
   reporte viejo pasado por el llamador -- evita reparar contra datos
   obsoletos).
2. Filtra los issues reparables (§22.7) que además están en
   `issue_codes` (o todos los reparables si `issue_codes` es `None`).
3. Calcula el `CashBalance`/`Position` corregidos (recomputados desde
   cero a partir de las Órdenes PENDING vigentes, nunca por
   incrementos/decrementos aproximados) y normaliza `Decimal("-0")` a
   `Decimal("0")` exacto.
4. Si `dry_run=True` (por defecto): no escribe nada.
   `ReconciliationRepairResult.operations_applied` describe lo que se
   *haría*; `success=True` si el plan se pudo construir sin error.
5. Si `dry_run=False`: antes de escribir, vuelve a leer
   `CashBalance`/`Position` una última vez y compara contra los valores
   usados al planear (control optimista, Paso 28); si difieren, aborta
   con `ReconciliationConflictError` sin escribir nada y sin hacer
   rollback parcial (nunca llegó a abrir la transacción). Si coinciden,
   ejecuta `save_reconciliation_transaction()` (única, atómica) y
   registra el resultado en la tabla de auditoría.

Idempotencia (Paso 27): tras una reparación exitosa, `CashBalance.reserved_balance`/
`Position.reserved_quantity` ya son exactamente la suma correcta de las
PENDING vigentes; una segunda `inspect()` no encuentra el mismo issue
(el estado ya es consistente), y una segunda `repair()` sobre el mismo
código no encuentra nada que reparar (`repaired_issue_codes` vacío,
`operations_applied` vacío, `success=True` -- no es un error volver a
pedir una reparación ya aplicada, simplemente no hay nada que hacer).

### 22.7 Reparaciones permitidas y prohibidas

Permitidas (únicas, deterministas, Paso 17):

1. `CASH_RESERVED_BALANCE_MISMATCH`/`ORPHAN_CASH_RESERVATION` →
   recalcular `CashBalance.reserved_balance` como la suma exacta de
   `reserved_notional + reserved_fee` de las BUY `PENDING` vigentes.
2. `POSITION_RESERVED_QUANTITY_MISMATCH`/`ORPHAN_POSITION_RESERVATION`
   → recalcular `Position.reserved_quantity` como la suma exacta de
   `reserved_quantity` de las SELL `PENDING` vigentes de ese símbolo.

Todo lo demás (`PENDING_*_MISSING_RESERVATION`,
`PENDING_ORDER_INVALID_RESERVED_PRICE`, `ORDER_RESERVATION_SIDE_MISMATCH`,
`TERMINAL_ORDER_HAS_RESERVATION`, cualquier issue de Execution/Trade/PnL,
`NEGATIVE_AVAILABLE_*`) es **no reparable automáticamente**
(`repairable=False`): exigiría crear una Execution/Trade, cambiar un
`OrderStatus`, inventar un precio/fee histórico o reescribir un campo de
`Order` -- todas explícitamente prohibidas (Paso 17) -- y por tanto
requiere intervención manual (una migración de datos escrita a mano,
revisada por el usuario, fuera del alcance de este subsistema).

### 22.8 Atomicidad, rollback y concurrencia

`save_reconciliation_transaction(cash_balances, positions, audit_record)`
es la única operación de escritura: una única conexión SQLite, upsert de
cada `CashBalance`/`Position` corregido más un `INSERT` en
`paper_trading_reconciliation_audit`, un único `commit()`; cualquier
excepción dispara `rollback()` antes de relanzar. Nunca toca
`paper_trading_orders`/`_executions`/`_trades`/`_portfolio_snapshots`/
`_pnl_snapshots`. El control optimista de concurrencia (Paso 28) vive en
`ReconciliationService.repair()`, no en el repositorio: el repositorio
solo ofrece la transacción; decidir si los valores siguen vigentes es
responsabilidad del Service, que ya tiene el reporte fresco.

### 22.9 Auditoría persistente

Tabla nueva `paper_trading_reconciliation_audit` (columnas del Paso 20).
Se persiste **tanto en dry-run como en reparación real** (`dry_run` es
una columna, no una condición para omitir el registro): un dry-run que
detectó problemas pero no aplicó nada también queda auditado. `report_json`/
`operations_json` usan `serialize_reconciliation_report()`/
`serialize_repair_operations()` nuevos en `serialization.py`, siguiendo
las mismas reglas ya vigentes (Decimal como string, datetime ISO8601,
enum `.value`, `json.dumps(..., sort_keys=True)` para que el JSON sea
determinista). `id`/`started_at`/`completed_at` siempre inyectados por
quien llama (`IdGenerator`/`Clock`), nunca generados dentro del
repositorio.

### 22.10 CLI administrativa

`src/paper_trading/reconciliation_cli.py`, separada del Dashboard (que
sigue sin ningún botón administrativo) y de `main.py` (que sigue sin
scheduler ni ejecución automática). `--apply` obligatorio para escribir;
sin él, `repair` siempre corre en `dry_run=True`. Construye su propio
`PaperTradingContext` vía `build_paper_trading_context()` (mismo patrón
que `main.py`), usando `SystemClock`/`UUIDIdGenerator` reales -- nunca
conecta Binance, nunca importa Streamlit/Dashboard, nunca inicia un
scheduler.

### 22.11 Arranque normal y Dashboard

`build_paper_trading_context()` construye `ReconciliationEngine`/
`ReconciliationService` (agregados a `PaperTradingContext` como un campo
más) pero **nunca** llama `inspect()` ni `repair()` durante la
construcción -- ver Paso 24. El Dashboard no cambia en esta etapa (se
prefiere no tocarlo, ver Paso 25): no importa `ReconciliationService`,
no expone ningún botón de inspección/reparación, sigue siendo
estrictamente de solo lectura sobre las 7 tablas ya existentes.

### 22.12 Excepciones nuevas

`ReconciliationError` (base), `ReconciliationConflictError` (control
optimista de concurrencia falló), `UnsupportedRepairError` (se pidió
reparar un `issue_code` que no está en la lista de reparaciones
permitidas), `ReconciliationAuditError` (falló la escritura de la fila
de auditoría). No heredan de `PaperTradingDomainError` (no son un error
del dominio de trading, son del subsistema de reconciliación) ni se
mezclan con rechazos de riesgo normales.

### 22.13 Limitaciones documentadas

- `reserved_fee` de una BUY PENDING no se valida contra `fee_rate`
  actual (§22.5): `fee_rate` no se persiste por orden.
- `Position.realized_pnl_to_date` nunca se corrige automáticamente en
  esta etapa (Paso 14): solo se reporta la diferencia.
- Ninguna Execution/Trade faltante se crea nunca: `SELL_FILLED_WITHOUT_TRADE`/
  `FILLED_ORDER_WITHOUT_EXECUTION` quedan como diagnóstico permanente
  hasta una intervención manual explícita, fuera de este subsistema.
- La automatización de la reconciliación (ejecutarla periódicamente,
  alertar, o exponerla en el Dashboard de alguna forma read-only) queda
  pendiente para una etapa futura (6.9+).

## 23. Automatización controlada de inspecciones (Etapa 6.9 — diseño previo a implementar)

### 23.1 Objetivo y alcance

Automatizar exclusivamente `ReconciliationService.inspect()` (Etapa
6.8): ejecutarlo periódicamente, persistir cada corrida, comparar contra
la anterior, y generar alertas estructuradas cuando algo cambia.
**`repair()` nunca se invoca desde ningún componente de esta etapa** --
ni el job, ni el scheduler, ni la Application, ni la Composition Root.
Reparar sigue siendo, exclusivamente, la CLI manual de la Etapa 6.8
(`reconciliation_cli.py repair --apply`), invocada por una persona.

### 23.2 Ejecución manual vs. periódica

- **Manual**: `PaperTradingApplication.run_reconciliation_inspection()`
  (delegando a `InspectionService`) o la nueva CLI
  (`inspection_cli.py run`) -- una sola corrida, bajo demanda.
- **Periódica**: `inspection_scheduler.py`, un proceso independiente
  (`python -m src.paper_trading.inspection_scheduler`) que invoca
  `InspectionJob.run_once()` cada `interval_minutes`. No es parte de
  `main.py`/`run_full_cycle()`, no comparte proceso con el bot principal.

### 23.3 Fuente de verdad

El `ReconciliationReport` que ya produce `ReconciliationEngine.analyze()`
(Etapa 6.8) sigue siendo la única fuente de verdad de qué está
inconsistente. Esta etapa no agrega ninguna regla de detección nueva:
solo persiste ese reporte, lo compara con el anterior, y decide si algo
amerita una alerta.

### 23.4 Identidad estable de un issue

`IssueIdentity` (`code`, `entity_type`, `entity_id`, `exchange`,
`symbol` -- exactamente los campos que identifican QUÉ está mal, nunca
CUÁNDO se detectó ni CÓMO se describe) permite reconocer "el mismo
problema" entre dos reportes generados en instantes distintos.
`build_issue_identity(issue)` es una función pura y determinista;
`IssueIdentity` es `@dataclass(frozen=True, order=True)`: hashable (para
usarse como clave de `dict`/`set`) y ordenable (para que las listas de
salida del comparador sean deterministas).

### 23.5 Comparación entre reportes

`compare_reports(previous_report, current_report)` (puro,
`inspection_comparator.py`) indexa ambos reportes por `IssueIdentity` y
clasifica cada identidad:

- Solo en `current` -> `new_issues`.
- Solo en `previous` -> `resolved_issues`.
- En ambos -> pertenece a `persistent_issues` (el superconjunto) y,
  además, a **todas** las subcategorías que apliquen -- no son
  mutuamente excluyentes desde la corrección de la Etapa 6.9 (ver
  §23.19): un mismo issue puede caer en `severity_increased` **y**
  `value_changed` a la vez si ambas cosas cambiaron en la misma corrida.
  1. `severity_increased` si el ordinal de severidad subió
     (`INFO(0) < WARNING(1) < ERROR(2) < CRITICAL(3)`).
  2. `severity_decreased` si bajó (mutuamente excluyente solo entre sí
     y `severity_increased` -- la severidad no puede subir y bajar a la
     vez).
  3. `value_changed` si `expected_value`, `actual_value` o `repairable`
     cambiaron, **independientemente** de si también hubo cambio de
     severidad.
  4. `unchanged` únicamente si no aplicó ninguna de las anteriores.

`previous_report=None` (primera inspección de la cuenta, nunca hubo una
corrida exitosa antes) se trata como "reporte anterior vacío": todos los
issues de `current_report` caen en `new_issues`, el resto queda vacío.
Una diferencia solo en `description`/`detected_at` nunca cambia la
identidad ni dispara ninguna subcategoría (esos campos no forman parte
de `IssueIdentity` ni se comparan).

### 23.6 Modelo de alertas y reglas de disparo

`AlertType`: `NEW_ISSUE`, `RESOLVED_ISSUE`, `SEVERITY_INCREASED`,
`SEVERITY_DECREASED`, `VALUE_CHANGED`, `INSPECTION_FAILED`,
`SYSTEM_RECOVERED`. Reglas (Paso 8): `NEW_ISSUE`/`RESOLVED_ISSUE`/
`SEVERITY_INCREASED` siempre generan alerta; se decide generar también
`SEVERITY_DECREASED` siempre (no solo "opcional"), por consistencia con
`SEVERITY_INCREASED` y porque una baja de severidad sigue siendo
información operativa relevante (ej. pasar de CRITICAL a WARNING sigue
mereciendo visibilidad); `VALUE_CHANGED` genera alerta solo si
`expected_value`/`actual_value` cambiaron (definido en 23.5). Ningún
cambio de solo `description`/`detected_at` genera alerta.

### 23.7 Deduplicación (`deduplication_key`)

SHA-256 sobre un payload JSON determinista (`sort_keys=True`, UTF-8) --
nunca `hash()` nativo (no determinista entre procesos). El payload
depende del tipo de alerta y **nunca** incluye `alert.id`, `run_id`,
`created_at` ni `detected_at`:

| AlertType | Payload |
|---|---|
| `NEW_ISSUE` | `alert_type`, `issue_identity`, `severity` (actual) |
| `RESOLVED_ISSUE` | `alert_type`, `issue_identity`, `severity` (la que tenía al resolverse) |
| `SEVERITY_INCREASED`/`SEVERITY_DECREASED` | `alert_type`, `issue_identity`, `previous_severity`, `current_severity` |
| `VALUE_CHANGED` | `alert_type`, `issue_identity`, `previous_expected_value`, `previous_actual_value`, `current_expected_value`, `current_actual_value`, `previous_repairable`, `current_repairable` |
| `INSPECTION_FAILED` | `alert_type`, `error_message` |
| `SYSTEM_RECOVERED` | `alert_type`, `previous_error_message` (el de la corrida fallida que precedió a la recuperación) |

**Limitación documentada**: como ni `run_id` ni marcas de tiempo forman
parte de la clave (por diseño, para que un reinicio no duplique
alertas), si exactamente la misma identidad reaparece con exactamente
la misma severidad después de haberse resuelto una vez, o si el mismo
`error_message` de fallo vuelve a ocurrir en un episodio posterior, la
clave de deduplicación coincide con la de la primera vez y esa
recurrencia no genera una fila nueva (la restricción `UNIQUE` la
rechazaría). Se documenta como limitación aceptada -- resolverla
exigiría incorporar un marcador de "episodio" monótono, explícitamente
fuera de alcance de los campos permitidos en la clave (Paso 10).

### 23.8 Persistencia

Dos tablas nuevas, mismo patrón que `paper_trading_reconciliation_audit`
(Etapa 6.8): `paper_trading_inspection_runs` (una fila por corrida,
`report_json` nulo si la corrida falló) y `paper_trading_inspection_alerts`
(`deduplication_key` con `UNIQUE`, `FOREIGN KEY(run_id)`). Migración
idempotente (`CREATE TABLE IF NOT EXISTS`, igual que toda tabla nueva de
Paper Trading). `save_inspection_run_transaction(run, alerts)` es la
única escritura multi-fila: una transacción atómica que inserta el run y
todas sus alertas (filtradas de duplicados antes de intentar el
`INSERT`, ver 23.7), todo o nada.

### 23.9 Entrega y reintentos

`InspectionAlertSink.deliver(alert) -> AlertDeliveryResult` es la única
abstracción de entrega; `LoggingInspectionAlertSink` (usa `logging`,
nunca `print`, captura sus propios errores) y `NullInspectionAlertSink`
(para pruebas) son las únicas implementaciones de esta etapa -- ningún
canal externo (email/Slack/Telegram/webhooks) se implementa todavía.
`AlertDeliveryService.deliver_pending_alerts()` lee `PENDING` (lote
acotado por `pending_alert_batch_size`), entrega una por una, y por cada
una: éxito -> `DELIVERED`; fallo con `delivery_attempts + 1 <
max_alert_delivery_attempts` -> sigue `PENDING` (reintentable); fallo
que alcanza el máximo -> `FAILED` (ya no se reintenta). Un fallo de
entrega o de la propia actualización de estado nunca detiene el
procesamiento de las demás alertas del lote (`try/except` por alerta).
`DELIVERED` nunca se reenvía; `SUPPRESSED` nunca se entrega (valor
reservado en `AlertStatus` para una futura función de silenciado manual
-- igual criterio que `OrderType.LIMIT`/`PositionSide.SHORT`: declarado,
sin ningún camino de código de esta etapa que lo produzca todavía).

### 23.10 `InspectionService`

Ajuste sobre la firma sugerida (Paso 15, con licencia explícita del
enunciado para adaptarla): `run_inspection(run_id, started_at, alert_ids)`
recibe `run_id`/`started_at` ya generados (por `InspectionJob`, vía
`IdGenerator`/`Clock`) pero determina `completed_at` internamente
llamando a su propio `Clock` inyectado justo antes de persistir --
pedirlo como parámetro externo habría obligado al llamador a inventar
ese instante *antes* de que la inspección realmente terminara. Del mismo
modo, `alert_ids` no es una lista de tamaño fijo pasada a ciegas: el
Service primero ejecuta `inspect()` + `compare_reports()`, cuenta
exactamente cuántas alertas hacen falta (la suma de los tamaños de cada
subcategoría de `InspectionComparison`), y **entonces** pide esa
cantidad exacta de ids a `IdGenerator.new_inspection_alert_id()` antes
de invocar `alert_builder.build_alerts()` (puro) con la lista ya
completa -- así el builder nunca genera un id él mismo (Paso 11) y el
Service es, igual que `PaperTradingApplication`, el único punto que
combina IdGenerator + una función pura.

### 23.11 Manejo de errores, `INSPECTION_FAILED` y `SYSTEM_RECOVERED`

Si `ReconciliationService.inspect()` lanza una excepción,
`InspectionService` la captura: nunca la deja propagar como fallo no
controlado (violaría "un fallo no debe detener el scheduler", Paso 4).
Construye un `ScheduledInspectionRun(success=False, report=None,
error_message=str(exc))`, una alerta `INSPECTION_FAILED` (deduplicada
por `error_message`, ver 23.7), y persiste ambos con la misma
transacción atómica que un run exitoso. Si la corrida **anterior**
(`get_latest_inspection_run()`, no `get_latest_successful_inspection_run()`)
tenía `success=False` y esta corrida sí tiene éxito, se agrega una
alerta `SYSTEM_RECOVERED` (una sola vez por episodio, deduplicada por el
`error_message` de esa corrida fallida previa). Si la propia
persistencia del run falla (un problema estructural del repositorio, no
un hallazgo de reconciliación), se intenta un último registro de fallo
con `save_inspection_run_transaction` de solo el run marcado
`success=False`; si eso también falla, se relanza envuelta en
`InspectionPersistenceError` -- mismo patrón que `ReconciliationAuditError`
en `reconciliation_service.py` (Etapa 6.8).

### 23.12 `InspectionJob` y no solapamiento

`InspectionJob.run_once()` es la única pieza que combina timing
(`Clock`), identidad (`IdGenerator`), `InspectionService` y
`AlertDeliveryService` -- no contiene ninguna regla de comparación ni de
reconciliación. Usa un `threading.Lock()` no reentrante en memoria
(`acquire(blocking=False)`): si ya hay un `run_once()` en curso, el
nuevo intento se omite de inmediato (`InspectionJobResult(skipped=True)`),
sin bloquear. El lock se libera siempre en `finally`, incluso si
`InspectionService`/`AlertDeliveryService` lanzan una excepción no
prevista. **Limitación explícita**: este lock protege un único proceso;
no es un advisory lock de base de datos y no impide que dos procesos
distintos (dos instancias del scheduler, o el scheduler + la CLI a la
vez) corran `run_once()` simultáneamente -- eso queda para una etapa
futura si se necesita.

### 23.13 Configuración y semántica de `enabled`

`paper_trading.reconciliation_inspection` es un bloque **opcional**
dentro de `config.yaml -> paper_trading`: si no existe, se aplican
valores por defecto seguros (`enabled=false`, `interval_minutes=60`,
`run_on_startup=false`, `deliver_alerts=true`,
`max_alert_delivery_attempts=3`, `history_limit=100`,
`pending_alert_batch_size=100`) -- un `config.yaml` de una etapa
anterior sigue cargando sin cambios. Dos gates independientes, nunca
confundidos:

- `paper_trading.enabled` controla la operación simulada (aceptar/
  llenar/cancelar órdenes). La inspección administrativa **manual**
  (`Application.run_reconciliation_inspection()`, la CLI) funciona
  igual con `paper_trading.enabled=false` -- mismo criterio ya aplicado
  a `inspect_reconciliation()`/`repair_reconciliation()` en la Etapa 6.8
  (§22.11): mantenimiento/diagnóstico no es una acción de trading.
- `reconciliation_inspection.enabled` controla exclusivamente si el
  **scheduler** (`inspection_scheduler.py`) arranca. Si es `false`, el
  proceso del scheduler informa y termina con código 0 sin construir
  ningún loop.

### 23.14 `Application`/Composition Root/CLI/Dashboard

`PaperTradingApplication` gana 3 métodos administrativos
(`run_reconciliation_inspection()`, `deliver_pending_reconciliation_alerts()`,
`fetch_reconciliation_inspection_history(limit=None)`) que delegan sin
contener reglas, igual criterio que `inspect_reconciliation()`/
`repair_reconciliation()` (§22.11) -- no expuestos en el Dashboard.
`PaperTradingContext` gana `inspection_service`/`alert_delivery_service`/
`inspection_job`; `build_paper_trading_context()` los construye e
inyecta pero **nunca** llama `run_once()`/`inspect()`/entrega alguna
durante la construcción (mismo principio ya establecido en §22.11 para
`repair()`). El Dashboard no cambia en esta etapa: sigue sin ningún
botón ni control del scheduler/inspección/alertas, sigue leyendo
únicamente vía el repositorio de solo lectura ya existente (Etapa 6.6).

### 23.15 CLI y scheduler

`inspection_cli.py` (`run`/`alerts`/`history --limit N`) sigue el mismo
patrón que `reconciliation_cli.py` (Etapa 6.8): construye su propio
`PaperTradingContext`, nunca llama `repair()`, nunca conecta Binance.
`inspection_scheduler.py` es un proceso completamente independiente de
`main.py`: no importa `run_full_cycle`, `BinanceExchangeClient`,
`SignalEngine`/`SignalService`, ni ningún módulo de `src.ai`/
`src.dashboard`. Implementa su propio loop simple (`InspectionScheduler`,
con `sleep_fn`/`max_cycles` inyectables para pruebas deterministas, sin
depender de la librería `schedule` -- ya usada por `main.py`, mantenida
fuera de este módulo para no acoplar ambos schedulers), en vez de
reutilizar `schedule.every(...)` de `main.py`, precisamente para poder
probarlo sin esperas reales (Paso 41) y para no tocar el scheduler
principal (Paso 28, "no modificar el scheduler principal salvo
necesidad estricta" -- no hizo falta ninguna).

### 23.16 Excepciones nuevas

`InspectionError` (base), `InspectionPersistenceError`,
`InspectionComparisonError`, `AlertDeliveryError`,
`InspectionAlreadyRunningError` -- no heredan de
`PaperTradingDomainError` ni de `ReconciliationError` (Etapa 6.8): son
un subsistema propio, análogo en independencia al de reconciliación.

### 23.17 Aislamiento y prohibición de reparación automática

Ningún componente de esta etapa (`InspectionComparator`, `AlertBuilder`,
`InspectionService`, `AlertDeliveryService`, `InspectionJob`,
`InspectionScheduler`) importa `ReconciliationService.repair`,
`PaperTradingService`, `RiskEngine`/`FillEngine`/`PositionEngine`,
Binance, `requests`, Streamlit/Dashboard, ni `src.signals`/`src.ai`. La
única forma de reparar sigue siendo la CLI manual de la Etapa 6.8. La
inspección automatizada de esta etapa **detecta y alerta**, nunca
corrige.

### 23.18 Notas de implementación (clarificaciones surgidas al programar)

- **`LoggingInspectionAlertSink`/`NullInspectionAlertSink` reciben un
  `Clock` inyectado** (no estaba explícito en el diseño original de
  §23.9): `AlertDeliveryResult.delivered_at` es responsabilidad del
  propio sink, y el Paso 4 (principio 14) exige que ningún módulo fuera
  de `runtime.py` llame `datetime.now()` directamente -- un `Clock`
  inyectado (con `SystemClock()` como valor por defecto) es la única
  forma de cumplir ambas cosas a la vez.
- **`AlertDeliveryBatchResult`** (`delivered_count`, `failed_count`) es
  un `NamedTuple` nuevo, no listado explícitamente en el enunciado:
  necesario como valor de retorno de
  `AlertDeliveryService.deliver_pending_alerts()`, mismo criterio que
  `SubmitOrderResult`/`ReconciliationRepairResult` en etapas anteriores.
- **`deserialize_reconciliation_report()`** (inverso de la función ya
  existente desde la Etapa 6.8) se agregó a `serialization.py` aunque no
  aparecía en la lista literal del Paso 14: es la única forma de
  "reconstruir el reporte anterior" que el Paso 15 exige explícitamente.
- **`ReconciliationInspectionConfig`** vive en `src/utils/config.py`
  (no en `src/paper_trading/`), como un campo con `default_factory`
  dentro de `PaperTradingConfig` -- así una `config.yaml` sin el bloque
  (toda config de la Etapa 6.0-6.8) sigue funcionando exactamente igual,
  sin ningún cambio de comportamiento.
- **`PaperTradingApplication`/`PaperTradingContext` ganan un tercer
  parámetro/campo opcional** (`inspection_service`/`alert_delivery_service`
  en Application; `inspection_service`/`alert_delivery_service`/
  `inspection_job` en `PaperTradingContext`), con el mismo patrón de
  default-si-no-se-inyecta ya usado por `reconciliation_service` en la
  Etapa 6.8 -- no rompe ningún consumidor existente que construya estas
  clases directamente (solo `composition.py` las instancia en el
  proyecto real).

### 23.19 Corrección post-aprobación: clasificación acumulativa, no excluyente

Detectado en auditoría tras el cierre inicial de la etapa: la
implementación original de `compare_reports()` usaba una cadena
`if severity_increased / elif severity_decreased / elif value_changed /
else unchanged`, que es **excluyente** -- un issue que cambiaba de
severidad Y de valor a la vez (ej. `WARNING`+`actual_value=100` ->
`CRITICAL`+`actual_value=200`) solo quedaba clasificado como
`severity_increased`, perdiendo silenciosamente la señal de
`value_changed`. Esto no correspondía al diseño aprobado (§23.5 nunca
exigió exclusión entre severidad y valor, solo la exclusión obvia entre
"subió" y "bajó").

**Corrección**: se reemplazó la cadena por dos bloques independientes
-- uno que evalúa severidad (`if aumentó / elif disminuyó`, mutuamente
excluyentes entre sí, ya que no puede subir y bajar en la misma
comparación) y otro, siempre evaluado por separado, que evalúa
`expected_value`/`actual_value`/`repairable`. Un issue puede así caer en
`severity_increased` **y** `value_changed` simultáneamente. `unchanged`
solo se puebla si ninguno de los dos bloques disparó. Cambio acotado
exclusivamente a `inspection_comparator.py`: `IssueIdentity`,
deduplicación, `AlertBuilder`, `InspectionService`, repositorio,
scheduler y Dashboard quedan exactamente igual -- `AlertBuilder` ya
iteraba cada subcategoría de `InspectionComparison` de forma
independiente (Paso 11 original), así que generar dos alertas
(`SEVERITY_INCREASED` + `VALUE_CHANGED`) para el mismo `IssueIdentity`,
con `deduplication_key` distintas, no requirió ningún cambio de código
en `alert_builder.py` ni en `InspectionService.run_inspection()` (que ya
calculaba el total de IDs necesarias sumando el tamaño de cada
subcategoría, sin asumir exclusión).

## 24. Canales de entrega de alertas (Etapa 6.10 — diseño previo a implementar)

### 24.1 Objetivo

Ampliar únicamente el **mecanismo de entrega** de las alertas ya
generadas por la Etapa 6.9 (`InspectionAlert`, persistidas en
`paper_trading_inspection_alerts`) para soportar, en el futuro, múltiples
canales simultáneos (logging, email, Slack, Telegram, webhooks) sin que
`AlertDeliveryService` conozca ninguno de ellos por nombre. Esta etapa
**no** agrega ninguna regla de detección, comparación ni generación de
alertas (eso ya está cerrado desde la 6.9): es exclusivamente una
refactorización de la capa de entrega hacia el patrón Strategy, más 4
canales *placeholder* que todavía no conectan a ningún servicio externo.

### 24.2 Arquitectura de canales (patrón Strategy)

`InspectionNotificationChannel` (`Protocol`, método único
`deliver(alert) -> AlertDeliveryResult`) es la única abstracción que
`AlertDeliveryService` conoce -- exactamente el mismo contrato que ya
tenía `InspectionAlertSink` (Etapa 6.9), solo renombrado y trasladado a
`notification_channels.py` para dejar claro que es el punto de
extensión Strategy de esta etapa. Cada canal concreto
(`LoggingNotificationChannel`, `NullNotificationChannel`,
`EmailNotificationChannel`, `SlackNotificationChannel`,
`TelegramNotificationChannel`, `WebhookNotificationChannel`) implementa
ese único método sin que `AlertDeliveryService` necesite saber cuál es
cuál -- **nunca** un `if`/`isinstance`/switch por tipo de canal dentro
de `AlertDeliveryService` ni dentro de `CompositeNotificationChannel`.

### 24.3 Flujo de entrega

`AlertDeliveryService.deliver_pending_alerts()` (sin cambios de lógica,
solo de tipo declarado) sigue leyendo alertas `PENDING`, llamando a
`self._channel.deliver(alert)` una vez por alerta, y actualizando el
estado según el `AlertDeliveryResult` devuelto -- exactamente igual que
en la Etapa 6.9. La única novedad es que, en producción, `self._channel`
ya no es un sink individual: es un `CompositeNotificationChannel` que
internamente reparte esa única llamada `deliver()` entre todos los
canales habilitados en `config.yaml`.

### 24.4 `CompositeNotificationChannel`

Recibe una colección de canales en el constructor. `deliver(alert)`
itera esa colección y llama a `channel.deliver(alert)` uno por uno,
envolviendo cada llamada en su propio `try/except`: si un canal lanza
una excepción (ej. un placeholder con `NotImplementedError`) o devuelve
`AlertDeliveryResult(success=False, ...)`, se registra el error (vía
`logging`) y se continúa con el siguiente canal -- nunca se detiene la
iteración completa. El resultado agregado es
`AlertDeliveryResult(success=True, ...)` únicamente si **todos** los
canales tuvieron éxito (no basta con que uno solo lo tenga): así, si un
canal real (ej. Slack en una etapa futura) falla mientras logging sigue
funcionando, la alerta permanece reintentable (`PENDING`/`FAILED` según
`max_attempts`) en vez de marcarse `DELIVERED` solo porque el canal más
trivial no falló. `error_message` concatena los errores de los canales
que fallaron (con el nombre de la clase del canal, para poder
diagnosticar cuál fue). Si la colección de canales está vacía (todos los
flags de `inspection_notifications` en `false`), `deliver()` es un no-op
exitoso -- comportamiento esperado y documentado, no un error: si el
usuario deshabilitó todos los canales, no hay nada que pueda fallar.

### 24.5 Responsabilidades

- **`AlertDeliveryService`**: lectura de `PENDING`, orquestación de
  reintentos, actualización de estado -- desconoce por completo qué
  canales existen.
- **`CompositeNotificationChannel`**: reparte una entrega entre N
  canales, aísla los fallos de cada uno, agrega un único resultado.
- **Cada canal concreto**: sabe entregar (o, por ahora, fallar
  explícitamente) por su propio medio; no sabe nada de reintentos,
  persistencia ni de los demás canales.
- **Composition Root**: única capa que decide, según
  `config.yaml -> paper_trading.inspection_notifications`, qué canales
  concretos entran en el `CompositeNotificationChannel`.

### 24.6 Extensibilidad

Agregar un canal real en una etapa futura (ej. Slack) significa
únicamente: (a) reemplazar el cuerpo de `SlackNotificationChannel.deliver()`
por la llamada real, sin tocar su firma; (b) no tocar
`AlertDeliveryService` ni `CompositeNotificationChannel` en absoluto. El
mecanismo de extensión es agregar una entrada más a la lista que
`build_paper_trading_context()` pasa al `CompositeNotificationChannel`,
nunca una rama condicional dentro de la entrega.

### 24.7 Manejo de errores, reintentos e idempotencia

- Cada canal debe capturar sus propios errores estructurales cuando sea
  posible y devolver `AlertDeliveryResult(success=False, ...)` (mismo
  contrato ya exigido en la Etapa 6.9); si aun así lanza una excepción
  (como los 4 placeholders, que lanzan `NotImplementedError` a
  propósito), `CompositeNotificationChannel` la captura por él.
- Los reintentos (`max_alert_delivery_attempts`, `DELIVERED` nunca se
  reenvía, `FAILED` al agotar intentos) siguen siendo responsabilidad
  exclusiva de `AlertDeliveryService` -- ni el canal individual ni el
  composite necesitan saber cuántas veces se intentó.
- Idempotencia: `deliver()` de cualquier canal no debe asumir que se
  llama una sola vez para una alerta dada (el mismo alert puede
  reintentarse); los placeholders son deliberadamente puros (lanzan
  siempre lo mismo, sin efecto secundario ni estado), y
  `CompositeNotificationChannel` no mantiene estado entre llamadas.

### 24.8 Backward compatibility

`alert_sink.py` (Etapa 6.9) se conserva íntegro: `LoggingInspectionAlertSink`/
`NullInspectionAlertSink` pasan a ser alias directos
(`LoggingInspectionAlertSink = LoggingNotificationChannel`) de las
clases nuevas -- misma implementación, mismo nombre, mismo constructor,
para que ningún import ni prueba existente de la Etapa 6.9 se rompa.
`InspectionAlertSink` (el Protocol viejo) se conserva sin cambios;
`AlertDeliveryService` pasa a tipar contra `InspectionNotificationChannel`
en su lugar, pero como ambos Protocols son estructuralmente idénticos
(`deliver(alert) -> AlertDeliveryResult`), cualquier objeto que ya
cumplía uno cumple el otro automáticamente (duck typing) -- no hace
falta migrar ningún doble usado en pruebas existentes.

### 24.9 Configuración

Nuevo bloque opcional `paper_trading.inspection_notifications`
(`logging`/`email`/`slack`/`telegram`/`webhook`, todos `bool`).
`logging=true` por defecto (preserva exactamente el comportamiento ya
aprobado en la Etapa 6.9, donde `LoggingInspectionAlertSink` era el
único canal); los otros 4, `false` por defecto. Una `config.yaml` sin
este bloque sigue funcionando idéntico a como lo hacía antes de esta
etapa.

### 24.10 Explícitamente fuera de alcance

SMTP real, Slack API real, Telegram API real, webhooks HTTP reales,
secretos/tokens/credenciales/OAuth para cualquiera de ellos. Los 4
canales nuevos son placeholders que documentan la forma final de la
interfaz, no integraciones funcionales.

## 25. Robustez e idempotencia de entrega por canal (Etapa 6.10.1)

Corrección posterior a la auditoría formal de la Etapa 6.10 (veredicto
"APROBADA CON CORRECCIONES"). Resuelve 3 riesgos confirmados por prueba
directa durante la auditoría, sin tocar dominio/reconciliación/reservas/
Dashboard ni implementar ningún canal real.

### 25.1 Corrección 1 -- excepciones directas siempre se persisten

`AlertDeliveryService.deliver_pending_alerts()` ya no depende de que el
canal capture sus propios errores: envuelve `self._channel.deliver(alert)`
en su **propio** `try/except`. Si `deliver()` lanza, se construye un
`AlertDeliveryResult(success=False, error_message=str(exc), ...)`
sintético con el mismo `Clock` ya inyectado (nuevo parámetro
`clock: Clock = SystemClock()` en el constructor, con valor por defecto
para no romper las dos llamadas posicionales existentes) y se procesa
exactamente igual que cualquier fallo normal: `delivery_attempts` se
incrementa, `last_error` se guarda, y `status` pasa a `FAILED` al
alcanzar `max_attempts` -- nunca queda en reintento infinito sin rastro.

### 25.2 Corrección 2 -- idempotencia por canal (`InspectionAlertChannelDelivery`)

Nueva entidad `InspectionAlertChannelDelivery` (alert_id, channel_name,
status, delivery_attempts, last_error, delivered_at, updated_at;
reutiliza `AlertStatus` -- PENDING/DELIVERED/FAILED, mismo significado
que a nivel de alerta), persistida en la tabla nueva
`paper_trading_inspection_alert_channel_deliveries` (PK compuesta
`(alert_id, channel_name)`, `FOREIGN KEY(alert_id)`). Tres métodos
nuevos en `PaperTradingRepository`: `get_alert_channel_delivery`,
`fetch_alert_channel_deliveries`, `upsert_alert_channel_delivery`
(upsert único -- crear-si-no-existe y actualizar son la misma
operación, sin necesidad de una "plataforma" de métodos separados por
transición de estado).

`CompositeNotificationChannel` deja de ser el único responsable de la
lógica de reintentos: ahora recibe `repository` y `max_attempts` en su
constructor y, por cada canal (en el orden determinista de la lista),
consulta el estado persistido antes de decidir qué hacer:

- `DELIVERED` -> se omite por completo (nunca se vuelve a invocar `deliver()`).
- `FAILED` (terminal, alcanzó su propio `max_attempts`) -> se omite,
  pero su error se sigue reportando como parte del fallo agregado.
- Ausente o `PENDING` -> se invoca `channel.deliver()` (con el mismo
  `try/except` de la Etapa 6.10, nunca deja propagar una excepción de
  un placeholder), y el resultado (éxito o fallo, con su propio contador
  de intentos **por canal**) se persiste vía `upsert_alert_channel_delivery`.

El resultado agregado (`AlertDeliveryResult`) gana un campo nuevo,
`terminal: bool = False` (compatible hacia atrás, con default): es
`True` cuando al menos un canal alcanzó su propio `FAILED` terminal en
esta pasada o en una anterior. `AlertDeliveryService` marca la alerta
completa como `FAILED` si `attempts >= max_attempts` **o** si
`result.terminal` es `True` -- así "al menos un canal en estado
terminal FAILED" fuerza el `FAILED` de la alerta completa sin esperar a
que el contador de intentos *de la alerta* (distinto del contador *por
canal*) también se agote. La alerta completa solo llega a `DELIVERED`
cuando **todos** los canales de la lista están `DELIVERED` (ya sea en
esta pasada o en una anterior) -- un canal exitoso nunca recibe la
alerta una segunda vez, sin importar cuántas veces se reintente el
lote completo. Todo el estado vive en SQLite, nunca en memoria del
proceso: sobrevive reinicios, nuevas instancias y reconstrucciones de
la Composition Root.

### 25.3 Corrección 3 -- placeholders bloqueados en el arranque

`build_paper_trading_context()` (vía `_build_notification_channel()`)
valida, antes de construir ningún canal, que ninguno de
`email`/`slack`/`telegram`/`webhook` esté en `true` -- si alguno lo
está, lanza `ValueError` de inmediato, con un mensaje que nombra
explícitamente cada canal habilitado todavía no implementado. Nunca se
llega a instanciar el placeholder ni a intentar una entrega. Solo
`logging` puede valer `true` en esta etapa; los 5 en `false`
(incluido `logging=false`) es una configuración válida y probada:
`CompositeNotificationChannel([])` es un no-op exitoso explícito
(`success=True` sin invocar nada), no un error.

### 25.4 Compatibilidad

- `sink=` (nombre del parámetro anterior a la Etapa 6.10) **no se
  restaura**: `channel` queda como nombre oficial, decisión explícita
  documentada aquí (sin uso interno de `sink=` en todo el repositorio,
  confirmado por auditoría). Se agrega una prueba que fija la firma
  actual del constructor para detectar cualquier cambio accidental futuro.
- `LoggingInspectionAlertSink`/`NullInspectionAlertSink` (alias de la
  Etapa 6.9) se conservan sin ningún cambio; se agregan pruebas
  explícitas de identidad (`is LoggingNotificationChannel`/
  `is NullNotificationChannel`).
- La deduplicación de alertas (`deduplication_key`, Etapa 6.9) no se
  toca: sigue operando exclusivamente a nivel de creación de la alerta,
  antes y de forma completamente independiente de esta corrección (que
  opera después, a nivel de entrega).

## 26. Arquitectura de plantillas de notificación (Etapa 6.11)

Separación completa entre **qué se comunica** (contenido de una
alerta) y **cómo se comunica** (transporte por un canal concreto).
Hasta esta etapa, un canal recibía directamente una `InspectionAlert`
y decidía por su cuenta qué texto construir a partir de ella (ver
`LoggingNotificationChannel.deliver()` en la Etapa 6.10). Eso acoplaba
el formato del mensaje al canal: agregar Telegram, Email o Slack en el
futuro habría significado repetir la misma lógica de formateo en cada
canal nuevo, con el riesgo de que cada uno mostrara un contenido
ligeramente distinto para la misma alerta.

### 26.1 Nuevo módulo: `notification_templates.py`

Patrón Strategy, igual que `notification_channels.py` (§24), pero para
el contenido en vez del transporte:

- **`InspectionNotificationTemplate`** (`Protocol`): una única
  responsabilidad, `render(alert: InspectionAlert) -> NotificationMessage`.
  Nunca lanza para una alerta válida -- es una función pura sobre datos
  ya validados por quien construyó la `InspectionAlert` (AlertBuilder,
  Etapa 6.9).
- **`NotificationMessage`** (dataclass congelada): el contrato de
  contenido que cualquier canal puede transportar. Campos: `title`,
  `body`, `severity` (reutiliza `IssueSeverity`), y `metadata`
  (`Mapping[str, str]`, congelado con `MappingProxyType` para que ni
  siquiera el dict subyacente pueda mutarse tras construir el mensaje).
  Deliberadamente **no** contiene HTML, Markdown específico, URLs, ni
  ninguna referencia a Telegram/Slack/Email -- es agnóstico a cualquier
  canal concreto. `metadata` es la única vía por la que un canal puede
  recuperar identificadores no presentacionales que necesite (ver
  §26.4) sin volver a conocer `InspectionAlert`.
- **`DefaultInspectionNotificationTemplate`**: única plantilla usada en
  producción en esta etapa (sin configuración nueva, ver §26.5).
  Genera un título fijo por `AlertType` (7 valores, ver
  `_TITLES_BY_ALERT_TYPE`) y un cuerpo de texto plano con el mensaje de
  la alerta más, cuando corresponden, una línea de código de issue, una
  línea de entidad (tipo, id, exchange y símbolo si están presentes) y
  la fecha de creación en ISO 8601. Para `INSPECTION_FAILED`/
  `SYSTEM_RECOVERED` (sin `issue_identity`/`issue_code`, ver
  `alert_models.py`), las líneas correspondientes simplemente se omiten
  en vez de mostrar un placeholder vacío.

### 26.2 Flujo antes y después

Antes (Etapa 6.10/6.10.1):

```
alert (InspectionAlert)
  -> channel.deliver(alert)
```

El canal conocía `InspectionAlert` por completo (`alert.title`,
`alert.message`, `alert.severity`, `alert.alert_type`, ...) y construía
su propio texto de salida.

Después (Etapa 6.11):

```
alert (InspectionAlert)
  -> template.render(alert) -> NotificationMessage
  -> channel.deliver(message)
```

`AlertDeliveryService.deliver_pending_alerts()` recibe un
`InspectionNotificationTemplate` inyectado (nuevo parámetro
`template: InspectionNotificationTemplate = DefaultInspectionNotificationTemplate()`,
con default para no romper ninguna construcción existente) y, por cada
alerta, llama primero a `self._template.render(alert)` y pasa el
`NotificationMessage` resultante a `self._channel.deliver(message)`. El
servicio nunca construye el contenido él mismo: solo orquesta la
secuencia. Ningún canal (`LoggingNotificationChannel`,
`NullNotificationChannel`, los 4 placeholders, ni
`CompositeNotificationChannel`) vuelve a recibir ni a importar
`InspectionAlert`.

### 26.3 Cambios en los canales

- `LoggingNotificationChannel.deliver(message)`: escribe
  `message.title`/`message.body` vía `logging`, eligiendo el nivel
  (`error`/`warning`/`info`) según `message.severity` -- ya no
  reconstruye ningún texto, solo transporta lo que la plantilla ya
  produjo.
- `NullNotificationChannel.deliver(message)`: ignora el mensaje por
  completo, sigue reportando éxito siempre (sin cambio de
  comportamiento).
- Los 4 placeholders (`Email`/`Slack`/`Telegram`/`WebhookNotificationChannel`)
  cambian únicamente el tipo del parámetro de `deliver()`; su cuerpo
  sigue lanzando `NotImplementedError` sin excepción.

### 26.4 `CompositeNotificationChannel`: sin cambios funcionales

Sigue funcionando exactamente igual que en la Etapa 6.10.1 (§25.2):
misma idempotencia por canal, mismo criterio de terminalidad, mismo
`try/except` alrededor de cada `channel.deliver()`. El único cambio es
el tipo que recibe y reenvía a cada canal (`NotificationMessage` en vez
de `InspectionAlert`). El `alert_id` que necesita para sus consultas a
`get_alert_channel_delivery()`/`upsert_alert_channel_delivery()` se
obtiene de `message.alert_id` (campo explícito desde la Etapa 6.11.1,
§26.x -- originalmente vivía en `message.metadata["alert_id"]`, ver
§26.x para el motivo del cambio), precisamente para que
`CompositeNotificationChannel` pueda seguir haciendo su trabajo sin
volver a conocer `InspectionAlert`.

### 26.5 Composition Root y configuración

`build_paper_trading_context()` construye `DefaultInspectionNotificationTemplate()`
y lo inyecta explícitamente como `template=` en `AlertDeliveryService`
-- ni el servicio ni ningún canal construyen su propia plantilla,
igual que ya era el caso para los canales concretos (§24.5). No se
agrega ninguna configuración nueva: `inspection_notifications` sigue
controlando únicamente qué canales se arman: la plantilla usada es
siempre `DefaultInspectionNotificationTemplate`, sin ningún flag para
elegir otra.

### 26.6 Por qué facilita Telegram, Email y Slack

Cuando se implemente un canal real, su `deliver(message)` ya recibirá
un `NotificationMessage` completo y agnóstico -- no necesitará saber
nada de `InspectionAlert`, `AlertType`, `IssueIdentity` ni de cómo se
arma el texto de una alerta. Un futuro `TelegramNotificationChannel`
real solo necesita decidir cómo transportar `message.title`/
`message.body` (ej. como un único mensaje de texto), y un futuro canal
con necesidades de formato distintas (ej. HTML para Email) podría
lograrlo con su propia plantilla alternativa que implemente
`InspectionNotificationTemplate`, sin tocar ningún canal existente ni
`AlertDeliveryService`.

### 26.7 Explícitamente fuera de alcance

Ninguna implementación real de Telegram/Slack/Email/Webhooks (sigue
igual que en la Etapa 6.10/6.10.1); ninguna dependencia nueva (`jinja2`,
`markdown`, `rich`, ni ninguna librería de plantillas externa); ningún
formato HTML/Markdown específico de canal; ninguna plantilla
alternativa a `DefaultInspectionNotificationTemplate` (se evalúa la
extensibilidad en §26.6, pero no se implementa ninguna otra plantilla
en esta etapa); ningún cambio de comportamiento funcional (mismo
resultado de entrega, mismos estados, misma idempotencia).

### 26.x Validación y robustez del contrato Template (Etapa 6.11.1)

Corrección posterior a la auditoría formal de la Etapa 6.11 (veredicto
"APROBADA CON CORRECCIONES"). Resuelve 4 riesgos confirmados por
prueba directa durante la auditoría, sin implementar ningún canal real
ni tocar Dashboard/Trading Engine/Reconciliation/Signals/AI.

**H1 -- excepciones de `template.render()` sin controlar.** Antes de
esta corrección, `AlertDeliveryService.deliver_pending_alerts()`
llamaba a `self._template.render(alert)` **fuera** del `try/except` que
protegía `channel.deliver()`. Una excepción del template (ej. un
`KeyError` de `_TITLES_BY_ALERT_TYPE` si se agregara un `AlertType`
nuevo sin actualizar el mapa) se propagaba sin control, abortando
`deliver_pending_alerts()` completo -- las demás alertas del lote ni
siquiera se procesaban. Corrección: `template.render(alert)` y su
validación (ver H4 más abajo) se movieron dentro del mismo
`try/except` que ya envolvía `channel.deliver()`. Cualquier excepción
del template se convierte ahora en un `AlertDeliveryResult(success=False, ...)`
sintético, exactamente igual que un fallo de canal: `delivery_attempts`
se incrementa, `last_error` se guarda, el estado pasa a `FAILED` al
agotar `max_attempts`, ningún canal se invoca, y el resto del lote
continúa sin interrupción.

**H2 -- `alert_id` sin validar permitía invocar un canal antes de fallar.**
Antes, `alert_id` vivía únicamente en `metadata["alert_id"]`, un valor
de tipo `Mapping[str, str]` sin ninguna garantía ni validación. Un
template que produjera un `alert_id` distinto al de la alerta real
hacía que `CompositeNotificationChannel` invocara el canal real
primero (efecto secundario ya ejecutado) y solo después fallara la
persistencia por violación de `FOREIGN KEY` -- sin que nada quedara
guardado, el siguiente intento repetía la invocación del canal real.
Corrección: `alert_id` pasa a ser un campo explícito, obligatorio e
inmutable de `NotificationMessage` (ya no vive en `metadata`).
`AlertDeliveryService` valida `message.alert_id == alert.id`
**antes** de llamar a `channel.deliver()`; si no coincide, se lanza un
`ValueError` interno ("NotificationMessage.alert_id does not match
InspectionAlert.id") que el mismo `try/except` de H1 convierte en un
fallo de entrega controlado -- ningún canal se invoca nunca con un
`alert_id` incorrecto, y por lo tanto tampoco se llega a violar ninguna
`FOREIGN KEY`. `CompositeNotificationChannel` deja de depender de
`metadata["alert_id"]` y usa directamente `message.alert_id`.

**H3 -- mensajes de error poco diagnosticables.** Al ser `alert_id` un
campo obligatorio de `NotificationMessage` (validado en su propio
`__post_init__`, ver más abajo), ya no puede faltar silenciosamente:
un `alert_id` vacío o compuesto solo de espacios lanza
`ValueError("NotificationMessage.alert_id must be a non-empty string.")`
al momento de construir el mensaje, con un texto que identifica
exactamente el campo y la causa -- nunca solo la palabra `"alert_id"`
como único rastro del error.

**H4 -- un template podía devolver `None` o un tipo incorrecto.**
`AlertDeliveryService` valida ahora `isinstance(message, NotificationMessage)`
inmediatamente después de `template.render(alert)`, antes de invocar
cualquier canal. Si el resultado no es una instancia de
`NotificationMessage` (`None`, un `str`, un `int`, etc.), se lanza un
`TypeError` interno ("InspectionNotificationTemplate.render() must
return NotificationMessage"), capturado por el mismo `try/except` de
H1: fallo controlado, sin invocar ningún canal, con el mismo
tratamiento de reintentos/`FAILED` que cualquier otro fallo de
entrega. Esta validación es una verificación del **contrato de la
plantilla**, no una rama por tipo de canal -- no reintroduce el patrón
`if`/`isinstance` por canal concreto que `AlertDeliveryService` tiene
prohibido (§24.2); una prueba dedicada (`test_paper_trading_composition.py`)
confirma que la única aparición de `isinstance(` en el archivo es
exactamente esa validación.

**`NotificationMessage.alert_id`**: campo `str` explícito, validado en
`__post_init__` (no vacío, no compuesto solo de espacios, debe ser
`str`), inmutable igual que el resto de los campos (dataclass frozen).
Ya no se duplica dentro de `metadata` -- `metadata` conserva únicamente
`alert_type`/`run_id` (información adicional no crítica para la
idempotencia). No se usa `assert` en ninguna de estas validaciones
(se desactivaría con `python -O`): todas usan `ValueError`/`TypeError`
explícitos.

**Por qué el canal nunca se invoca con un mensaje inválido**: las tres
validaciones (excepción de template, tipo incorrecto, `alert_id`
no coincidente) ocurren estrictamente antes de la línea
`self._channel.deliver(message)` dentro del mismo bloque `try`; si
cualquiera de ellas falla, el flujo salta directo al `except` sin
llegar jamás a invocar `deliver()`. Esto es lo que garantiza que, para
canales reales futuros, ningún efecto secundario externo (envío real a
Telegram/Slack/Email/un webhook) pueda ocurrir a partir de un mensaje
mal formado.

**Continuidad del lote e idempotencia**: ninguno de estos cambios
afecta la iteración `for alert in alerts:` de `deliver_pending_alerts()`
-- un fallo (de cualquiera de los 3 tipos) en una alerta nunca detiene
el procesamiento de las siguientes. La idempotencia por canal
(§25.2/§26.4) tampoco cambia: `CompositeNotificationChannel` sigue
usando `(alert_id, channel_name)` como clave compuesta, solo cambia de
dónde lee `alert_id` (`message.alert_id` en vez de
`message.metadata["alert_id"]`).

## 27. Canal de notificaciones Telegram (Etapa 6.12)

Primer canal externo real de `inspection_notifications`, construido
sobre la arquitectura ya aprobada (§24-§26.x): `AlertDeliveryService`
sigue sin conocer canales concretos, `TelegramNotificationChannel`
sigue sin conocer `InspectionAlert`, y la idempotencia por canal
(§25.2) sigue operando exactamente igual. Deshabilitado por defecto;
no requiere ninguna credencial mientras esté deshabilitado.

### 27.1 Flujo completo

```
InspectionAlert
  ↓
DefaultInspectionNotificationTemplate   (§26 -- sin cambios en 6.12)
  ↓
NotificationMessage                     (§26.x -- alert_id explícito, sin cambios en 6.12)
  ↓
TelegramNotificationChannel             (nuevo en 6.12: adapta el mensaje a texto plano)
  ↓
TelegramTransport (Protocol)            (nuevo en 6.12: abstracción de transporte)
  ↓
UrllibTelegramTransport                 (nuevo en 6.12: única implementación real)
  ↓
Telegram Bot API (POST /bot<token>/sendMessage)
```

### 27.2 Responsabilidades por capa

- **Template** (`notification_templates.py`, sin cambios en esta
  etapa): sigue siendo el único responsable de construir
  `title`/`body`/`severity` a partir de `InspectionAlert`. Telegram
  nunca reconstruye contenido de dominio -- solo adapta lo que la
  plantilla ya produjo.
- **`TelegramNotificationChannel`** (`notification_channels.py`):
  recibe únicamente `NotificationMessage`, nunca `InspectionAlert`. Su
  única responsabilidad de formato es `_format_telegram_text()` (una
  función privada y pura, ver §27.3). No accede al repositorio, no
  persiste estado, no decide reintentos (eso sigue siendo exclusivo de
  `CompositeNotificationChannel`/`AlertDeliveryService`, §25.2/§26.x) y
  realiza como máximo **una** solicitud HTTP por llamada a `deliver()`
  (ver §27.6). Valida `bot_token`/`chat_id`/`timeout_seconds` en su
  propio constructor, nunca contra la red.
- **`TelegramTransport`** (`telegram_transport.py`, `Protocol` +
  `UrllibTelegramTransport`): única capa que conoce `urllib`/el
  endpoint HTTP oficial de Telegram. Construye la solicitud POST,
  aplica el timeout, interpreta la respuesta JSON y convierte
  cualquier fallo en `TelegramTransportError` con un mensaje
  sanitizado. No conoce el formato del mensaje, no reintenta, no
  persiste, no lee variables de entorno.
- **Telegram Bot API**: el servicio externo real -- fuera del alcance
  del proyecto, solo se le habla vía HTTP estándar.

### 27.3 Formato del mensaje (`_format_telegram_text`)

Función privada y pura en `notification_channels.py`:

```
{message.title}

{message.body}

Severidad: {message.severity.value}   -- solo si severity is not None
```

Texto plano únicamente: nunca HTML, nunca Markdown específico de
Telegram (`*bold*`, `_italic_`, etc.), nunca incluye `metadata`
completa ni `alert_id` (decisión explícita: el texto es para lectura
humana, no para correlación -- `alert_id` ya vive fuera del mensaje
transportado, en el campo propio de `NotificationMessage`, §26.x).

### 27.4 Límite de longitud

`TELEGRAM_MAX_MESSAGE_LENGTH = 4096`. Si el texto formateado supera el
límite, se trunca de forma controlada y se agrega la marca
`"\n[Mensaje truncado]"` al final, garantizando que el resultado nunca
exceda `TELEGRAM_MAX_MESSAGE_LENGTH`. Esta etapa no divide un mensaje
largo en varios envíos (evita entregas parciales y una idempotencia
más compleja) -- queda para una etapa futura si se necesitara.

### 27.5 Timeout obligatorio

Toda solicitud real usa `urlopen(request, timeout=timeout_seconds)`
-- nunca una llamada sin timeout. `timeout_seconds` se valida (`> 0`)
en el constructor de `TelegramNotificationChannel`, con default
`10.0` si no se especifica.

### 27.6 Ausencia de reintentos internos

Ni `TelegramTransport` ni `TelegramNotificationChannel` reintentan
nada por sí mismos. Cada llamada a `deliver()` genera como máximo una
solicitud HTTP. Toda la lógica de reintentos (intentos globales,
intentos por canal, `PENDING`/`FAILED`, idempotencia) sigue siendo
exclusiva de `AlertDeliveryService`/`CompositeNotificationChannel`
(§25.2) -- Telegram encaja en esa arquitectura sin ningún cambio en
ninguna de las dos clases.

### 27.7 Idempotencia externa

La identidad persistente del canal (§25.2, tabla
`paper_trading_inspection_alert_channel_deliveries`) sigue siendo
`type(channel).__name__ == "TelegramNotificationChannel"` -- sin
cambios de diseño en esta etapa (la limitación conocida de identidad
por clase, documentada en `CompositeNotificationChannel`, sigue
aplicando igual que a los demás canales). Un envío ya `DELIVERED`
nunca se reintenta, sobrevive reinicios y reconstrucciones de la
Composition Root, exactamente igual que `LoggingNotificationChannel`.

### 27.8 Manejo y sanitización de errores

`UrllibTelegramTransport` distingue: HTTP no exitoso, timeout, error de
red/DNS, JSON inválido (incluida una respuesta vacía) y `{"ok": false}`/
ausencia del campo `"ok"`. Todos se convierten en `TelegramTransportError`
con un mensaje claro (ej. `"Telegram API request failed (HTTP 401)."`,
`"Telegram API returned invalid JSON."`) que **nunca** incluye el
token, la URL completa, encabezados ni el cuerpo completo de la
respuesta -- solo, cuando está disponible, el código HTTP.
`TelegramNotificationChannel.deliver()` captura cualquier excepción del
transporte (incluida `TelegramTransportError`) y la convierte en un
`AlertDeliveryResult(success=False, ...)`, igual que
`LoggingNotificationChannel`.

### 27.9 Configuración

Reutiliza el sistema de configuración existente (`src/utils/config.py`),
sin crear uno nuevo:

- **Activación**: `paper_trading.inspection_notifications.telegram`
  (config.yaml, booleano, ya existía desde la Etapa 6.10) -- `false`
  por defecto. Se eligió reutilizar este flag en vez de agregar una
  variable de entorno `PAPER_TRADING_TELEGRAM_ENABLED` nueva, para no
  duplicar el mecanismo que ya decide qué canales entran en la lista.
- **Credenciales**: `TelegramSettings` (`bot_token`, `chat_id`), ya
  existente y reservada desde la Etapa 1.5 para "la futura integración
  con Telegram" -- esta etapa es esa integración. Se leen de
  `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` en `.env` (mismas variables
  que ya estaban documentadas en `.env.example`), nunca desde
  config.yaml. `PaperTradingConfig.telegram` reutiliza exactamente la
  misma instancia de `TelegramSettings` que `Settings.telegram`
  (construida una sola vez en `load_settings()`) -- nunca un segundo
  sistema de credenciales paralelo.
- **Timeout**: `TelegramSettings.timeout_seconds` (nuevo campo, default
  `10.0`), leído de `TELEGRAM_TIMEOUT_SECONDS` (nueva variable, opcional).
- **Validación**: `bot_token`/`chat_id`/`timeout_seconds` solo se
  validan cuando `inspection_notifications.telegram=true` -- si está
  deshabilitado (default), no se requiere ninguna credencial y
  `_build_notification_channel()` ni siquiera intenta construir
  `TelegramNotificationChannel`. La validación ocurre en el propio
  constructor del canal (mensajes claros, sin exponer el secreto,
  §27.8), nunca contra la red.

### 27.10 Orden determinista de canales

`_build_notification_channel()` (composition.py) agrega
`LoggingNotificationChannel` primero (si `logging=true`) y
`TelegramNotificationChannel` después (si `telegram=true`) -- mismo
orden documentado en el ejemplo conceptual de esta etapa. Cambiar este
orden en el futuro debe documentarse aquí explícitamente.

### 27.11 Seguridad de secretos

El token nunca aparece en: logs (`TelegramTransportError` sanitiza
antes de que `TelegramNotificationChannel` lo convierta en
`AlertDeliveryResult.error_message`), mensajes de excepción,
representación de objetos, documentación (esta sección no incluye
ningún token de ejemplo con formato real), pruebas (usan valores
claramente ficticios como `"SECRET-TOKEN-VALUE"`/`"tok"`) ni commits.
`.env` está ignorado por git (`.gitignore`); `.env.example` solo
contiene placeholders vacíos. Ninguna prueba automatizada realiza una
conexión real (`urllib.request.urlopen` siempre se reemplaza por un
doble en las pruebas del transporte; el canal siempre recibe un
`FakeTelegramTransport` en las pruebas del canal).

### 27.12 Explícitamente fuera de alcance

Slack/Email/Webhooks siguen bloqueados como placeholders (§25.3, sin
cambios); ninguna dependencia nueva (`requests`/`httpx`/`aiohttp`/
`telegram`/`python-telegram-bot`/`telebot` -- solo `urllib`/`json` de
la biblioteca estándar); ningún reintento interno en transporte/canal;
ninguna división de mensajes largos en múltiples envíos; ningún envío
real durante la implementación de esta etapa.
