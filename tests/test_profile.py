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
