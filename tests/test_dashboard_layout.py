"""Pruebas para src/dashboard/layout.py (helpers de layout responsive, funciones puras salvo render_*)."""

from src.dashboard.layout import (
    VIEW_MODE_AUTO,
    VIEW_MODE_COMPACT,
    VIEW_MODE_WIDE,
    get_cards_per_row,
    is_compact,
)


class TestGetCardsPerRow:
    def test_wide_mode_returns_three(self):
        assert get_cards_per_row(VIEW_MODE_WIDE) == 3

    def test_compact_mode_returns_one(self):
        assert get_cards_per_row(VIEW_MODE_COMPACT) == 1

    def test_auto_mode_returns_a_conservative_value(self):
        value = get_cards_per_row(VIEW_MODE_AUTO)
        assert value == 2

    def test_unknown_mode_falls_back_to_auto(self):
        assert get_cards_per_row("no-existe") == get_cards_per_row(VIEW_MODE_AUTO)

    def test_none_falls_back_to_auto(self):
        assert get_cards_per_row(None) == get_cards_per_row(VIEW_MODE_AUTO)

    def test_empty_string_falls_back_to_auto(self):
        assert get_cards_per_row("") == get_cards_per_row(VIEW_MODE_AUTO)

    def test_no_mode_ever_returns_zero(self):
        for mode in [VIEW_MODE_WIDE, VIEW_MODE_COMPACT, VIEW_MODE_AUTO, "desconocido", None, ""]:
            assert get_cards_per_row(mode) > 0

    def test_no_mode_ever_returns_more_than_three(self):
        for mode in [VIEW_MODE_WIDE, VIEW_MODE_COMPACT, VIEW_MODE_AUTO, "desconocido", None, ""]:
            assert get_cards_per_row(mode) <= 3


class TestIsCompact:
    def test_compact_mode_is_compact(self):
        assert is_compact(VIEW_MODE_COMPACT) is True

    def test_wide_mode_is_not_compact(self):
        assert is_compact(VIEW_MODE_WIDE) is False

    def test_auto_mode_is_not_compact(self):
        assert is_compact(VIEW_MODE_AUTO) is False

    def test_unknown_mode_is_not_compact(self):
        assert is_compact("no-existe") is False

    def test_none_is_not_compact(self):
        assert is_compact(None) is False


class TestRenderResponsiveGrid:
    def test_compact_grid_renders_every_item_without_columns(self):
        from src.dashboard.layout import render_responsive_grid

        rendered = []
        render_responsive_grid([1, 2, 3], rendered.append, cards_per_row=1)

        assert rendered == [1, 2, 3]

    def test_wide_grid_renders_every_item_exactly_once(self):
        from src.dashboard.layout import render_responsive_grid

        rendered = []
        render_responsive_grid([1, 2, 3, 4, 5], rendered.append, cards_per_row=3)

        assert rendered == [1, 2, 3, 4, 5]

    def test_empty_items_renders_nothing(self):
        from src.dashboard.layout import render_responsive_grid

        rendered = []
        render_responsive_grid([], rendered.append, cards_per_row=1)
        assert rendered == []

        render_responsive_grid([], rendered.append, cards_per_row=3)
        assert rendered == []
