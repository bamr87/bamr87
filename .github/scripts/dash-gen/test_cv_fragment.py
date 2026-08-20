"""Tests for cv_fragment — the registry -> bamr87/cv portfolio projection."""
from __future__ import annotations

import cv_fragment


def _reg() -> list[dict]:
    return [
        {
            "name": "alpha",
            "slug": "alpha",
            "description": "Active thing.",
            "stack": ["python", "jekyll"],
            "repo_url": "https://github.com/bamr87/alpha",
            "status": "active",
            "featured": False,
            "live_url": "https://alpha.example",
        },
        {
            "name": "beta",
            "slug": "beta",
            "description": "Featured but dormant.",
            "stack": ["react"],
            "repo_url": "https://github.com/bamr87/beta",
            "status": "maintenance",
            "featured": True,
        },
        {
            "name": "gone",
            "slug": "gone",
            "description": "Archived — never CV-worthy.",
            "stack": ["cobol"],
            "repo_url": "https://github.com/bamr87/gone",
            "status": "archived",
            "featured": True,
        },
        {
            "name": "lab",
            "slug": "lab",
            "description": "Experiment, not featured.",
            "stack": ["rust"],
            "repo_url": "https://github.com/bamr87/lab",
            "status": "experiment",
            "featured": False,
        },
    ]


def test_selection_rules():
    ids = [p["id"] for p in cv_fragment.build_fragment(_reg())["projects"]]
    assert "fleet-alpha" in ids, "active projects are included"
    assert "fleet-beta" in ids, "featured projects are included even in maintenance"
    assert "fleet-gone" not in ids, "archived is excluded even when featured"
    assert "fleet-lab" not in ids, "unfeatured experiments are excluded"


def test_ordering_featured_first():
    ids = [p["id"] for p in cv_fragment.build_fragment(_reg())["projects"]]
    assert ids == ["fleet-beta", "fleet-alpha"]


def test_project_shape_matches_cvdata_contract():
    projects = cv_fragment.build_fragment(_reg())["projects"]
    alpha = next(p for p in projects if p["id"] == "fleet-alpha")
    # CVData Project keys the adopter keeps…
    assert alpha["name"] == "alpha"
    assert alpha["technologies"] == ["python", "jekyll"]
    assert alpha["github"] == "https://github.com/bamr87/alpha"
    assert alpha["url"] == "https://alpha.example"
    assert alpha["startDate"] == "", "registry has no dates; adopter fills"
    # …and the adoption metadata it strips.
    assert alpha["fleet_status"] == "active"
    assert alpha["featured"] is False
    beta = next(p for p in projects if p["id"] == "fleet-beta")
    assert "url" not in beta, "no live_url -> no url key"


def test_skill_rollup_excludes_archived_and_sorts():
    skills = cv_fragment.build_fragment(_reg())["skills"]
    assert len(skills) == 1
    assert skills[0]["skills"] == ["jekyll", "python", "react", "rust"]
    assert "cobol" not in skills[0]["skills"], "archived stacks stay out"


def test_render_is_deterministic():
    assert cv_fragment.render(_reg()) == cv_fragment.render(_reg())
    assert cv_fragment.render(_reg()).endswith("\n")
