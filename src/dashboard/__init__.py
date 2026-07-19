"""
Dashboard de solo lectura (Etapa 5, Iteración 5.2 — estructura base).

Visualiza, para cada símbolo configurado, el estado más reciente y el
historial de las 4 tablas ya generadas por las Etapas 1 a 4 (market_data,
market_indicators, market_signals, ai_recommendations). No escribe en
ninguna tabla, no recalcula indicadores, no genera señales ni
recomendaciones: solo lee lo que los motores existentes ya guardaron.

Ver docs/ALCANCE_ETAPA_5.md y docs/ARQUITECTURA_DASHBOARD.md.

Ejecutar con: streamlit run src/dashboard/app.py
"""
