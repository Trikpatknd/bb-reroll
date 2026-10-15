"""Trait tooltip lines -> good / bad effects (bbseed/traits.py). Lines as the game gives them."""
from bbseed.traits import effect, plain


def test_green_values_are_good_red_ones_bad():
    assert effect("[color=#135213]+15%[/color] chance to hit when wielding a two-handed weapon") == {
        "sign": "+", "text": "+15% chance to hit when wielding a two-handed weapon"}
    assert effect("[color=#8f1e1e]-5[/color] Melee Defense") == {"sign": "-", "text": "-5 Melee Defense"}


def test_legends_placeholder_colours():
    assert effect("[color=%positive%]+7[/color] Resolve")["sign"] == "+"
    assert effect("[color=%negative%]-50%[/color] Ranged Skill") == {"sign": "-", "text": "-50% Ranged Skill"}


def test_a_line_without_colours_is_neither():
    assert effect("Gets more irritated while reading") == {"sign": "", "text": "Gets more irritated while reading"}


def test_the_first_coloured_value_decides():
    line = "[color=%positive%]+5[/color] Resolve, [color=%negative%]-5[/color] Initiative"
    assert effect(line)["sign"] == "+"


def test_plain_strips_markup_and_spaces():
    assert plain("Umm, what?  [b]This[/b] character\n isn't bright.") == "Umm, what? This character isn't bright."
