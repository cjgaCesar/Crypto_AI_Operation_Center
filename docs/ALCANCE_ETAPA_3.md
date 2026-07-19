# Alcance de la Etapa 3 — Motor de Señales

> **Estado: EN REVISIÓN, NO APROBADA TODAVÍA.** Esta etapa ha pasado por
> dos rondas de ajuste de arquitectura (ver "Notas de revisión" abajo) a
> pedido explícito del usuario. Queda pendiente su revisión y aprobación
> formal antes de considerarla cerrada y antes de avanzar a la Etapa 4.

## Objetivo

Transformar los indicadores técnicos ya calculados (Etapa 2) en señales
estructuradas y configurables, sin usar inteligencia artificial, para que
la IA, el dashboard y el motor de trading de etapas futuras las consuman
directamente en vez de recalcular indicadores.

**Nota de revisión 1**: la primera versión de esta etapa hacía que cada
regla devolviera directamente un Enum propio (ej. `TrendResult.STRONG_BULLISH`)
y calculaba el score como un promedio simple de 3 puntos fijos por regla.
Se ajustó la arquitectura para que: (1) todas las reglas devuelvan un
modelo común `RuleResult` (con `direction`, `strength` continua y `reason`
en texto, no solo una categoría), (2) el score se calcule ponderando cada
regla según un peso configurable, y (3) `SignalSnapshot` conserve el
detalle completo (el `reason` de cada regla), para que la Etapa 4 (IA)
pueda explicar una señal sin recalcular nada.

**Nota de revisión 2**: se identificó que `RuleResult.label` seguía siendo
un `str` de texto libre (no tipado), y que la `strength` de cada regla no
quedaba persistida en `SignalSnapshot`. Se ajustó nuevamente para que: (1)
`label` sea un Enum específico por regla (`TrendLabel`, `EMALabel`,
`MACDLabel`, `RSILabel`, `BollingerLabel`), con `RuleResult` parametrizado
genéricamente (`RuleResult[TrendLabel]`, etc.) para evitar la ambigüedad de
valores de texto compartidos entre esos enums; (2) se agregaron los 5
campos `*_rule_strength` a `SignalSnapshot`, con validación Pydantic
0.0-1.0; (3) se revisó y documentó explícitamente el cálculo de
`confidence` (determinístico, sin depender de `Counter` ni de ningún
orden), con pruebas para 5 casos incluyendo empates; (4) `SignalSnapshot`
pasó a usar Enums directamente en sus campos de categoría, en vez de `str`
sueltos, serializados explícitamente (`.value`) al guardar en SQLite.

El resto de esta etapa (tabla independiente, reglas independientes, sin
IA, sin modificar Etapas 1/1.5/2) permanece igual en ambas revisiones.

## Incluido en esta etapa

1. **Módulo `src/signals/`**, con:
   - `enums.py` — `Direction`, `TrendStrength`, `ConfidenceLevel`,
     `SignalType`: vocabulario común reutilizado en todo el módulo.
   - `rule_result.py` — modelo `RuleResult` (`direction`, `strength`,
     `reason`, `label`), que devuelven las 5 reglas.
   - `engine.py` — `SignalEngine`: lógica de negocio pura, ejecuta las 5
     reglas y el agregador, sin I/O.
   - `service.py` — `SignalService`: lee indicadores/precio, ejecuta el
     motor, guarda el resultado, registra en logs.
   - `aggregator.py` — combina los 5 `RuleResult` en `score` (ponderado),
     `confidence`, `trend_strength` y `signal_type`.
   - `base.py` — interfaz `SignalRepository`.
   - `sqlite_repository.py` — `SQLiteSignalRepository` (en uso).
   - `postgres_repository.py` — `PostgresSignalRepository` (stub).
   - `rules/` — `TrendRule`, `EMARule`, `MACDRule`, `RSIRule`,
     `BollingerRule`, cada una un componente independiente que devuelve
     `RuleResult` (nunca un string suelto).

2. **Modelo `SignalSnapshot`** (`src/models/signal_data.py`, Pydantic), con
   el resultado final (`exchange`, `symbol`, `trend`, `trend_strength`,
   `ema_signal`, `macd_signal`, `rsi_signal`, `bollinger_signal`, `score`,
   `confidence`), el detalle de cada regla (`trend_reason`, `ema_reason`,
   `macd_reason`, `rsi_reason`, `bollinger_reason`) y el veredicto general
   (`signal_type`), además de `generated_at` (+ `id` autogenerado en la
   tabla).

3. **Tabla independiente `market_signals`**, sin modificar `market_data` ni
   `market_indicators`. Incluye migración automática de bases de datos
   creadas con la primera versión de la tabla (sin las columnas `*_reason`
   ni `signal_type`), sin perder registros existentes.

4. **Configuración completa en `config.yaml` → `signals`**: pesos por
   regla (`weights.trend/ema/macd/rsi/bollinger`), umbrales de
   clasificación del score final (`score.bullish/neutral/bearish`),
   umbrales de confianza y umbrales propios de cada regla, todos
   configurables (ningún valor mágico en el código).

5. **`main.py` actualizado como único Composition Root**: encadena
   `MarketDataService → IndicatorService → SignalService` en cada ciclo.

## Decisiones de diseño relevantes (para que quede documentado el porqué)

- **MACDRule no compara contra un snapshot anterior**: refleja la relación
  *actual* entre `macd_line` y `macd_signal` (no un evento de cruce
  detectado en ese instante). Mantiene la regla con una sola
  responsabilidad y sin necesitar historial.
- **RSIRule trata "Overbought" como alcista y "Oversold" como bajista**
  (interpretación de seguimiento de tendencia, no de contrarian/reversión),
  para ser consistente con el resto de reglas de esta etapa.
- **BollingerRule necesita el precio actual** (de `market_data`), a
  diferencia de las otras 4 reglas que solo usan `market_indicators`: las
  bandas por sí solas no dicen dónde está el precio dentro de ellas.
- **`score` se calcula ponderando `dirección × strength` de cada regla**
  por su peso configurado en `signals.weights` (no un promedio simple de 3
  puntos fijos por regla, como en la primera versión de esta etapa).
- **`confidence` mide el acuerdo entre las 5 reglas** (qué proporción
  comparte la inclinación mayoritaria en `direction`), no la fuerza del
  score ni los pesos.
- **`trend_strength` se deriva directamente de `TrendRule`** (su `label`
  contiene "Strong" → Strong; dirección no neutral → Medium; neutral →
  Weak).
- **`confidence.very_high` no vino en el ejemplo original** (solo se dieron
  high/medium/low): se agregó en `config.yaml` para completar las 5
  categorías pedidas (Very Low..Very High), como valor configurable, no
  fijo en código.
- **`signals.score.{bullish,neutral,bearish}` cambió de propósito**: en la
  primera versión eran los puntos fijos por regla; ahora son los umbrales
  que clasifican el score final (ya ponderado) en `SignalType`.
- **`SignalType` se agregó como campo adicional de `SignalSnapshot`**
  (más allá del mínimo pedido), para darle uso real al enum solicitado en
  vez de calcularlo y descartarlo.
- **El factor de normalización de `strength` en `EMARule`** (10× la banda
  neutral) es una elección de diseño razonable, no un valor pedido
  explícitamente, documentada en el código.
- **`RuleResult` es genérico (`RuleResult[TrendLabel]`, etc.)** en vez de
  usar un `Union` de los 5 enums de label: varios valores de texto se
  repiten entre esos enums (ej. "Neutral" existe en los 5), y un `Union`
  simple sería ambiguo sobre cuál enum usar al validar. La parametrización
  genérica hace que Pydantic valide y normalice `label` contra el enum
  exacto de cada regla, sin ambigüedad (verificado explícitamente:
  `test_rule_result_normalizes_shared_value_to_the_parameterized_enum_type`).
- **`confidence` se reescribió usando `.count()` + `max()` explícitos**, en
  vez de `Counter(directions).most_common(1)[0][1]`. El valor numérico ya
  era correcto en ambas versiones (`most_common()` siempre devuelve el
  conteo máximo real), pero la nueva versión es más fácil de auditar: no
  requiere conocer las reglas de desempate internas de `Counter` para
  confirmar que el resultado es determinístico.
- **Los campos de categoría de `SignalSnapshot` son Enums, no `str`**: se
  revisó explícitamente (punto 7 de la solicitud) y se decidió que
  Pydantic valide contra los Enums directamente, serializándolos a texto
  (`.value`) solo en la capa de repositorio (`SQLiteSignalRepository`), no
  en el modelo.
- **Los `*_reason` no llevan `min_length=1` en el modelo**: aunque las 5
  reglas siempre producen un `reason` no vacío para señales nuevas, el
  modelo debe poder reconstruir registros migrados desde el esquema
  anterior (que usan `''` como valor por defecto). Exigir no-vacío a nivel
  de modelo rompería la lectura de esos datos históricos.

## Explícitamente fuera de esta etapa

- ❌ Inteligencia artificial, Machine Learning, predicción de precios.
- ❌ Telegram, dashboard, paper trading, trading automático.
- ❌ ATR y ADX (siguen sin calcularse; ver docs/ALCANCE_ETAPA_2.md).
- ❌ Ninguna modificación a `MarketDataService`, `IndicatorEngine` ni
  `IndicatorService`.
- ❌ Ninguna modificación a `market_data` ni a `market_indicators`.

## Criterio de validación de la Etapa 3

1. Todas las pruebas automatizadas (`pytest`) pasan.
2. `main.py` sigue sin contener lógica de negocio ni cálculos.
3. Las 5 reglas son componentes independientes, cada una con una sola
   responsabilidad, sin conocerse entre sí.
4. `market_signals` se crea automáticamente y se llena correctamente, sin
   alterar `market_data` ni `market_indicators`.
5. Una ejecución real genera señales correctas a partir del historial de
   indicadores ya calculado.
6. No hay regresiones respecto de la Etapa 2 (mismas pruebas, mismo
   comportamiento de `MarketDataService`/`IndicatorEngine`/`IndicatorService`).
7. El usuario ha revisado y aprobado esta etapa antes de avanzar a
   cualquier etapa posterior (IA, Dashboard, Paper Trading, Trading
   Automático).
