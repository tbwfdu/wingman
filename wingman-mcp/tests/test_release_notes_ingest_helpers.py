"""Tests for the pure helpers in the new ingest_release_notes module."""
import pytest

from wingman_mcp.ingest.ingest_release_notes import (
    _bundle_matches,
    _extract_version,
    _migrate_hash_keys,
)
from wingman_mcp.ingest.products import PRODUCTS


def test_bundle_matches_prefix():
    rn = PRODUCTS["app_volumes"].release_notes
    assert _bundle_matches("AppVolumesReleaseNotesV2603", rn)
    assert _bundle_matches("AppVolumesReleaseNotesV2512", rn)
    assert not _bundle_matches("AppVolumesAdminGuideV2603", rn)


def test_bundle_matches_exact():
    rn = PRODUCTS["intelligence"].release_notes
    assert _bundle_matches("IntelligenceRN", rn)
    assert not _bundle_matches("Intelligence", rn)


def test_extract_version_yymm():
    rn = PRODUCTS["horizon"].release_notes
    assert _extract_version("Horizon-Release-Notes-V2603", rn) == "2603"


def test_extract_version_dem_strips_underscores():
    rn = PRODUCTS["dem"].release_notes
    assert (
        _extract_version("Dynamic-Environment-Manager_2111.1_AdminGuide", rn)
        == "2111.1"
    )


def test_extract_version_access_dotted():
    rn = PRODUCTS["access"].release_notes
    assert _extract_version("workspace-one-access-release-notesV24.12", rn) == "24.12"


def test_extract_version_rolling_when_no_match():
    rn = PRODUCTS["intelligence"].release_notes
    assert _extract_version("IntelligenceRN", rn) == "rolling"


def test_migrate_hash_keys_legacy_uem():
    """Legacy hash entries with bare version keys get prefixed with uem:."""
    legacy = {"2506": "abc", "2509": "def", "uem:2602": "ghi"}
    migrated = _migrate_hash_keys(legacy)
    assert migrated == {
        "uem:2506": "abc",
        "uem:2509": "def",
        "uem:2602": "ghi",
    }
