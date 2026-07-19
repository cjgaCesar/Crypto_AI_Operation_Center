"""
Motor de señales (Etapa 3).

Transforma los indicadores técnicos ya calculados (Etapa 2, tabla
market_indicators) en señales estructuradas (tabla market_signals), sin usar
inteligencia artificial: solo reglas determinísticas y configurables
(src/signals/rules/) combinadas por un agregador (src/signals/aggregator.py).

Pensado para que la IA, el dashboard y el motor de trading de etapas
futuras consuman market_signals directamente.
"""
