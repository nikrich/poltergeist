from ghostbrain.ontology.sanitize import neutralise, one_line


def test_neutralise_breaks_closing_delimiter_runs_of_any_length():
    for run in (">>>", ">>>>>", ">>>>>>"):
        out = neutralise(f"a{run}b")
        assert ">>>" not in out and "a" in out and "b" in out


def test_neutralise_breaks_opening_delimiter_runs():
    assert "<<<" not in neutralise("<<<<<")
    assert "<<<" not in neutralise("x <<< y")


def test_neutralise_defuses_line_leading_headers_but_keeps_line_breaks():
    out = neutralise("intro\n### NOTE 7\nbody")
    assert "\n### NOTE 7" not in out
    assert out.splitlines() == ["intro", "# # # NOTE 7", "body"]


def test_one_line_flattens_newlines_and_neutralises():
    out = one_line("x\n### NOTE 9\n>>>")
    assert "\n" not in out and ">>>" not in out and "### NOTE" not in out


def test_one_line_collapses_whitespace_and_caps_length():
    assert one_line("  a \r\n\n b\tc  ") == "a b c"
    assert one_line("abcdef", 3) == "abc"
