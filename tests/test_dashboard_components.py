"""
Pruebas para src/dashboard/components.py: enfocadas en el fallback seguro
de render_status_badge() (Bloque C, Iteración 5.3), que reemplazó el
`<span>` con `unsafe_allow_html=True` por la sintaxis nativa de markdown
de Streamlit (":color-background[texto]").
"""

from streamlit.testing.v1 import AppTest


def _render_badge(label, color):
    from src.dashboard.components import render_status_badge
    render_status_badge(label, color)


def _run(label, color):
    at = AppTest.from_function(_render_badge, args=(label, color))
    at.run(timeout=10)
    return at


def test_valid_label_and_color_render_expected_markdown():
    at = _run("Bullish", "#22C55E")
    assert not at.exception
    assert at.markdown[0].value == ":green-background[Bullish]"


def test_none_label_falls_back_to_not_available():
    at = _run(None, "#22C55E")
    assert not at.exception
    assert at.markdown[0].value == ":green-background[N/D]"


def test_empty_label_falls_back_to_not_available():
    at = _run("", "#22C55E")
    assert not at.exception
    assert at.markdown[0].value == ":green-background[N/D]"


def test_none_color_falls_back_to_gray():
    at = _run("Bullish", None)
    assert not at.exception
    assert at.markdown[0].value == ":gray-background[Bullish]"


def test_unknown_color_falls_back_to_gray():
    at = _run("Bullish", "#000000")
    assert not at.exception
    assert at.markdown[0].value == ":gray-background[Bullish]"


def test_label_with_brackets_is_escaped_instead_of_breaking_markdown():
    at = _run("Weird[Label]", "#22C55E")
    assert not at.exception
    assert at.markdown[0].value == ":green-background[Weird(Label)]"


def test_no_html_is_ever_produced():
    at = _run("Bullish", "#22C55E")
    assert "<span" not in at.markdown[0].value
    assert "unsafe" not in at.markdown[0].value.lower()
