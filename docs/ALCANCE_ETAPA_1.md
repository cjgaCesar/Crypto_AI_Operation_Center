# Alcance de la Etapa 1 — Bot de consulta de mercado (solo lectura)

## Objetivo

Construir un bot en Python que consulte datos públicos del mercado de
criptomonedas desde Binance, sin ejecutar operaciones ni utilizar dinero real,
y que guarde esos datos de forma ordenada para poder revisarlos más adelante.

## Incluido en esta etapa

1. **Consulta de datos públicos de Binance** para tres pares:
   - `BTCUSDT`
   - `ETHUSDT`
   - `SOLUSDT`

2. **Datos obtenidos por cada consulta:**
   - Precio actual (`lastPrice`)
   - Volumen de las últimas 24 horas (`volume`)
   - Variación porcentual de las últimas 24 horas (`priceChangePercent`)
   - Fecha y hora exacta de la consulta (generada por el propio bot, no por Binance)

3. **Ejecución automática cada 5 minutos**, con el intervalo definido en
   `config/config.yaml` (no está escrito directamente en el código).

4. **Almacenamiento en SQLite**, una base de datos local (un solo archivo,
   sin necesidad de instalar un servidor de base de datos aparte).

5. **Registro de logs**: toda la actividad normal (ej. "consulta exitosa") y
   los errores (ej. "no se pudo conectar a Binance") se guardan en
   `logs/app.log`, con fecha y hora.

6. **Configuración separada del código**, en `config/config.yaml`, para:
   - Lista de monedas a consultar
   - Intervalo de consulta (en minutos)
   - Límites de alerta (por ejemplo, variación porcentual mínima/máxima que
     en el futuro podría disparar una notificación — en esta etapa solo se
     define el valor, no se usa todavía)

## Explícitamente fuera de esta etapa

Estas restricciones son intencionales y no se deben implementar hasta que el
usuario lo indique explícitamente en una etapa futura:

- ❌ No se conectan claves privadas ni API keys de ninguna cuenta de Binance.
- ❌ No se realizan compras, ventas, ni ninguna operación de trading (real o de prueba).
- ❌ No se incluye inteligencia artificial, modelos de predicción, ni análisis técnico.
- ❌ No se construye ningún dashboard ni interfaz visual.
- ❌ No se integra con Telegram ni con ningún otro servicio de mensajería.
- ❌ No se usan APIs privadas ni endpoints que requieran autenticación.

## Criterio de validación de la Etapa 1

La Etapa 1 se considera terminada y validada cuando:

1. El bot se ejecuta sin errores y consulta correctamente los 3 pares definidos.
2. Los datos obtenidos son correctos y verificables contra Binance en el momento
   de la consulta.
3. Cada consulta queda guardada en `data/crypto_data.db` con su fecha/hora.
4. Los logs muestran claramente la actividad y cualquier error ocurrido.
5. El bot repite el ciclo automáticamente cada 5 minutos sin intervención manual.
6. Las pruebas automatizadas (`pytest`) pasan correctamente.
7. El usuario ha revisado y aprobado el funcionamiento antes de avanzar a
   cualquier etapa posterior (Telegram, IA, dashboard, trading).
