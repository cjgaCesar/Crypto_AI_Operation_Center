"""
Dominio de Paper Trading (Etapa 6.1).

Capa de dominio pura: modelos Pydantic + enums + invariantes, sin
SQLite, sin Streamlit, sin conexión a ningún exchange y sin ningún
motor de negocio todavía (ver docs/ARQUITECTURA_PAPER_TRADING.md).

Alcance de esta iteración: solo MARKET, solo LONG, una sola cuenta, un
solo exchange. El motor de llenado, RiskEngine, el repositorio y el
servicio se agregan en iteraciones posteriores (6.2 en adelante), cada
una construida sobre este dominio sin modificarlo salvo error crítico.
"""
