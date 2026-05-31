"""Tests for the Phase 0 identity resolver.

These exercise the resolution strategy (exact id key, attached cross-id, fuzzy
name fallback, position disambiguation, name normalization) without any network
or database — the crosswalk is an in-memory fixture.
"""

from __future__ import annotations

import pytest

from ffdraft.identity import IdentityResolver, normalize_name


@pytest.fixture
def crosswalk() -> list[dict]:
    return [
        {
            "gsis_id": "00-0036389", "full_name": "Ja'Marr Chase", "position": "WR",
            "sleeper_id": "6794", "espn_id": "4362628", "yahoo_id": "32703", "pfr_id": "ChasJa00",
        },
        {
            "gsis_id": "00-0037240", "full_name": "Marvin Harrison Jr.", "position": "WR",
            "sleeper_id": "11628", "espn_id": "4432708",
        },
        {
            # Same surname/first-name family, different person & position to test
            # position disambiguation on a shared normalized name is not needed,
            # but a near-duplicate name is.
            "gsis_id": "00-0099999", "full_name": "Michael Carter", "position": "RB",
            "sleeper_id": "7600",
        },
        {
            "gsis_id": "00-0088888", "full_name": "Michael Carter", "position": "WR",
            "sleeper_id": "8200",
        },
        {
            "gsis_id": "00-0034796", "full_name": "Patrick Mahomes", "position": "QB",
            "sleeper_id": "4046", "espn_id": "3139477",
        },
    ]


def test_normalize_name_handles_punct_accents_suffix():
    assert normalize_name("A.J. Brown") == "aj brown"
    assert normalize_name("Marvin Harrison Jr.") == "marvin harrison"
    assert normalize_name("Ja'Marr Chase") == "jamarr chase"
    assert normalize_name("D'Andre  Swift") == "dandre swift"
    assert normalize_name(None) == ""


def test_normalize_name_handles_common_adp_aliases():
    assert normalize_name("Hollywood Brown") == "marquise brown"
    assert normalize_name("Gabe Davis") == "gabriel davis"
    assert normalize_name("Chig Okonkwo") == "chigoziem okonkwo"
    assert normalize_name("Jeff Wilson Jr.") == "jeffery wilson"


def test_exact_id_key_resolution(crosswalk):
    r = IdentityResolver(crosswalk)
    res = r.resolve(source="sleeper", source_id="6794", name="Ja'Marr Chase", position="WR")
    assert res.gsis_id == "00-0036389"
    assert res.confidence == 1.0
    assert res.method == "id_key"


def test_attached_cross_id_preferred(crosswalk):
    # ADP feed gives its own id but also carries a sleeper_id we trust.
    r = IdentityResolver(crosswalk)
    res = r.resolve(
        source="adp:fantasypros", source_id="4046",
        name="Pat Mahomes", position="QB", prefer_id_source="sleeper",
    )
    assert res.gsis_id == "00-0034796"
    assert res.method == "id_key"
    assert res.confidence == 1.0


def test_fuzzy_name_fallback(crosswalk):
    # Source only gives a (slightly off) name, no usable id key.
    r = IdentityResolver(crosswalk)
    res = r.resolve(source="adp:x", source_id="zzz", name="Marvin Harrison", position="WR")
    assert res.gsis_id == "00-0037240"
    assert res.method == "fuzzy"
    assert 0.0 < res.confidence <= 1.0


def test_position_disambiguates_duplicate_names(crosswalk):
    r = IdentityResolver(crosswalk)
    rb = r.resolve(source="adp:x", source_id="a", name="Michael Carter", position="RB")
    wr = r.resolve(source="adp:x", source_id="b", name="Michael Carter", position="WR")
    assert rb.gsis_id == "00-0099999"
    assert wr.gsis_id == "00-0088888"


def test_unresolved_when_no_id_and_no_name_match(crosswalk):
    r = IdentityResolver(crosswalk)
    res = r.resolve(source="adp:x", source_id="q", name="Totally Unknown Person", position="WR")
    assert res.gsis_id is None
    assert res.method == "unresolved"
    assert res.confidence == 0.0
