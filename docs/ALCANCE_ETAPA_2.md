# Alcance de la Etapa 2 — Motor de indicadores técnicos

## Objetivo

Agregar el cálculo de indicadores técnicos sobre el historial de precios ya
recolectado, sin modificar la forma en que se consultan ni se guardan los
datos crudos de mercado (Etapa 1 / 1.5), y respetando la arquitectura
modular existente (interfaces de exchange y de repositorio).

## Incluido en esta etapa

1. **Motor de indicadores** (`src/services/indicator_engine.py`), que
   calcula, a partir del historial de precios de un símbolo:
   - SMA (media móvil simple)
   - EMA rápida, media y lenta (medias móviles exponenciales)
   - RSI (índice de fuerza relativa, suavizado de Wilder)
   - MACD (línea, señal e histograma)
   - Bandas de Bollinger (superior, media, inferior)
   - VWAP (aproximado, ver limitación más abajo)

2. **Modelo de datos `IndicatorSnapshot`** (`src/models/indicator_data.py`),
   con todos los indicadores como campos opcionales: mientras no haya
   historial suficiente para un indicador puntual, ese campo queda en
   `None` en vez de forzar un valor incorrecto.

3. **Tabla independiente `market_indicators`**, separada de `market_data`.
   `market_data` sigue conteniendo únicamente datos crudos del mercado, sin
   ningún cambio de esquema en esta etapa (más allá de lo ya hecho en la
   Etapa 1.5). Esta separación permite recalcular indicadores históricos si
   cambian los periodos de configuración, sin volver a consultar Binance.

4. **`IndicatorRepository`**, nueva interfaz de repositorio
   (`src/database/base.py`), implementada por `SQLiteIndicatorRepository`
   (en uso) y con un stub `PostgresIndicatorRepository` preparado para una
   futura migración, igual que ya existía para `market_data`.

5. **`IndicatorService`** (`src/services/indicator_service.py`), que
   coordina: leer el historial de un símbolo (`MarketDataRepository`),
   calcularle los indicadores (`IndicatorEngine`) y guardarlos
   (`IndicatorRepository`). Es lógica de negocio, separada de main.py.

6. **Configuración de periodos en `config.yaml` → `indicators`**: todos los
   periodos (sma, ema_fast/medium/slow, rsi, macd_fast/slow/signal,
   bollinger_period/stddev, vwap) son ajustables sin tocar código.

7. **`main.py` sigue siendo solo un coordinador**: arma ambos servicios
   (`MarketDataService`, `IndicatorService`) y, en cada ciclo, primero
   consulta y guarda los precios, y luego recalcula los indicadores con el
   historial ya actualizado.

## Limitación conocida: ATR y ADX no se calculan todavía

`config.yaml` incluye los periodos `atr` y `adx` (tal como se definió al
planear esta etapa), pero el motor de indicadores **no los calcula**. Ambos
requieren datos de máximo y mínimo por vela (OHLC), que el endpoint que usa
este proyecto (`/api/v3/ticker/24hr`) no provee por intervalo — solo da el
máximo/mínimo acumulado de las últimas 24 horas, no el de cada consulta de
5 minutos. Calcularlos de forma aproximada solo con el precio de cierre
produciría un número que no sería un ATR/ADX real, lo cual sería riesgoso
si una etapa futura (motor de señales, trading) confiara en él para, por
ejemplo, calcular un stop-loss.

Para implementarlos correctamente en el futuro haría falta consultar el
endpoint de velas de Binance (`/api/v3/klines`), lo cual es una fuente de
datos adicional, fuera del alcance de esta etapa. Ver
[ARQUITECTURA.md](ARQUITECTURA.md) para más detalle.

## Aproximación del VWAP

El VWAP tradicional se calcula con el volumen negociado en cada intervalo.
Este proyecto solo consulta `volume_24h` (volumen acumulado de 24 horas que
reporta Binance), no el volumen de cada ventana de 5 minutos. El VWAP que
calcula esta etapa usa `volume_24h` como peso de cada lectura dentro de la
ventana (`sma` periodos), lo cual es una aproximación razonable pero no el
VWAP exacto de un exchange. Está documentado también en el código
(`src/services/indicator_engine.py`).

## Explícitamente fuera de esta etapa

- ❌ No se agregó inteligencia artificial.
- ❌ No se construyó el dashboard.
- ❌ No se integró Telegram.
- ❌ No se implementó ningún tipo de trading ni paper trading.
- ❌ No se conectó ninguna clave privada real.
- ❌ No se calculan ATR ni ADX (ver limitación arriba).
- ❌ No se modificó la tabla `market_data` ni la forma en que se consultan
  los precios crudos.

## Criterio de validación de la Etapa 2

1. Todas las pruebas automatizadas (`pytest`) pasan.
2. `main.py` sigue sin contener lógica de negocio ni cálculos.
3. Binance sigue implementado detrás de la interfaz común de exchanges.
4. Los indicadores se calculan correctamente sobre datos de prueba
   verificables a mano (precios constantes, tendencias puras).
5. `market_data` permanece con datos crudos únicamente; `market_indicators`
   contiene los indicadores calculados, en una tabla separada.
6. Una ejecución real de un solo ciclo consulta BTCUSDT/ETHUSDT/SOLUSDT,
   guarda los precios y calcula/guarda los indicadores disponibles con el
   historial existente.
7. El usuario ha revisado y aprobado esta etapa antes de avanzar a
   cualquier etapa posterior.
