"""
Reglas de señales: componentes independientes, cada uno con una única
responsabilidad (Single Responsibility Principle). Cada regla recibe
únicamente los indicadores que necesita y devuelve un resultado propio
(un Enum), sin conocer las demás reglas ni el agregador.

Agregar una regla nueva no requiere modificar las existentes (Open/Closed):
solo se crea un archivo nuevo aquí y se conecta en SignalEngine y en el
agregador.
"""
