from ghostbrain.semantic.regions import region_color, region_label


def test_known_contexts_use_base_palette():
    assert region_color("poltergeist") == "#6EE7A8"
    assert region_color("sanlam") == "#38BDF8"
    assert region_color("personal") == "#A78BFA"


def test_unknown_context_is_deterministic_hex():
    a = region_color("reducedrecipes-clone")
    b = region_color("reducedrecipes-clone")
    assert a == b and a.startswith("#") and len(a) == 7


def test_label_falls_back_to_unfiled():
    assert region_label("") == "unfiled"
    assert region_label("sanlam") == "sanlam"
