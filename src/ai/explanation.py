"""
Explicación legible de una AIRecommendation (Etapa 4).

AIExplanation NO es lo que se persiste en 'ai_recommendations' (esa tabla
guarda los campos de AIRecommendation, ver src/ai/repository.py y
src/ai/sqlite_repository.py): es una vista derivada, pensada para un futuro
Dashboard, que reformatea una AIRecommendation ya generada en una
explicación de lectura más humana, sin recalcular nada ni volver a llamar
al proveedor de IA.
"""

from pydantic import BaseModel, Field

from src.ai.recommendation import AIRecommendation


class AIExplanation(BaseModel):
    """Desglose legible de una AIRecommendation: resumen, razón principal,
    factores (positivos y negativos como bullets) y conclusión."""

    full_explanation: str = Field(min_length=1)
    short_explanation: str = Field(min_length=1)
    bullet_points: list[str]
    conclusion: str = Field(min_length=1)


def build_explanation(recommendation: AIRecommendation) -> AIExplanation:
    """Deriva una AIExplanation a partir de una AIRecommendation ya
    generada. Puro formateo/texto: no agrega ni descarta información, y no
    contiene ninguna lógica de negocio (esa vive en DecisionEngine/reglas)."""
    bullet_points = (
        [f"+ {advantage}" for advantage in recommendation.advantages]
        + [f"- {risk}" for risk in recommendation.risks]
    )

    positives = "\n".join(f"- {a}" for a in recommendation.advantages) or "- (ninguno reportado)"
    negatives = "\n".join(f"- {r}" for r in recommendation.risks) or "- (ninguno reportado)"
    full_explanation = (
        f"{recommendation.reasoning}\n\n"
        f"Factores positivos:\n{positives}\n\n"
        f"Factores de riesgo:\n{negatives}"
    )

    conclusion = (
        f"Recomendación: {recommendation.recommendation.value} "
        f"(riesgo {recommendation.risk_level.value}, "
        f"confianza {recommendation.confidence:.0f}%)."
    )

    return AIExplanation(
        full_explanation=full_explanation,
        short_explanation=recommendation.summary,
        bullet_points=bullet_points,
        conclusion=conclusion,
    )
