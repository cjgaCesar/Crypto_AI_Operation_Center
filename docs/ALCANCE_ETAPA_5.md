# Alcance de la Etapa 5 — Dashboard (solo lectura)

> **Estado: ITERACIÓN 5.1 — SOLO ANÁLISIS Y DISEÑO.** Este documento define
> el alcance y la arquitectura del Dashboard antes de escribir ningún
> código. No se ha implementado nada todavía. Queda pendiente tu
> aprobación de este diseño antes de comenzar la Iteración 5.2
> (implementación).

## Objetivo

Construir un Dashboard de **solo lectura** que visualice, para cada
símbolo configurado, el estado más reciente y el historial de las 4
tablas ya generadas por las Etapas 1 a 4 (`market_data`,
`market_indicators`, `market_signals`, `ai_recommendations`), sin agregar
ninguna lógica de negocio nueva ni modificar ningún dato.

**El Dashboard no calcula nada.** No recalcula indicadores, no recalcula
señales, no genera recomendaciones de IA: solo lee y presenta lo que los
motores de las Etapas 2, 3 y 4 ya guardaron.

## Restricciones explícitas de esta etapa (dadas por el usuario)

- Uso personal/local durante las Etapas 5 y 6 (no multiusuario, no
  desplegado remotamente todavía).
- Desarrollado completamente en Python.
- Lee directamente de SQLite, **en modo solo lectura** (nunca llama a
  `save()` de ningún repositorio).
- No requiere un backend adicional (un solo proceso).
- Modular: la lógica de consulta debe poder reutilizarse detrás de una
  futura API (FastAPI) sin reescribirla.
- Prioriza simplicidad y mantenibilidad sobre una arquitectura
  distribuida.

## Alcance de la Iteración 5.1 (esta iteración)

Únicamente:
1. Auditoría de la arquitectura existente (ver `docs/ARQUITECTURA.md`).
2. Revisión del esquema de las 4 tablas SQLite disponibles.
3. Definición del alcance del Dashboard (este documento).
4. Selección y justificación de la tecnología (`Streamlit`, ver
   `docs/ARQUITECTURA_DASHBOARD.md`).
5. Diseño de páginas, componentes, filtros globales y arquitectura de
   módulos (ver `docs/ARQUITECTURA_DASHBOARD.md`).
6. Documentación.

**Explícitamente fuera de la Iteración 5.1**: escribir código del
Dashboard, crear carpetas nuevas, instalar dependencias nuevas
(`streamlit` todavía no se agrega a `requirements.txt`).

## Explícitamente fuera de toda la Etapa 5

- ❌ Cualquier operación de escritura sobre `market_data`,
  `market_indicators`, `market_signals` o `ai_recommendations`.
- ❌ Autenticación, multiusuario, despliegue remoto (quedan para una
  etapa futura si se decide desplegar el Dashboard).
- ❌ Telegram, Paper Trading, Trading Automático.
- ❌ Conexión a proveedores de IA reales (sigue usando lo que ya haya
  generado `DummyProvider` en `ai_recommendations`).
- ❌ Modificar `src/market/`, `src/database/`, `src/services/`,
  `src/signals/`, `src/ai/` o `src/utils/`.

## Criterio de validación de la Iteración 5.1

1. `docs/ALCANCE_ETAPA_5.md` y `docs/ARQUITECTURA_DASHBOARD.md` existen y
   documentan el diseño completo.
2. `README.md` y `docs/ARQUITECTURA.md` reflejan que la Etapa 5 está en
   diseño.
3. `pytest` sigue en verde (esta iteración no toca código, por lo que no
   debe haber ningún cambio de comportamiento).
4. El usuario aprueba el diseño antes de que comience la Iteración 5.2.
