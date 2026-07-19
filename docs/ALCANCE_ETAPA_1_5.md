# Alcance de la Etapa 1.5 — Refactorización y preparación de arquitectura

## Objetivo

Reorganizar el código de la Etapa 1 (ya aprobada) en una arquitectura
modular, para que las etapas futuras (Inteligencia Artificial, múltiples
exchanges, dashboard, Telegram, paper trading, trading automatizado) se
puedan construir agregando módulos nuevos, sin reescribir los existentes.

Esta etapa es puramente estructural: **el comportamiento observable del bot
no cambia**. Sigue consultando los mismos 3 pares, con el mismo intervalo,
guardando en la misma base de datos y registrando los mismos logs.

## Incluido en esta etapa

1. **Arquitectura modular** dentro de `src/`: `market/`, `database/`,
   `services/`, `models/`, `utils/`, `ai/`, `dashboard/`, `alerts/`,
   `telegram/`, y `main.py` como coordinador. Ver detalle en
   [ARQUITECTURA.md](ARQUITECTURA.md).

2. **`.env.example`**, con espacios reservados para: Binance, OpenAI,
   Anthropic (Claude), Telegram, CoinGecko y NewsAPI. Ninguna de estas
   credenciales se usa todavía en el proyecto.

3. **Sistema de configuración combinado**: `src/utils/config.py` lee
   `config/config.yaml` (comportamiento) y `.env` (credenciales), y entrega
   un único objeto `Settings`.

4. **Modelos de datos con Pydantic**: `MarketTicker`
   (`src/models/market_data.py`) reemplaza los diccionarios sueltos que se
   usaban en la Etapa 1, con validación automática de tipos.

5. **Lógica de negocio separada en servicios**: `MarketDataService`
   (`src/services/market_data_service.py`) contiene todo lo que antes
   estaba directamente en `main.py`. `main.py` ahora solo arma las piezas
   (configuración, cliente de exchange, repositorio, servicio) y coordina
   la ejecución.

6. **Interfaz común para exchanges**: `ExchangeClient`
   (`src/market/base.py`), implementada hoy solo por
   `BinanceExchangeClient` (`src/market/binance.py`). Deja la puerta
   abierta a Bybit, Coinbase, Kraken, etc. sin cambiar el resto del
   proyecto.

7. **Interfaz común para almacenamiento**: `MarketDataRepository`
   (`src/database/base.py`), implementada hoy por
   `SQLiteMarketDataRepository` (en uso) y con un stub preparado
   `PostgresMarketDataRepository` (`src/database/postgres_repository.py`,
   sin implementar todavía) para una futura migración.

## Explícitamente fuera de esta etapa

- ❌ No se agregó inteligencia artificial (más allá de las carpetas y
  campos de configuración reservados).
- ❌ No se construyó el dashboard.
- ❌ No se integró Telegram.
- ❌ No se implementó paper trading ni trading automatizado.
- ❌ No se conectó ninguna clave privada real, ni de Binance ni de ningún
  otro servicio.
- ❌ No se implementó PostgreSQL de verdad: solo la estructura (interfaz +
  stub) para que sea sencillo agregarlo después.

## Criterio de validación de la Etapa 1.5

1. Toda la funcionalidad de la Etapa 1 sigue funcionando exactamente
   igual (mismas monedas, mismo intervalo, mismos datos, mismos logs).
2. El código está organizado en los módulos descritos en
   [ARQUITECTURA.md](ARQUITECTURA.md).
3. `main.py` no contiene lógica de negocio, solo coordinación.
4. Binance está implementado detrás de una interfaz común de exchanges.
5. SQLite está implementado detrás de una interfaz común de repositorios,
   con un stub preparado para PostgreSQL.
6. Los datos de mercado se representan con un modelo Pydantic
   (`MarketTicker`), no con diccionarios sueltos.
7. Existe `.env.example` con los campos de credenciales futuras, sin usar
   ninguno todavía.
8. Todas las pruebas automatizadas (`pytest`) pasan.
9. El usuario ha revisado y aprobado esta etapa antes de avanzar a
   cualquier etapa posterior (IA, dashboard, Telegram, trading).
