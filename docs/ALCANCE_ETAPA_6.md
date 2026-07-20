# Alcance de la Etapa 6.0 — Preparación de la arquitectura para Paper Trading

> **Estado: DISEÑO, SIN CÓDIGO.** Esta sub-etapa (6.0) no implementa Paper
> Trading. Su único entregable es documentación técnica de arquitectura.
> **No existe ninguna operación de compra o venta, simulada o real, al
> finalizar esta etapa.** Queda pendiente la revisión y aprobación formal
> del usuario antes de escribir la primera línea de código de Paper
> Trading (Etapa 6.1 en adelante).

## Objetivo

Diseñar, validar y documentar la arquitectura que utilizará el futuro
motor de Paper Trading (compra/venta simulada, sin dinero real ni
conexión a un exchange para operar), de forma que las etapas de
implementación posteriores puedan construirse **sumando módulos nuevos**,
sin reescribir nada de lo ya aprobado (Etapas 1 a 5).

Esta etapa es exclusivamente de **análisis y diseño**:

- No se crea ningún archivo de código (`.py`) nuevo.
- No se modifica ningún archivo de código existente.
- No se crean tablas, migraciones ni archivos de base de datos.
- No se agrega ninguna dependencia a `requirements.txt`.
- Solo se crea documentación (`docs/`) y se actualiza el roadmap del
  `README.md`.

## Entregables de esta etapa

1. [`docs/ARQUITECTURA_PAPER_TRADING.md`](ARQUITECTURA_PAPER_TRADING.md) —
   documento técnico completo: arquitectura general, modelo de dominio,
   flujo de una orden, estados de una orden, modelo de posiciones,
   modelo de cartera, modelo de PnL, riesgo, capital disponible, eventos
   del sistema, persistencia (diseño de tablas, sin crearlas), auditoría,
   integración con el Dashboard, integración futura con IA, y estrategia
   de pruebas.
2. Este documento (`ALCANCE_ETAPA_6.md`): objetivo, alcance, análisis del
   código existente (qué se reutiliza / extiende / aísla) y criterio de
   cierre.
3. Actualización del roadmap en `README.md` (una entrada nueva para la
   Etapa 6, sin tocar el resto del documento).

## Análisis del código existente

Antes de diseñar nada nuevo, se revisó completamente el código real del
proyecto (`src/database/`, `src/services/`, `src/signals/`, `src/ai/`,
`src/models/`, `src/dashboard/`, `src/utils/config.py`, `src/main.py`,
`config/config.yaml`, `tests/`) para decidir qué puede reutilizarse, qué
debe extenderse (sin romper nada aprobado) y qué debe permanecer
completamente aislado. El detalle completo está en
[ARQUITECTURA_PAPER_TRADING.md](ARQUITECTURA_PAPER_TRADING.md#0-análisis-del-código-existente);
resumen:

### Reutilizable tal cual (sin ningún cambio)

- Los 4 modelos de dominio ya existentes como **entrada de solo lectura**:
  `MarketTicker`, `IndicatorSnapshot`, `SignalSnapshot`, `AIRecommendation`.
- El patrón Repository/Service/Engine (inyección de dependencias por
  constructor, `run_cycle()` como único método público de orquestación,
  motor puro sin I/O separado del servicio que sí lo tiene).
- El patrón de conexión SQLite (una conexión nueva por llamada,
  `try/finally: conn.close()`, migración idempotente vía `PRAGMA
  table_info` + `ALTER TABLE ... ADD COLUMN`).
- El patrón de configuración (`@dataclass(frozen=True)` por sección,
  `config.yaml` para comportamiento, `.env` para secretos).
- El patrón de extensión de solo lectura del Dashboard
  (`DashboardRepository`/`SQLiteDashboardRepository`/`DashboardService`):
  reutiliza los métodos `fetch_*` de los repositorios existentes en vez
  de duplicar SQL, y abre su propia conexión `mode=ro` solo para
  consultas realmente nuevas.
- La convención de nombres de pruebas (`test_<dominio>_<sujeto>.py`).

### Debe extenderse (de forma aditiva, sin romper lo aprobado)

- `Settings` (`src/utils/config.py`): agregar una sección
  `PaperTradingSettings` nueva, siguiendo exactamente el mismo patrón que
  `AIEngineSettings`.
- `config/config.yaml`: agregar una sección `paper_trading:` nueva
  (`enabled`, límites de riesgo, etc.), sin tocar ninguna sección
  existente.
- `main.py` (`build_services()`/`run_full_cycle()`): agregar un 5to paso
  condicional (`Optional[PaperTradingService]`), con el mismo mecanismo
  de apagado explícito ya usado para `ai_engine.enabled` (si está
  deshabilitado, ni siquiera se instancia el repositorio).
- `DashboardRepository`/`SQLiteDashboardRepository`/`DashboardService`:
  agregar métodos nuevos de solo lectura (`get_latest_position`,
  `get_portfolio_history`, etc.), reutilizando el repositorio de Paper
  Trading, nunca duplicando su SQL.

### Debe permanecer aislado (módulo nuevo, propio)

- Un paquete nuevo `src/paper_trading/`, con la misma organización interna
  que `src/signals/`/`src/ai/` (enums, modelos, interfaz `base.py`,
  `sqlite_repository.py`, `postgres_repository.py` stub, motor(es) puro(s),
  servicio).
- Tablas nuevas e independientes (`paper_trading_*`), sin modificar
  `market_data`, `market_indicators`, `market_signals` ni
  `ai_recommendations`.
- Se confirmó (búsqueda exhaustiva en todo `src/`) que **no existe
  absolutamente ningún código previo** de órdenes, posiciones, cartera,
  PnL, riesgo o balances: este módulo es enteramente nuevo, sin nada que
  desenredar ni migrar.

## Explícitamente fuera de esta etapa (6.0)

- ❌ Cualquier línea de código de Paper Trading (modelos, motor, servicio,
  repositorio, configuración, página de Dashboard).
- ❌ Compra o venta, simulada o real.
- ❌ Órdenes, posiciones, cartera, riesgo, PnL, balances — como código;
  como **diseño**, sí son el contenido de esta etapa.
- ❌ Strategy Engine, Backtesting, Live Trading, Broker API, WebSockets.
- ❌ Cualquier modificación a `market_data`, `market_indicators`,
  `market_signals`, `ai_recommendations` o a las páginas del Dashboard.
- ❌ Cualquier migración o archivo de base de datos nuevo.
- ❌ Conexión real a un exchange para operar (fuera de alcance de todo el
  proyecto hasta que se apruebe explícitamente una etapa de Live Trading).

## Criterio de cierre de la Etapa 6.0

1. `docs/ARQUITECTURA_PAPER_TRADING.md` cubre los 15 puntos solicitados
   (arquitectura general, modelo de dominio, flujo de una orden, estados,
   posiciones, cartera, PnL, riesgo, capital disponible, eventos,
   persistencia, auditoría, integración con Dashboard, integración
   futura con IA, estrategia de pruebas).
2. El análisis del código existente identifica explícitamente qué se
   reutiliza, qué se extiende y qué permanece aislado, sin ambigüedad.
3. `git status` no muestra ningún archivo `.py` nuevo ni modificado, solo
   documentación y el roadmap del `README.md`.
4. La regresión completa (`pytest`) sigue en 100% verde, sin ningún
   archivo de prueba nuevo ni modificado (no hay código nuevo que probar
   todavía).
5. El usuario ha revisado y aprobado esta arquitectura antes de que se
   escriba la primera línea de código de Paper Trading (Etapa 6.1 en
   adelante).
