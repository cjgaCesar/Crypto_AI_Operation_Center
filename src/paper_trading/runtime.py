"""
Clock e IdGenerator -- primitivas no deterministas aisladas (Etapa 6.5).

`PaperTradingApplication` y la Composition Root nunca deben llamar
`datetime.now()` ni `uuid.uuid4()` directamente (harían que el mismo
caso de uso produjera resultados distintos en cada corrida, imposibles
de reproducir en una prueba). En su lugar, reciben estas dos
dependencias inyectadas como protocolos:

- `Clock.now()` reemplaza `datetime.now(timezone.utc)`.
- `IdGenerator.new_order_id()/new_execution_id()/new_trade_id()/
  new_reconciliation_audit_id()` (el último agregado en la Etapa 6.8)
  reemplazan `uuid.uuid4()`.

`SystemClock`/`UUIDIdGenerator` son las únicas implementaciones de este
módulo que sí usan `datetime.now()`/`uuid.uuid4()` -- deliberadamente
aisladas aquí, para que las pruebas puedan inyectar dobles
(`FixedClock`/`DeterministicIdGenerator`, definidos en los propios
archivos de prueba) sin tocar ninguna lógica de aplicación.

Archivo separado de `application.py`/`composition.py` (en vez de vivir
en cualquiera de los dos) para evitar un import circular:
`composition.py` construye `PaperTradingApplication` (de
`application.py`), y `application.py` tipa su constructor con
`Clock`/`IdGenerator` -- si estos vivieran en cualquiera de esos dos
archivos, el otro tendría que importarlo de vuelta.
"""

import uuid
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Devuelve el instante actual (con zona horaria)."""
        ...


class IdGenerator(Protocol):
    def new_order_id(self) -> str: ...

    def new_execution_id(self) -> str: ...

    def new_trade_id(self) -> str: ...

    def new_reconciliation_audit_id(self) -> str: ...


class SystemClock:
    """Implementación real de Clock: usa datetime.now(timezone.utc)."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class UUIDIdGenerator:
    """Implementación real de IdGenerator: usa uuid.uuid4()."""

    def new_order_id(self) -> str:
        return str(uuid.uuid4())

    def new_execution_id(self) -> str:
        return str(uuid.uuid4())

    def new_trade_id(self) -> str:
        return str(uuid.uuid4())

    def new_reconciliation_audit_id(self) -> str:
        return str(uuid.uuid4())
