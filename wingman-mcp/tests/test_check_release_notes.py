"""Tests for the per-product slicing in check_release_notes."""
from wingman_mcp.ingest.check import _split_rn_targets


def test_split_rn_targets_handles_combined_alias():
    products, combined = _split_rn_targets(["release_notes"])
    assert combined is True
    # When the combined target is present, products list is irrelevant
    # — check_release_notes will iterate everything.


def test_split_rn_targets_extracts_per_product_axes():
    products, combined = _split_rn_targets(["horizon_rn", "uag_rn"])
    assert combined is False
    assert products == ["horizon", "uag"]


def test_split_rn_targets_passes_through_unrelated():
    products, combined = _split_rn_targets(["uem", "api"])
    assert combined is False
    assert products == []
