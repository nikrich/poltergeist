from ghostbrain.semantic.regions import _RAMP, region_color, region_label


def test_known_contexts_use_base_palette():
    # "poltergeist" is the only entry in _BASE — a product accent, not a
    # context. Every actual context (legacy or configured) flows through
    # the hash->ramp path below.
    assert region_color("poltergeist") == "#6EE7A8"


def test_configured_context_hashes_into_ramp():
    a = region_color("sanlam")
    b = region_color("sanlam")
    assert a == b and a in _RAMP


def test_unknown_context_is_deterministic_hex():
    a = region_color("reducedrecipes-clone")
    b = region_color("reducedrecipes-clone")
    assert a == b and a.startswith("#") and len(a) == 7


def test_label_falls_back_to_unfiled():
    assert region_label("") == "unfiled"
    assert region_label("sanlam") == "sanlam"
