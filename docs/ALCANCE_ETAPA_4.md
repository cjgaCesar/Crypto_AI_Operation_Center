# Alcance de la Etapa 4 — Motor de Decisión de IA

> **Estado: EN REVISIÓN, NO APROBADA TODAVÍA.** Queda pendiente su revisión
> y aprobación formal antes de considerarla cerrada y antes de avanzar a
> cualquier etapa posterior (Dashboard, Telegram, Paper Trading, Trading
> Automático).

## Objetivo

Construir un **AI Decision Engine** completamente desacoplado que
interprete, explique y priorice las señales ya generadas por el motor de
reglas de la Etapa 3, sin reemplazarlo.

**La IA NO reemplaza el motor de señales.** El motor de reglas
(`src/signals/`) sigue siendo la única fuente oficial de las señales; la
IA únicamente consume su salida (`SignalSnapshot`), la interpreta y genera
una `AIRecommendation` (acción sugerida, confianza propia, nivel de
riesgo, razonamiento y factores positivos/negativos).

**Nota de revisión**: tras la primera versión de esta etapa, se hicieron 13
ajustes adicionales a pedido explícito del usuario, antes de la validación
final: (1) `RecommendationAction` pasó de 3 a 7 valores (Strong/Weak
Buy/Sell + Hold); (2) `RiskLevel` pasó de 3 a 5 valores (+ Very Low/Very
High); (3) `prompt_version` pasó de `str` a un Enum tipado `PromptVersion`;
(4) se agregó `processing_time_ms` (medido por `DecisionEngine` con
`time.perf_counter()`, únicamente alrededor de `provider.generate()`); (5)
se agregó `raw_response` opcional (para auditoría de proveedores reales
futuros); (6) se implementó la migración SQLite idempotente para ambas
columnas nuevas; (7) se fortalecieron las validaciones Pydantic de los 4
modelos; (8) se ampliaron las pruebas de `AIService` cubriendo el historial
de señales en 6 escenarios distintos; (9)-(11) se ampliaron
exhaustivamente las pruebas de `DummyProvider`, `DecisionEngine` y
`SQLiteAIRepository`/`PostgresAIRepository` (nuevo); (12) se documentó con
más detalle la separación `Settings.ai`/`Settings.ai_engine` y se acotó
`temperature` a un rango razonable (0.0-2.0); (13) `settings.ai_engine.enabled
= false` ahora hace que `AIService` **no se instancie** (antes solo se
omitía su ejecución). Ver el detalle de cada decisión más abajo.

## Flujo completo

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
(`SignalEngine`, Etapa 3): `AIService` solo lee una señal ya calculada,
nunca recalcula ninguna regla ni ningún indicador.

Ampliando el primer eslabón (de dónde viene todo) y el último (a dónde va
después de esta etapa):

```
Binance -> MarketData -> ... -> ai_recommendations -> Dashboard (futura) ->
Paper Trading (futura) -> Trading Automático (futura)
```

## Incluido en esta etapa

1. **Módulo `src/ai/`**, con:
   - `context.py` — modelo `MarketContext` (todo lo que la IA necesita
     saber de un símbolo: precio > 0, indicadores, última señal, historial
     reciente de señales) + `build_market_context()`.
   - `recommendation.py` — enum `RecommendationAction` (7 valores: Strong
     Buy, Buy, Weak Buy, Hold, Weak Sell, Sell, Strong Sell), enum
     `RiskLevel` (5 valores: Very Low, Low, Medium, High, Very High) +
     modelo `AIRecommendation` (resultado final, incluyendo
     `processing_time_ms` y `raw_response`).
   - `explanation.py` — modelo `AIExplanation` (vista legible derivada de
     una `AIRecommendation`, para un futuro Dashboard) + `build_explanation()`.
   - `models.py` — reexporta los modelos anteriores (+ `PromptVersion`)
     desde un solo lugar.
   - `base.py` — interfaz `AIProvider` + modelo `AIProviderResponse`
     (respuesta cruda de un proveedor, antes de completarse como
     `AIRecommendation`; incluye `raw_response` opcional).
   - `providers/` — `DummyProvider` (implementado, sin IA real, respuestas
     deterministas), `OpenAIProvider` y `ClaudeProvider` (estructura
     preparada, NO conectadas).
   - `prompt_builder.py` — `PromptBuilder` + enum `PromptVersion` (`V1 =
     "v1"`): arma el prompt a partir de un `MarketContext`, sin ninguna
     lógica de negocio.
   - `decision_engine.py` — `DecisionEngine`: orquesta
     `MarketContext -> PromptBuilder -> AIProvider -> AIRecommendation`,
     mide `processing_time_ms` con `time.perf_counter()` alrededor de
     `provider.generate()`, y copia `raw_response`. No conoce SQLite,
     Binance ni Dashboard, y no atrapa excepciones del proveedor.
   - `repository.py` — interfaz `AIRepository`.
   - `sqlite_repository.py` — `SQLiteAIRepository` (en uso, con migración
     idempotente).
   - `postgres_repository.py` — `PostgresAIRepository` (stub, NO implementado).
   - `service.py` — `AIService`: lee la última señal (y su historial
     reciente) e indicadores/precio ya guardados, ejecuta `DecisionEngine`,
     guarda el resultado.

2. **Tabla nueva e independiente `ai_recommendations`** (16 columnas), sin
   modificar `market_data`, `market_indicators` ni `market_signals`.

3. **Configuración `config.yaml -> ai`**: `enabled`, `provider`, `model`,
   `temperature` (validado entre 0.0 y 2.0), `max_tokens`, `system_prompt`,
   `dummy_delay`. La clave `future_api_key` (mencionada en la solicitud) se
   implementó como variable de entorno (`AI_FUTURE_API_KEY`, en
   `Settings.ai_engine`), no en `config.yaml`, porque el proyecto nunca
   guarda secretos en ese archivo (ver más abajo, "Decisiones de diseño").

4. **`main.py` actualizado**: encadena
   `MarketDataService → IndicatorService → SignalService → AIService` en
   cada ciclo. `settings.ai_engine.enabled=false` hace que `build_services()`
   **no instancie** `AIService` (ni `DecisionEngine` ni el `AIProvider`
   activo): el 4to elemento que devuelve es `None`, y `run_full_cycle()`
   simplemente omite ese paso, sin afectar a las 3 etapas anteriores.

## Decisiones de diseño relevantes (para que quede documentado el porqué)

- **La solicitud original nombraba `base.py`, `repository.py`,
  `context.py`, `recommendation.py`, `explanation.py` y `models.py` como
  archivos separados, pero las pruebas pedidas explícitamente mencionan
  `SQLiteAIRepository`** (no nombrado en la lista de archivos). Se resolvió
  así, siguiendo el mismo patrón ya usado en `src/database/` y
  `src/signals/`:
  - `base.py` → interfaz `AIProvider` (el componente intercambiable central
    de este módulo, igual que `ExchangeClient` en `src/market/base.py`).
  - `repository.py` → interfaz `AIRepository` (igual que
    `src/signals/base.py` → `SignalRepository`).
  - `sqlite_repository.py` → se agregó como implementación concreta de
    `AIRepository` (no estaba en la lista original, pero es indispensable
    para que exista `SQLiteAIRepository`, pedido explícitamente en la
    sección de pruebas).
  - `context.py`, `recommendation.py`, `explanation.py` → cada uno define
    su propio modelo Pydantic (mismo nombre que el archivo).
  - `models.py` → reexporta los 3 modelos desde un solo lugar
    (`from src.ai.models import MarketContext, AIRecommendation, ...`),
    para que el resto del código y las pruebas no tengan que saber en qué
    archivo vive cada uno.
- **`future_api_key` no se guarda en `config.yaml`**: el proyecto tiene la
  regla explícita, desde la Etapa 1.5, de que ningún secreto va en ese
  archivo (solo en `.env`). Se implementó como
  `Settings.ai_engine.future_api_key`, leído desde la variable de entorno
  `AI_FUTURE_API_KEY`, igual que `openai_api_key`/`anthropic_api_key` ya
  existentes en `Settings.ai`.
- **Existen dos clases de configuración de IA, sin fusionarse**:
  `AISettings` (ya existía desde la Etapa 1.5; solo guarda
  `openai_api_key`/`anthropic_api_key` leídos de `.env`) y
  `AIEngineSettings` (nueva, con el comportamiento del motor:
  `enabled`/`provider`/`model`/etc., leído de `config.yaml`). No se
  renombró ni se reusó `AISettings` porque ya hay pruebas existentes
  (`tests/test_utils_config.py`) que dependen de `settings.ai.openai_api_key`;
  fusionarlas habría sido una modificación innecesaria de una
  funcionalidad ya aprobada.
- **`DummyProvider` no genera texto aleatorio**: deriva su respuesta
  determinista de la línea `"Signal Type: ..."` que `PromptBuilder` ya
  escribe en el prompt (el mismo veredicto que el motor de señales de la
  Etapa 3 calculó). Esto demuestra el pipeline completo de forma
  significativa (la recomendación sí refleja la señal real) sin usar
  ningún modelo de lenguaje.
- **`OpenAIProvider`/`ClaudeProvider` lanzan `NotImplementedError`**,
  siguiendo exactamente el mismo patrón que
  `PostgresMarketDataRepository`/`PostgresIndicatorRepository`/
  `PostgresSignalRepository`: la estructura existe, las credenciales ya
  están preparadas (`Settings.ai`), pero no se conecta ninguna API real
  (fuera de alcance explícito de esta etapa).
- **`AIRecommendation.confidence` es numérica (0.0-100.0), no un Enum como
  `SignalSnapshot.confidence`**: son dos conceptos distintos, documentados
  explícitamente en `src/ai/recommendation.py` para no repetir la
  confusión de conceptos que motivó la revisión 2 de la Etapa 3 (ver
  `ALCANCE_ETAPA_3.md`). `SignalSnapshot.confidence` mide el acuerdo entre
  las 5 reglas del motor de señales (un `ConfidenceLevel` categórico);
  `AIRecommendation.confidence` es la certeza autoreportada por el
  proveedor de IA sobre su propia recomendación (un número).
- **`ai_recommendations` guarda TODOS los campos de `AIRecommendation`**
  (incluyendo `advantages`, `risks` y `prompt_version`), no solo los 10
  campos mínimos listados en la solicitud original
  (`exchange, symbol, recommendation, confidence, risk, summary, reasoning,
  provider, model, created_at`). Omitir `advantages`/`risks` habría
  perdido justo los "Factores positivos"/"Factores negativos" que la
  sección de explicabilidad exige poder consultar después — la misma
  razón por la que la Etapa 3 terminó guardando `reason`/`rule_strength`
  más allá del mínimo pedido en su primera ronda.
- **`advantages` y `risks` se guardan como JSON** en una columna `TEXT`
  (`json.dumps`/`json.loads`), la forma estándar de persistir una lista en
  SQLite sin inventar un formato de texto propio.
- **`AIService` excluye la última señal de `recent_signals`** comparando
  `history[:-1]` (todo menos el último elemento), no una comparación de
  identidad de objetos: `fetch_history` reconstruye objetos nuevos desde
  SQLite en cada llamada, así que comparar por identidad (`is`) nunca
  coincidiría con el objeto devuelto por `fetch_latest`.
- **El límite de historial reciente (`_RECENT_SIGNALS_LIMIT = 5`) no es
  configurable desde `config.yaml`**: es un límite de cuánto contexto
  entra en el prompt, no un umbral de negocio (a diferencia de los
  umbrales de `signals.rules`, que sí son configurables).
- **`AIExplanation` no se persiste en `ai_recommendations`**: es una vista
  derivada (`build_explanation()`), pensada para un futuro Dashboard, que
  reformatea una `AIRecommendation` ya guardada. Guardarla también
  duplicaría datos ya presentes en `AIRecommendation` sin agregar
  información nueva.
- **`AIService.run_cycle()` omite un símbolo si falta la señal o el
  precio**, igual que `SignalService` omite un símbolo si faltan
  indicadores o precio: ningún componente falla de forma silenciosa; cada
  omisión queda registrada en el log con `logger.warning`.
- **`RecommendationAction`/`RiskLevel` se ampliaron manteniendo los valores
  de texto originales sin cambios** (`"Buy"`, `"Sell"`, `"Hold"`,
  `"Low"`, `"Medium"`, `"High"`): cualquier `AIRecommendation` ya generada
  con los 3/3 valores originales sigue siendo válida sin ninguna
  migración de datos. `DummyProvider` sigue usando solo los 3 valores
  originales de cada enum a propósito (los niveles fuertes/débiles y los
  extremos quedan disponibles recién cuando se conecte un proveedor real
  capaz de expresar esos matices).
- **`PromptVersion` es un Enum (no un `str` suelto)** para que
  `AIRecommendation.prompt_version` no acepte cualquier texto arbitrario:
  solo una versión de prompt conocida y válida (`PromptVersion.V1 = "v1"`
  hoy). Si el formato del prompt cambia de forma incompatible, se agrega
  un nuevo miembro (`V2`, etc.) en vez de reemplazar `V1`, para poder
  seguir reconstruyendo recomendaciones históricas.
- **`processing_time_ms` mide únicamente `provider.generate(prompt)`**, no
  el armado del prompt ni el guardado en SQLite: es el tiempo que le tomó
  específicamente al proveedor de IA responder, el dato relevante para
  evaluar la latencia de un proveedor real en el futuro.
  `time.perf_counter()` (reloj monotónico) se eligió sobre `datetime.now()`
  porque no se ve afectado por ajustes del reloj del sistema.
- **`raw_response` existe para auditoría/depuración de proveedores reales
  futuros**: hoy siempre es `None` (`DummyProvider` no tiene ninguna
  respuesta "cruda" que preservar, ya genera la respuesta ya
  estructurada). Se persiste como columna `TEXT` nullable; `sqlite3`
  traduce `None <-> NULL` automáticamente, sin conversión manual.
- **La migración de `ai_recommendations` reutiliza el mismo patrón que
  `SQLiteSignalRepository`** (`PRAGMA table_info` + `ALTER TABLE ... ADD
  COLUMN` solo para las columnas realmente faltantes), verificada con una
  base construida manualmente con el esquema anterior (sin
  `processing_time_ms` ni `raw_response`) y 3 llamadas consecutivas a
  `init()` (ver `tests/test_ai_sqlite_repository.py`).
- **`ai.enabled=false` ahora impide que `AIService` se instancie**, no solo
  que se ejecute: antes de este ajuste, `build_services()` siempre
  construía `AIService` (incluyendo `ai_repository.init()`, creando la
  tabla) aunque `run_full_cycle()` no lo ejecutara. Se cambió para que
  `build_services()` devuelva `None` como 4to elemento cuando está
  deshabilitado, verificado explícitamente: con `ai.enabled=false`, la
  tabla `ai_recommendations` ni siquiera se crea (`tests/test_main.py`).

## Explícitamente fuera de esta etapa

- ❌ Conexión real a OpenAI o Anthropic (estructura preparada, sin API key
  usada en ningún lugar del proyecto).
- ❌ Dashboard, Telegram, Paper Trading, Trading Automático.
- ❌ Machine Learning, Fine Tuning, Embeddings, RAG, bases de datos
  vectoriales.
- ❌ Ninguna modificación a `MarketDataService`, `IndicatorEngine`,
  `IndicatorService`, `SignalEngine`, `SignalService` ni a sus reglas.
- ❌ Ninguna modificación a `market_data`, `market_indicators` ni
  `market_signals`.

## Criterio de validación de la Etapa 4

1. Todas las pruebas automatizadas (`pytest`) pasan.
2. `main.py` sigue sin contener lógica de negocio ni cálculos.
3. `DecisionEngine` no conoce SQLite, Binance ni Dashboard, y no atrapa
   excepciones del proveedor.
4. `ai_recommendations` se crea automáticamente y se llena correctamente,
   sin alterar `market_data`, `market_indicators` ni `market_signals`.
5. Una ejecución real genera recomendaciones de IA a partir de señales ya
   calculadas, usando `DummyProvider` (sin conexión a ninguna API real).
6. La migración de `ai_recommendations` (agregar `processing_time_ms` y
   `raw_response`) es completamente idempotente y no pierde registros.
7. `ai.enabled=false` impide que `AIService` se instancie y se ejecute,
   sin afectar a las Etapas 1, 1.5, 2 y 3.
8. No hay regresiones respecto de las Etapas 1, 1.5, 2 y 3.
9. El usuario ha revisado y aprobado esta etapa antes de avanzar a
   cualquier etapa posterior (Dashboard, Telegram, Paper Trading, Trading
   Automático).
