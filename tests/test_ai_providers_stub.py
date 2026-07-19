"""
Pruebas para src/ai/base.py (interfaz AIProvider) y los stubs
src/ai/providers/openai_provider.py y claude_provider.py.

Ninguno de los dos proveedores reales está implementado a propósito (ver
docstring de cada archivo): estas pruebas confirman que cumplen la interfaz
AIProvider y que, si se usan antes de tiempo, fallan de forma clara
(NotImplementedError) en vez de silenciosa o con una llamada de red real.
"""

import pytest

from src.ai.base import AIProvider
from src.ai.providers.claude_provider import ClaudeProvider
from src.ai.providers.dummy_provider import DummyProvider
from src.ai.providers.openai_provider import OpenAIProvider


def test_dummy_provider_implements_interface():
    assert isinstance(DummyProvider(), AIProvider)


def test_openai_provider_implements_interface():
    provider = OpenAIProvider(api_key="sk-test", model="gpt-4", temperature=0.2, max_tokens=500)
    assert isinstance(provider, AIProvider)


def test_openai_provider_generate_raises_not_implemented():
    provider = OpenAIProvider(api_key="sk-test", model="gpt-4", temperature=0.2, max_tokens=500)

    with pytest.raises(NotImplementedError):
        provider.generate("cualquier prompt")


def test_claude_provider_implements_interface():
    provider = ClaudeProvider(api_key="sk-ant-test", model="claude-3", temperature=0.2, max_tokens=500)
    assert isinstance(provider, AIProvider)


def test_claude_provider_generate_raises_not_implemented():
    provider = ClaudeProvider(api_key="sk-ant-test", model="claude-3", temperature=0.2, max_tokens=500)

    with pytest.raises(NotImplementedError):
        provider.generate("cualquier prompt")
