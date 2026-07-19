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

## Qué hace el bot hoy

- Consulta precios públicos de Binance para `BTCUSDT`, `ETHUSDT` y `SOLUSDT`.
- Obtiene precio actual, volumen 24h, variación % 24h y la fecha/hora de la consulta.
- Repite la consulta automáticamente cada 5 minutos (configurable).
- Guarda cada resultado en una base de datos SQLite local.
- Registra toda la actividad y los errores en archivos de log.

**Todavía NO hace lo siguiente (a propósito, queda preparado para etapas futuras):**

- No usa ninguna clave privada real (de Binance, OpenAI, Anthropic, Telegram, etc.).
- No compra ni vende nada. No mueve dinero real ni de prueba.
- No incluye inteligencia artificial ni modelos predictivos todavía.
- No incluye dashboard ni interfaz visual todavía.
- No envía mensajes a Telegram ni a ningún otro servicio externo todavía.

## Estructura del proyecto (desde la Etapa 1.5)

```
Crypto_AI_Operation_Center/
├── README.md
├── requirements.txt
├── .env.example              # Plantilla de credenciales futuras (no se usan todavía)
├── config/
│   └── config.yaml            # Monedas, intervalo, límites de alerta, rutas
├── src/
│   ├── main.py                 # Punto de entrada: SOLO arma piezas y coordina
│   ├── market/                  # Clientes de exchanges (hoy: Binance)
│   │   ├── base.py                # Interfaz común ExchangeClient
│   │   └── binance.py             # Implementación de Binance
│   ├── database/                  # Repositorios de almacenamiento
│   │   ├── base.py                  # Interfaz común MarketDataRepository
│   │   ├── sqlite_repository.py      # Implementación SQLite (en uso)
│   │   └── postgres_repository.py    # Preparado para el futuro (no implementado)
│   ├── services/                    # Lógica de negocio
│   │   └── market_data_service.py     # Orquesta exchange + repositorio
│   ├── models/                        # Modelos de datos (Pydantic)
│   │   └── market_data.py               # MarketTicker
│   ├── utils/                           # Configuración y logging
│   │   ├── config.py                      # Lee config.yaml + .env
│   │   └── logger.py                      # Configuración de logs
│   ├── ai/                                # Reservado para IA (etapa futura)
│   ├── dashboard/                         # Reservado para el dashboard (etapa futura)
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
    └── ARQUITECTURA.md
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

Esto va a:

1. Leer la configuración desde `config/config.yaml` (y `.env` si existe).
2. Consultar Binance para las monedas configuradas.
3. Guardar los resultados en `data/crypto_data.db`.
4. Escribir actividad y errores en `logs/app.log`.
5. Repetir automáticamente cada 5 minutos (o el intervalo que definas).

Para detenerlo, presiona `Ctrl + C` en la terminal.

## Cómo ejecutar las pruebas

```bash
pytest
```

Esto valida que la conexión a Binance, el guardado en la base de datos, el
modelo de datos, el servicio y la configuración funcionen correctamente
antes de continuar con más funcionalidades.

Las pruebas que dependen de Binance usan datos simulados (no llaman a
internet), así que son rápidas y siempre dan el mismo resultado. La
conexión real se verifica manualmente ejecutando el bot (paso anterior).

## Cómo revisar los datos guardados manualmente

```bash
python -c "from src.database.sqlite_repository import SQLiteMarketDataRepository; [print(t) for t in SQLiteMarketDataRepository('data/crypto_data.db').fetch_all()]"
```

Esto imprime cada registro guardado como un objeto `MarketTicker` (symbol,
price, volume_24h, price_change_percent_24h, queried_at).

## Estado del proyecto

✅ Etapa 1 aprobada: bot funcional de consulta de mercado.
✅ Etapa 1.5 completada: arquitectura modular, interfaces para exchanges y
bases de datos, modelos de datos con Pydantic, configuración combinada
`.env` + `config.yaml`, lógica de negocio separada en servicios.

Pendiente: aprobación formal de la Etapa 1.5 antes de avanzar a cualquier
etapa futura (Telegram, inteligencia artificial, dashboard, paper trading
o trading).
