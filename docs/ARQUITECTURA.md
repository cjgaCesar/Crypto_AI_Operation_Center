# Arquitectura del proyecto (desde la Etapa 1.5)

Este documento explica cómo está organizado el código a partir de la Etapa
1.5 (refactorización y preparación de arquitectura), y por qué se organizó
así. El objetivo de esta arquitectura es que las etapas futuras (IA,
múltiples exchanges, dashboard, Telegram, paper trading, trading
automatizado) se puedan agregar **sumando módulos nuevos**, sin tener que
reescribir los ya existentes.

## Principio general: interfaces primero, implementaciones después

En vez de que el resto del proyecto dependa directamente de "Binance" o de
"SQLite", depende de dos contratos (interfaces):

- `ExchangeClient` (`src/market/base.py`): "algo que sabe consultar precios
  de un exchange".
- `MarketDataRepository` (`src/database/base.py`): "algo que sabe guardar y
  leer datos de mercado".

Binance y SQLite son, hoy, la única implementación de cada uno. Agregar
Bybit, Coinbase, Kraken o PostgreSQL en el futuro significa crear una nueva
clase que cumpla el mismo contrato, sin tocar el resto del proyecto.

## Estructura de carpetas

```
Crypto_AI_Operation_Center/
├── .env.example          # Plantilla de credenciales (Binance, OpenAI, Anthropic, Telegram, CoinGecko, NewsAPI, DB)
├── config/
│   └── config.yaml       # Configuración de comportamiento (monedas, intervalo, límites, rutas)
├── data/
│   └── crypto_data.db    # Base de datos SQLite (se genera sola)
├── docs/
│   ├── ALCANCE_ETAPA_1.md
│   ├── ALCANCE_ETAPA_1_5.md
│   └── ARQUITECTURA.md   # Este documento
├── logs/
│   └── app.log            # Log de actividad y errores (se genera solo)
├── tests/                 # Pruebas automatizadas (pytest)
├── src/
│   ├── main.py             # Punto de entrada: SOLO arma piezas y coordina
│   ├── market/              # Clientes de exchanges (hoy: Binance)
│   │   ├── base.py          # Interfaz ExchangeClient + ExchangeClientError
│   │   └── binance.py       # BinanceExchangeClient (implementa ExchangeClient)
│   ├── database/             # Repositorios de almacenamiento
│   │   ├── base.py            # Interfaz MarketDataRepository
│   │   ├── sqlite_repository.py    # Implementación real (SQLite, en uso)
│   │   └── postgres_repository.py  # Stub preparado para el futuro (NO implementado)
│   ├── services/              # Lógica de negocio
│   │   └── market_data_service.py  # Orquesta exchange + repositorio (el ciclo de consulta)
│   ├── models/                 # Modelos de datos (Pydantic)
│   │   └── market_data.py       # MarketTicker
│   ├── utils/                   # Utilidades transversales
│   │   ├── config.py              # Settings: lee config.yaml + .env
│   │   └── logger.py              # Configuración de logging
│   ├── ai/                        # Reservado para IA (Etapa futura). Vacío.
│   ├── dashboard/                 # Reservado para el dashboard (Etapa futura). Vacío.
│   ├── alerts/                    # Reservado para evaluación de alertas (Etapa futura). Vacío.
│   └── telegram/                  # Reservado para notificaciones Telegram (Etapa futura). Vacío.
```

## Flujo de una consulta (`python -m src.main`)

1. `main.py` llama a `load_settings()` (`src/utils/config.py`), que combina
   `config/config.yaml` (comportamiento) con `.env` (credenciales, si
   existe).
2. `main.py` configura logging (`src/utils/logger.py`).
3. `main.py` construye un `BinanceExchangeClient` y un
   `SQLiteMarketDataRepository`, y con ellos arma un `MarketDataService`
   (`src/services/market_data_service.py`). Esta construcción es el único
   lugar del proyecto que sabe que "hoy" el exchange es Binance y la base
   de datos es SQLite.
4. `main.py` llama a `service.run_cycle()` una vez, y luego programa que se
   repita cada `interval_minutes` usando la librería `schedule`.
5. `MarketDataService.run_cycle()` (la lógica de negocio): pide los
   tickers al `ExchangeClient`, los valida (ya vienen validados como
   objetos `MarketTicker` gracias a Pydantic), los guarda con el
   `MarketDataRepository`, y registra actividad en el log.

`main.py` no sabe cómo se consulta Binance, ni cómo se guarda en SQLite: solo
sabe que existen esas piezas y las conecta. Esa es la definición de
"coordinar" en este proyecto.

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

`src/database/postgres_repository.py` ya existe como estructura (todos sus
métodos lanzan `NotImplementedError` a propósito). Para activarlo en el
futuro:

1. Agregar un driver de PostgreSQL a `requirements.txt`.
2. Implementar `init()`, `save()` y `fetch_all()` usando ese driver y la
   variable de entorno `DATABASE_URL` (ya preparada en `.env.example` y en
   `Settings.database.postgres_url`).
3. Cambiar, en `src/main.py`, qué repositorio se instancia. Nada más en el
   proyecto necesita cambiar.

## Módulos reservados (todavía vacíos, a propósito)

`src/ai/`, `src/dashboard/`, `src/alerts/` y `src/telegram/` existen como
carpetas con un `__init__.py` que documenta su propósito futuro, pero sin
ningún código funcional. Se crearon ahora para que, cuando se autorice cada
etapa, el código nuevo tenga un lugar natural donde vivir, sin tener que
reorganizar el proyecto otra vez.

## Qué NO cambia para el usuario

El comando para ejecutar el bot sigue siendo el mismo:

```bash
python -m src.main
```

Y el comportamiento observable (qué monedas consulta, cada cuánto, qué
guarda, qué registra en logs) es exactamente el mismo que en la Etapa 1.
Lo que cambió es cómo está organizado el código por dentro, no lo que hace.
