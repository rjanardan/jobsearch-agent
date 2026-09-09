"""Profile schema + resume-text handling tests (FR-1/2)."""

from __future__ import annotations

import pytest

from jobagent.tools.profile import (
    ProfileData,
    ProfileParseError,
    load_structured,
    strip_html,
)


def test_yaml_profile_roundtrip(tmp_path) -> None:
    p = tmp_path / "profile.yaml"
    p.write_text(
        "name: Tester\n"
        "location: Bengaluru, India\n"
        "skills:\n"
        "  - name: Python\n"
        "    proficiency: 5\n"
        "domains: [AI]\n",
        encoding="utf-8",
    )
    data = load_structured(p)
    assert data.name == "Tester"
    assert data.skills[0].proficiency == 5


def test_bad_proficiency_rejected(tmp_path) -> None:
    p = tmp_path / "profile.yaml"
    p.write_text("skills:\n  - name: Go\n    proficiency: 9\n", encoding="utf-8")
    with pytest.raises(ProfileParseError):
        load_structured(p)


def test_html_strip() -> None:
    html = "<div><p>Build <b>agents</b> with Python</p>&amp; tools</div>"
    out = strip_html(html)
    assert "agents" in out
    assert "<" not in out
    assert "&amp;" not in out


def test_unsupported_extension_rejected(tmp_path) -> None:
    p = tmp_path / "resume.docx"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        from jobagent.tools.profile import _read_text

        _read_text(p)


def test_profile_data_serializes() -> None:
    data = ProfileData.model_validate({"name": "X", "skills": [{"name": "Py", "proficiency": 3}]})
    dumped = data.model_dump(mode="json")
    assert dumped["skills"][0]["proficiency"] == 3


def test_html_to_text_preserves_structure_and_drops_markup() -> None:
    from jobagent.tools.profile import html_to_text

    html = (
        "<html><head><style>body{color:red}</style>"
        "<script>var x=1;</script></head><body>"
        "<h1>Janardhan Revuru</h1>"
        "<p>AI engineering leader</p>"
        "<ul><li>Python</li><li>PyTorch</li></ul>"
        "<h2>Experience</h2><p>Built agentic systems 2019&ndash;2026</p>"
        "</body></html>"
    )
    out = html_to_text(html)
    assert "Janardhan Revuru" in out
    assert "AI engineering leader" in out
    assert "Python" in out and "PyTorch" in out
    assert "Experience" in out
    assert "–" in out  # &ndash; decoded
    assert "<" not in out
    assert "var x=1" not in out  # script content dropped
    assert "color:red" not in out  # style content dropped


def test_html_resume_readable_by_read_text(tmp_path) -> None:
    from jobagent.tools.profile import _read_text

    p = tmp_path / "resume.html"
    p.write_text("<html><body><h1>Hi</h1><p>Body text here.</p></body></html>", encoding="utf-8")
    text = _read_text(p)
    assert "Hi" in text and "Body text here" in text
