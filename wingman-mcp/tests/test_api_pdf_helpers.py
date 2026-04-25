"""Tests for the PDF section splitter used by Intelligence API ingest."""
from wingman_mcp.ingest.ingest_api_pdf import _split_pdf_sections


def test_split_pdf_sections_uppercase_headings():
    text = (
        "INTRODUCTION\n"
        "This is the intro paragraph.\n\n"
        "AUTHENTICATION\n"
        "Use OAuth tokens.\n"
    )
    sections = _split_pdf_sections(text)
    assert sections == [
        ("INTRODUCTION", "This is the intro paragraph."),
        ("AUTHENTICATION", "Use OAuth tokens."),
    ]


def test_split_pdf_sections_numbered_headings():
    text = (
        "1. Overview\n"
        "Some prose.\n\n"
        "2. Endpoints\n"
        "More prose.\n"
    )
    sections = _split_pdf_sections(text)
    names = [s[0] for s in sections]
    assert names == ["1. Overview", "2. Endpoints"]


def test_split_pdf_sections_handles_no_headings():
    """Text without any heading produces a single 'General' section."""
    text = "Just some flat content with no headings at all.\n"
    sections = _split_pdf_sections(text)
    assert len(sections) == 1
    assert sections[0][0] == "General"
