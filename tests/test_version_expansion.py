"""Table-driven tests for version normalization."""
import pytest

from wingman_mcp.search import _expand_version


@pytest.mark.parametrize("user_input,expected_subset", [
    # 4-digit yymm → adds dotted yy.mm form
    ("2412", {"2412", "24.12"}),
    ("24.12", {"2412", "24.12"}),
    ("2603", {"2603", "26.03"}),
    # Patch suffix
    ("2506.1", {"2506.1", "25061"}),
    # Leading 'v' is stripped
    ("v2602", {"2602", "26.02"}),
    ("V24.12", {"2412", "24.12"}),
    # Whitespace tolerated
    ("  2412  ", {"2412", "24.12"}),
])
def test_expand_version_table(user_input, expected_subset):
    result = set(_expand_version(user_input))
    assert expected_subset.issubset(result), (
        f"For input {user_input!r}, expected {expected_subset} ⊆ result, got {result}"
    )


def test_expand_version_returns_sorted_list():
    result = _expand_version("2412")
    assert isinstance(result, list)
    assert result == sorted(result)
