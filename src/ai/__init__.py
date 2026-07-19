"""
Motor de decisión de IA (Etapa 4).

Interpreta, explica y prioriza los SignalSnapshot ya generados por el motor
de señales determinístico de la Etapa 3 (src/signals/). La IA NO reemplaza
ese motor: el motor de reglas sigue siendo la única fuente oficial de las
señales; este módulo solo consume su salida.

Flujo: MarketContext -> PromptBuilder -> AIProvider -> AIRecommendation.

Hoy el único AIProvider realmente conectado es DummyProvider (respuestas
simuladas, deterministas, sin llamadas de red). OpenAIProvider y
ClaudeProvider existen como estructura preparada (src/ai/providers/), sin
conectar ninguna API real todavía: las credenciales ya están preparadas en
Settings.ai (src/utils/config.py) y en .env.example.
"""
