"""
Punto único de importación para los modelos Pydantic de la Etapa 4.

Cada modelo vive en su propio archivo (context.py, recommendation.py,
explanation.py), igual que src/models/ separa MarketTicker, IndicatorSnapshot
y SignalSnapshot en archivos distintos. Este módulo solo reexporta, para que
el resto del código (y las pruebas) pueda importar todo desde un solo
lugar: 'from src.ai.models import MarketContext, AIRecommendation, ...'.
"""

from src.ai.context import MarketContext, build_market_context
from src.ai.explanation import AIExplanation, build_explanation
from src.ai.prompt_builder import PromptVersion
from src.ai.recommendation import AIRecommendation, RecommendationAction, RiskLevel

__all__ = [
    "MarketContext",
    "build_market_context",
    "AIRecommendation",
    "RecommendationAction",
    "RiskLevel",
    "PromptVersion",
    "AIExplanation",
    "build_explanation",
]
