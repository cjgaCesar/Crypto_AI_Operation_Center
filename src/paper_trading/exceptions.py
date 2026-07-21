"""
Excepciones del dominio de Paper Trading (Etapa 6.1, ampliado en 6.7).

Se declaran ahora, aunque ningún motor de esta iteración las lance
todavía (esta etapa no incluye ningún Engine, ver src/paper_trading/
__init__.py), para que la Etapa 6.2 (motores puros, ver
docs/ARQUITECTURA_PAPER_TRADING.md §19) no tenga que diseñar la
jerarquía de errores desde cero: son invariantes que la arquitectura ya
identificó como responsabilidad del futuro motor, no de un modelo
individual (ej. un over-fill cruza Order + Execution, ver §4 "casos
especiales" -- ningún modelo por sí solo puede validarlo).

Las 5 excepciones agregadas en la Etapa 6.7 (ver §21.9) representan
estados imposibles del ciclo de vida de reservas (aceptar/llenar/
cancelar) -- nunca un rechazo de riesgo normal, que sigue
representándose como `RiskValidationResult(approved=False)`.

Las 4 excepciones agregadas en la Etapa 6.8 (ver
docs/ARQUITECTURA_PAPER_TRADING.md §22.12) pertenecen al subsistema de
reconciliación, no al dominio de trading: deliberadamente NO heredan de
`PaperTradingDomainError` (no son un rechazo de riesgo ni un estado
imposible del ciclo de una Order) y no se mezclan con las excepciones
de arriba.
"""


class PaperTradingDomainError(Exception):
    """Error base de todo el dominio de Paper Trading."""


class InvalidOrderTransitionError(PaperTradingDomainError):
    """Se intentó una transición de estado de Order no permitida.

    Ver ARQUITECTURA_PAPER_TRADING.md §4 (matriz de transiciones válidas
    y transiciones inválidas).
    """


class OverFillError(PaperTradingDomainError):
    """Una Execution superaría la cantidad restante de la Order que llena.

    Invariante dura (ver ARQUITECTURA_PAPER_TRADING.md §4, caso especial
    "over-fill"): debe rechazarse ruidosamente, nunca recortarse en
    silencio.
    """


class InvalidOrderStateError(PaperTradingDomainError):
    """Se intentó aceptar/llenar/cancelar una Order que no está en el
    estado requerido para esa operación (ver ARQUITECTURA_PAPER_TRADING.md
    §21.1/§21.6): aceptar algo que no es NEW, llenar o cancelar algo que
    no es PENDING, o aceptar dos veces el mismo id de orden.
    """


class ReservationNotFoundError(PaperTradingDomainError):
    """Se intentó liberar la reserva de una Order que no tiene datos de
    reserva registrados (ver §21.2: reserved_price/reserved_notional/
    reserved_fee/reserved_quantity en None pese a exigirse poblados).
    """


class InsufficientReservedCashError(PaperTradingDomainError):
    """No hay suficiente CashBalance.available_balance para reservar el
    monto requerido por una orden BUY (ver §21.4). Como RiskEngine ya
    aprobó la orden antes de intentar reservar, este error representa un
    estado imposible/carrera, no un rechazo de riesgo normal.
    """


class InsufficientReservedQuantityError(PaperTradingDomainError):
    """No hay suficiente Position.available_quantity para reservar la
    cantidad requerida por una orden SELL (ver §21.4). Mismo criterio que
    InsufficientReservedCashError: RiskEngine ya aprobó la orden antes.
    """


class ReservationAlreadyReleasedError(PaperTradingDomainError):
    """Se intentó liberar una reserva que dejaría `reserved_balance`/
    `reserved_quantity` en un valor negativo -- señal de que ya se liberó
    antes, o de una inconsistencia de datos (ver §21.4/§21.6).
    """


class ReconciliationError(Exception):
    """Error base del subsistema de reconciliación (Etapa 6.8, ver §22.12).

    No hereda de `PaperTradingDomainError`: no representa un estado
    imposible del ciclo de vida de una Order, sino una falla del propio
    subsistema de diagnóstico/reparación.
    """


class ReconciliationConflictError(ReconciliationError):
    """El estado de `CashBalance`/`Position` cambió entre el análisis y el
    intento de reparación (control optimista de concurrencia, §22.6/§22.8
    Paso 28). La reparación se aborta sin escribir nada; se debe volver a
    inspeccionar antes de reintentar.
    """


class UnsupportedRepairError(ReconciliationError):
    """Se pidió reparar un `issue_code` que no está en la lista cerrada de
    reparaciones automáticas permitidas (§22.7) -- ej. intentar reparar
    `FILLED_ORDER_WITHOUT_EXECUTION`, que exigiría crear una Execution.
    """


class ReconciliationAuditError(ReconciliationError):
    """Falló la escritura de la fila de auditoría
    (`paper_trading_reconciliation_audit`, §22.9). Se distingue de un
    fallo de la transacción de reparación en sí para que quien llame
    pueda diferenciar "no se reparó nada" de "se reparó pero no quedó
    auditado".
    """
