"""Player identity resolver.

The Phase 0 spine. Every external source (Sleeper, ADP providers, ESPN, Yahoo)
must map onto one canonical player. We resolve in priority order:

  1. Direct id-key match against the nflverse crosswalk (sleeper_id, espn_id,
     yahoo_id, pfr_id, gsis_id). These are exact and trustworthy -> confidence 1.0.
  2. Fuzzy fallback on normalized (name, position, team) for sources that only
     give a name. Confidence < 1.0, and we record the method so the Gate-0
     hand-check can audit every fuzzy match.

The crosswalk is `nflreadpy.load_players()`, exposed here as a list of dicts so
the resolver is trivially testable without a network or database.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz, process

# nflverse columns that carry a foreign-source id, mapped to our `source` label.
_NFLVERSE_ID_COLUMNS: dict[str, str] = {
    "sleeper_id": "sleeper",
    "espn_id": "espn",
    "yahoo_id": "yahoo",
    "pfr_id": "pfr",
    "gsis_id": "nflverse",
}

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name: str | None) -> str:
    """Lowercase, strip accents/punctuation/suffixes, collapse whitespace.

    "A.J. Brown" -> "aj brown"; "Marvin Harrison Jr." -> "marvin harrison".
    """
    if not name:
        return ""
    # Strip accents.
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = name.lower()
    # Delete intra-name punctuation so initials/contractions collapse:
    #   "a.j." -> "aj", "ja'marr" -> "jamarr". Then turn the rest into spaces.
    name = re.sub(r"[.'`]", "", name)
    name = re.sub(r"[^a-z0-9\s]", " ", name)
    tokens = [t for t in name.split() if t and t not in _SUFFIXES]
    return " ".join(tokens)


@dataclass(frozen=True)
class ResolvedAlias:
    """Result of resolving one external record to a canonical player."""

    gsis_id: str | None       # canonical key from the crosswalk
    source: str               # e.g. 'adp:fantasypros'
    source_id: str            # the id (or name-key) as that source knows it
    source_name: str | None
    confidence: float         # 1.0 exact key, <1.0 fuzzy
    method: str               # 'id_key' | 'fuzzy' | 'unresolved'


class IdentityResolver:
    """Resolve external player records onto the nflverse crosswalk."""

    def __init__(self, crosswalk: list[dict], *, fuzzy_threshold: float = 88.0) -> None:
        """`crosswalk`: rows from nflreadpy.load_players() as dicts. Needs at
        least `gsis_id`, `full_name`/`display_name`, `position`, plus any of the
        foreign-id columns in `_NFLVERSE_ID_COLUMNS`.
        """
        self.fuzzy_threshold = fuzzy_threshold
        self._rows = crosswalk
        # Index: (source, str(source_id)) -> gsis_id, for direct key lookups.
        self._id_index: dict[tuple[str, str], str] = {}
        # Index: normalized_name -> list of (gsis_id, position) for fuzzy fallback.
        self._name_index: dict[str, list[tuple[str, str | None]]] = {}
        self._gsis_to_name: dict[str, str] = {}
        self._build_indexes()

    def _row_name(self, row: dict) -> str | None:
        return row.get("full_name") or row.get("display_name") or row.get("name")

    def _build_indexes(self) -> None:
        for row in self._rows:
            gsis = row.get("gsis_id")
            if not gsis:
                continue
            name = self._row_name(row)
            self._gsis_to_name[gsis] = name or ""
            for col, source in _NFLVERSE_ID_COLUMNS.items():
                val = row.get(col)
                if val is None or val == "":
                    continue
                self._id_index[(source, str(val))] = gsis
            norm = normalize_name(name)
            if norm:
                self._name_index.setdefault(norm, []).append((gsis, row.get("position")))

    def resolve_by_id(self, source: str, source_id: str | int) -> str | None:
        """Direct foreign-key resolution. Returns gsis_id or None."""
        return self._id_index.get((source, str(source_id)))

    def resolve(
        self,
        *,
        source: str,
        source_id: str | int,
        name: str | None = None,
        position: str | None = None,
        prefer_id_source: str | None = None,
    ) -> ResolvedAlias:
        """Resolve one external record.

        Strategy:
          - If `prefer_id_source` is given (e.g. the ADP feed also carries a
            sleeper_id), try that exact key first.
          - Then try the source's own key.
          - Then fuzzy-match on name (+ position guard).
        """
        # 1) Exact key via an attached cross-id (best case).
        if prefer_id_source is not None:
            gsis = self.resolve_by_id(prefer_id_source, source_id)
            if gsis:
                return ResolvedAlias(gsis, source, str(source_id), name, 1.0, "id_key")

        # 2) Exact key via the source's own id.
        gsis = self.resolve_by_id(source, source_id)
        if gsis:
            return ResolvedAlias(gsis, source, str(source_id), name, 1.0, "id_key")

        # 3) Fuzzy fallback on name.
        if name:
            match = self._fuzzy_match(name, position)
            if match is not None:
                gsis, score = match
                return ResolvedAlias(
                    gsis, source, str(source_id), name, round(score / 100.0, 4), "fuzzy"
                )

        return ResolvedAlias(None, source, str(source_id), name, 0.0, "unresolved")

    def _fuzzy_match(self, name: str, position: str | None) -> tuple[str, float] | None:
        norm = normalize_name(name)
        if not norm:
            return None
        # Exact normalized hit, disambiguated by position if needed.
        if norm in self._name_index:
            candidates = self._name_index[norm]
            if position:
                pos_hits = [g for g, p in candidates if p == position]
                if len(pos_hits) == 1:
                    return pos_hits[0], 100.0
            if len(candidates) == 1:
                return candidates[0][0], 100.0
            # Ambiguous exact name with no clean position split: take first but
            # flag with a slightly reduced score so the audit sees it.
            return candidates[0][0], 95.0

        # True fuzzy search over the normalized-name keyspace.
        choice = process.extractOne(
            norm, self._name_index.keys(), scorer=fuzz.WRatio, score_cutoff=self.fuzzy_threshold
        )
        if choice is None:
            return None
        matched_norm, score, _ = choice
        candidates = self._name_index[matched_norm]
        if position:
            pos_hits = [g for g, p in candidates if p == position]
            if pos_hits:
                return pos_hits[0], score
        return candidates[0][0], score

    def name_for(self, gsis_id: str) -> str:
        return self._gsis_to_name.get(gsis_id, "")
