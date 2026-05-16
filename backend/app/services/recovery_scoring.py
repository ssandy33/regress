"""Recovery Plan scoring engine — deterministic recommendation layer.

Consumes the path list emitted by :mod:`app.services.recovery_engine` plus
the user's OKR settings and emits a deterministic ``Recommendation`` dict:

- ``recommended_path_id`` — slug of the single best-fit eligible path, or
  ``None`` in the two degradation states (no-clear-best-fit / no-eligible).
- ``recommendation_label`` — template-rendered, never free-form prose.
- ``recommendation_reasons`` — 2–4 template-rendered explanation strings.
- ``ranked_paths`` — every path (eligible + suppressed) with score + rank.
- ``path_scores`` — one row per criterion × every eligible path; the
  Inspect-Scoring matrix's source of truth.
- ``tie_epsilon`` — the constant the matrix renders in its footnote.
- ``disclaimer`` — the canonical legal-style statement per issue AC.

Algorithm:
1. Filter the engine's paths into eligible vs suppressed.
2. For each criterion, rank the eligible paths by the relevant raw value,
   award the criterion's weight in points to the leader (with ties at
   exact equality splitting — all tied leaders get the full weight).
3. Sum points per path → ``totals``. Rank by total; surface as
   ``ranked_paths``.
4. If the top two total scores are within :data:`TIE_EPSILON`, no path is
   recommended (``recommended_path_id = None``).
5. Otherwise render ``recommendation_label`` and 2–4
   ``recommendation_reasons`` from the frozen template dicts.

Pure function: no DB, no HTTP, no LLM. Same input → byte-identical output
(enforced by ``test_recovery_scoring.py::test_reproducibility_*``).

**Strategy-preference bonus** (issue AC, dormant in V0.5.8):

The bonus reads ``okr_settings.strategy_preference``; when the field is
unset (V0.5.8 default — OKR persistence in #156/#157 ships later), every
cell in the bonus row scores ``0`` so the matrix renders the unset-row
form. When the field lands later (income-first → wheel-cc, etc.), no code
change is required.
"""

from __future__ import annotations

from typing import Any

# --- Constants --------------------------------------------------------------

# Top-two total tie threshold. When the gap between rank 1 and rank 2
# eligible totals is ≤ this value, the engine emits
# ``recommended_path_id = None`` and ``recommendation_label = "No clear
# best fit"`` (issue AC §Recommendation engine).
TIE_EPSILON: float = 1.0

# Per-criterion weights. Awarded to the leader (or split among ties at
# exact equality). Defaults from the issue body's scoring table.
WEIGHT_FASTEST_BREAKEVEN: int = 3
WEIGHT_LOWEST_CAPITAL: int = 3
WEIGHT_LOWEST_OPPORTUNITY_COST: int = 2
WEIGHT_STRATEGY_PREFERENCE: int = 2

# Canonical disclaimer rendered by the panel footer. Frozen by snapshot
# tests (`test_recovery_scoring_snapshots.py`).
DISCLAIMER_TEXT: str = (
    "This is a fit recommendation based on your configured preferences "
    "and stated assumptions. It is not investment advice, a price "
    "prediction, or a trade execution suggestion."
)

# Strategy-preference → path-slug mapping. Dormant in V0.5.8; activates
# automatically when #156/#157 persists the field. ``"passive"`` and
# unknown values fall through to no bonus.
STRATEGY_PREFERENCE_TO_PATH: dict[str, str] = {
    "income-first": "wheel-cc",
    "capital-efficient": "sell-redeploy",
    "conviction-add": "average-down",
}

# Label templates — frozen by snapshot tests. Keyed on the recommendation
# state (and optional preference flag where applicable).
LABEL_TEMPLATES: dict[str, str] = {
    # Happy path with no strategy preference (V0.5.8 default).
    "recommended_neutral": "Best fit on capital efficiency and breakeven: {path_label}",
    # Happy path with strategy preference set (activates when #156/#157 lands).
    "recommended_with_strategy_preference": (
        "Best fit for {preference} strategy: {path_label}"
    ),
    # Top-two within tie_epsilon.
    "no_clear_best_fit": "No clear best fit",
    # Every path suppressed.
    "no_eligible_path": "No eligible path under current sizing rules",
}

# Reason templates — keyed on the criterion the path won. The frontend
# never renders these directly; the scoring engine fills in the kwargs and
# returns the resolved strings.
REASON_TEMPLATES: dict[str, str] = {
    "fastest_breakeven_solo": (
        "Fastest expected breakeven ({months} months vs {next_months} for the next option)"
    ),
    "fastest_breakeven_unique": "Fastest expected breakeven ({months} months)",
    "lowest_additional_capital_zero": "Lowest additional capital required ($0)",
    "lowest_additional_capital_amount": (
        "Lowest additional capital required (${capital:,.0f} vs ${next_capital:,.0f} for the next option)"
    ),
    "lowest_opportunity_cost_zero": "Lowest opportunity cost vs baseline (${opp_cost:,.0f})",
    "lowest_opportunity_cost_amount": (
        "Lowest opportunity cost vs baseline (${opp_cost:,.0f})"
    ),
    "strategy_preference_match": "Matches your configured {preference} strategy preference",
    "within_sizing_cap": "Within your per-position sizing cap",
}


# --- Helpers ----------------------------------------------------------------


def _criterion_raw_value(path: dict, criterion: str) -> float | None:
    """Return the raw numeric value a path contributes to a given criterion.

    Returns ``None`` when the path has no value for the criterion (e.g.
    hold-monitor on ``fastest_breakeven``). Callers treat ``None`` as
    "worst tier" — never a leader.
    """
    if criterion == "fastest_breakeven":
        rng = path.get("months_to_breakeven") or {}
        return rng.get("expected")
    if criterion == "lowest_additional_capital":
        return path.get("capital_tied_up")
    if criterion == "lowest_opportunity_cost":
        cost = path.get("opportunity_cost_vs_baseline")
        # Absolute distance from baseline so signed wins on either side
        # don't artificially win this column.
        if cost is None:
            return None
        return abs(cost)
    return None


def _rank_paths_for_criterion(
    eligible: list[dict],
    criterion: str,
    weight: int,
) -> list[dict]:
    """Build the ranking cells for one criterion.

    Lower raw value is better (fastest breakeven, least capital, least
    opportunity cost). ``None`` raw values sort to the bottom and earn
    zero points.

    Returns a list of cell dicts ordered to match the engine's canonical
    path order — the ``rank`` field carries the actual ranking.
    """
    # Build (path_id, raw, original_index) tuples for deterministic sort.
    indexed = []
    for idx, p in enumerate(eligible):
        raw = _criterion_raw_value(p, criterion)
        indexed.append((p["path_id"], raw, idx))

    # Sort: non-None raw values first (ascending), then None values last.
    # The original-index tiebreaker keeps determinism when two paths share
    # the same raw value AND the same path_id (cannot happen in practice,
    # but the guarantee is cheap).
    def _sort_key(entry):
        path_id, raw, idx = entry
        if raw is None:
            return (1, 0.0, idx, path_id)
        return (0, raw, idx, path_id)

    sorted_entries = sorted(indexed, key=_sort_key)

    # Assign ranks: tied non-None values at exact equality share rank 1.
    rank_by_path: dict[str, int] = {}
    points_by_path: dict[str, int] = {}
    leader_raw: float | None = None
    leader_set = False
    for entry in sorted_entries:
        path_id, raw, _ = entry
        if raw is None:
            rank_by_path[path_id] = len(eligible)  # worst rank
            points_by_path[path_id] = 0
            continue
        if not leader_set:
            leader_raw = raw
            leader_set = True
            rank_by_path[path_id] = 1
            points_by_path[path_id] = weight
        elif raw == leader_raw:
            # Exact tie → both leaders get the full weight per the AC
            # ("tied leaders get the full weight"; the example in the
            # issue body awards +3 to every $0-capital path).
            rank_by_path[path_id] = 1
            points_by_path[path_id] = weight
        else:
            # Strict rank-2 and beyond — no points on this criterion.
            # Assign deterministic ranks (2, 3, …) by encounter order.
            rank_by_path[path_id] = max(rank_by_path.values()) + 1
            points_by_path[path_id] = 0

    # Build cell list in canonical (engine emission) order.
    cells: list[dict] = []
    for idx, p in enumerate(eligible):
        path_id = p["path_id"]
        raw = _criterion_raw_value(p, criterion)
        cells.append(
            {
                "path_id": path_id,
                "raw_value": raw,
                "points": points_by_path[path_id],
                "rank": rank_by_path[path_id],
            }
        )
    return cells


def _strategy_preference_row(
    eligible: list[dict],
    weight: int,
    preference: str | None,
) -> dict:
    """Build the strategy-preference bonus row.

    When ``preference`` is unset or maps to no path (V0.5.8 default,
    "passive", or an unknown value), every cell scores ``0``. When the
    preference maps to one of the eligible paths, that path's cell gets
    the full ``weight`` in points.

    The row is always emitted so the frontend can render the unset
    callout (design spec §4.5 row 1).
    """
    target_slug = (
        STRATEGY_PREFERENCE_TO_PATH.get(preference) if preference else None
    )
    cells: list[dict] = []
    for p in eligible:
        slug = p["path_id"]
        if target_slug is not None and slug == target_slug:
            cells.append(
                {
                    "path_id": slug,
                    "raw_value": None,
                    "points": weight,
                    "rank": 1,
                }
            )
        else:
            cells.append(
                {
                    "path_id": slug,
                    "raw_value": None,
                    "points": 0,
                    # Per design spec §4.5: cells in the unset row render as
                    # em-dashes; rank is meaningless. Emit a deterministic
                    # value (worst rank among eligible) for shape stability.
                    "rank": len(eligible),
                }
            )
    return {
        "criterion": "strategy_preference_bonus",
        "weight": weight,
        "ranking": cells,
    }


def _build_reasons(
    *,
    eligible: list[dict],
    recommended: dict,
    path_scores: list[dict],
    okr_settings: dict[str, Any],
) -> list[str]:
    """Build the 2–4 ``recommendation_reasons`` for the recommended path.

    Walks the ``path_scores`` rows in deterministic order, emits one reason
    per criterion where the recommended path was a (sole or tied) leader.
    Always appends "Within your per-position sizing cap" for completeness
    so the reason list is never below 2 entries.
    """
    reasons: list[str] = []
    slug = recommended["path_id"]
    # Index path_scores by criterion for easy lookup.
    by_criterion = {row["criterion"]: row for row in path_scores}

    # 1. fastest_breakeven
    row = by_criterion.get("fastest_breakeven")
    if row:
        cells = {c["path_id"]: c for c in row["ranking"]}
        rec_cell = cells.get(slug)
        if rec_cell and rec_cell["rank"] == 1 and rec_cell["raw_value"] is not None:
            # Look for next-rank (rank > 1) cell with a raw_value to fill the
            # comparison parenthetical.
            next_cells = sorted(
                [c for c in row["ranking"] if c["rank"] > 1 and c["raw_value"] is not None],
                key=lambda c: (c["raw_value"], c["path_id"]),
            )
            if next_cells:
                reasons.append(
                    REASON_TEMPLATES["fastest_breakeven_solo"].format(
                        months=_fmt_months(rec_cell["raw_value"]),
                        next_months=_fmt_months(next_cells[0]["raw_value"]),
                    )
                )
            else:
                reasons.append(
                    REASON_TEMPLATES["fastest_breakeven_unique"].format(
                        months=_fmt_months(rec_cell["raw_value"]),
                    )
                )

    # 2. lowest_additional_capital
    row = by_criterion.get("lowest_additional_capital")
    if row:
        cells = {c["path_id"]: c for c in row["ranking"]}
        rec_cell = cells.get(slug)
        if rec_cell and rec_cell["rank"] == 1:
            raw = rec_cell["raw_value"] or 0
            if raw == 0:
                reasons.append(REASON_TEMPLATES["lowest_additional_capital_zero"])
            else:
                next_cells = sorted(
                    [
                        c
                        for c in row["ranking"]
                        if c["rank"] > 1 and c["raw_value"] is not None
                    ],
                    key=lambda c: (c["raw_value"], c["path_id"]),
                )
                next_capital = next_cells[0]["raw_value"] if next_cells else raw
                reasons.append(
                    REASON_TEMPLATES["lowest_additional_capital_amount"].format(
                        capital=raw,
                        next_capital=next_capital,
                    )
                )

    # 3. lowest_opportunity_cost
    row = by_criterion.get("lowest_opportunity_cost")
    if row:
        cells = {c["path_id"]: c for c in row["ranking"]}
        rec_cell = cells.get(slug)
        if rec_cell and rec_cell["rank"] == 1 and rec_cell["raw_value"] is not None:
            # Use the recommended path's actual signed opportunity cost
            # (the criterion raw_value is the absolute distance).
            signed = next(
                (
                    p.get("opportunity_cost_vs_baseline")
                    for p in eligible
                    if p["path_id"] == slug
                ),
                rec_cell["raw_value"],
            )
            if signed is None:
                signed = rec_cell["raw_value"]
            if signed == 0:
                reasons.append(
                    REASON_TEMPLATES["lowest_opportunity_cost_zero"].format(opp_cost=signed)
                )
            else:
                reasons.append(
                    REASON_TEMPLATES["lowest_opportunity_cost_amount"].format(
                        opp_cost=signed
                    )
                )

    # 4. strategy_preference_bonus
    row = by_criterion.get("strategy_preference_bonus")
    preference = okr_settings.get("strategy_preference") if okr_settings else None
    if (
        row
        and preference
        and STRATEGY_PREFERENCE_TO_PATH.get(preference) == slug
    ):
        reasons.append(
            REASON_TEMPLATES["strategy_preference_match"].format(preference=preference)
        )

    # Always-present anchor when nothing else fits (keeps list ≥ 2 entries).
    if len(reasons) < 2:
        reasons.append(REASON_TEMPLATES["within_sizing_cap"])

    # Per AC: 2–4 entries. Cap deterministically.
    return reasons[:4]


def _fmt_months(value: float) -> str:
    """Format a months value for reason templates (drop trailing zeros)."""
    if value == int(value):
        return f"{int(value)}"
    return f"{value:g}"


def _build_label(
    *,
    recommended: dict | None,
    state: str,
    preference: str | None,
) -> str:
    """Render the recommendation label from the frozen template dict."""
    if state == "no_clear_best_fit":
        return LABEL_TEMPLATES["no_clear_best_fit"]
    if state == "no_eligible_path":
        return LABEL_TEMPLATES["no_eligible_path"]
    # Happy path.
    if (
        preference
        and recommended
        and STRATEGY_PREFERENCE_TO_PATH.get(preference) == recommended["path_id"]
    ):
        return LABEL_TEMPLATES["recommended_with_strategy_preference"].format(
            preference=preference,
            path_label=recommended["label"],
        )
    return LABEL_TEMPLATES["recommended_neutral"].format(
        path_label=recommended["label"] if recommended else "",
    )


# --- Public surface ---------------------------------------------------------


def score_recovery_paths(
    paths: list[dict],
    okr_settings: dict[str, Any] | None = None,
) -> dict:
    """Score the engine's paths and emit the deterministic recommendation.

    Args:
        paths: Output of :func:`recovery_engine.compute_recovery_paths`.
            Suppressed paths must still be present; this function filters
            them.
        okr_settings: Optional dict carrying ``target_yield``,
            ``sizing_cap_dollars``, and ``strategy_preference``. Missing
            keys are treated as unset.

    Returns:
        Recommendation dict ready to attach to the ``RecoveryPlanResponse``.
    """
    okr_settings = okr_settings or {}
    preference = okr_settings.get("strategy_preference") or None

    eligible = [p for p in paths if p.get("eligibility") == "eligible"]
    suppressed = [p for p in paths if p.get("eligibility") == "suppressed"]

    # All paths suppressed → "No eligible path".
    if not eligible:
        ranked = [
            {
                "path_id": p["path_id"],
                "score": None,
                "rank": None,
                "suppression_reason": p.get("suppression_reason") or "",
            }
            for p in paths
        ]
        return {
            "recommended_path_id": None,
            "recommendation_label": _build_label(
                recommended=None, state="no_eligible_path", preference=preference
            ),
            "recommendation_reasons": [
                "Every path violates your configured constraints.",
                "Adjust your caps in Settings → OKRs to enable more paths.",
            ],
            "ranked_paths": ranked,
            "path_scores": [],
            "tie_epsilon": TIE_EPSILON,
            "disclaimer": DISCLAIMER_TEXT,
        }

    # Per-criterion ranking.
    path_scores: list[dict] = [
        {
            "criterion": "fastest_breakeven",
            "weight": WEIGHT_FASTEST_BREAKEVEN,
            "ranking": _rank_paths_for_criterion(
                eligible, "fastest_breakeven", WEIGHT_FASTEST_BREAKEVEN
            ),
        },
        {
            "criterion": "lowest_additional_capital",
            "weight": WEIGHT_LOWEST_CAPITAL,
            "ranking": _rank_paths_for_criterion(
                eligible, "lowest_additional_capital", WEIGHT_LOWEST_CAPITAL
            ),
        },
        {
            "criterion": "lowest_opportunity_cost",
            "weight": WEIGHT_LOWEST_OPPORTUNITY_COST,
            "ranking": _rank_paths_for_criterion(
                eligible, "lowest_opportunity_cost", WEIGHT_LOWEST_OPPORTUNITY_COST
            ),
        },
        _strategy_preference_row(eligible, WEIGHT_STRATEGY_PREFERENCE, preference),
    ]

    # Aggregate totals.
    totals: dict[str, int] = {p["path_id"]: 0 for p in eligible}
    for row in path_scores:
        for cell in row["ranking"]:
            totals[cell["path_id"]] += cell["points"]

    # Rank eligible paths by total (desc); tie-break on canonical engine
    # order so the output is fully deterministic.
    order_by_slug = {p["path_id"]: idx for idx, p in enumerate(eligible)}
    sorted_eligible = sorted(
        eligible,
        key=lambda p: (-totals[p["path_id"]], order_by_slug[p["path_id"]]),
    )

    # Assign integer ranks; equal totals share the same rank (dense ranking
    # is overkill here — the matrix Total/Rank rows just need a number).
    ranked_paths: list[dict] = []
    last_total: int | None = None
    last_rank = 0
    for idx, p in enumerate(sorted_eligible):
        total = totals[p["path_id"]]
        if total != last_total:
            last_rank = idx + 1
            last_total = total
        ranked_paths.append(
            {
                "path_id": p["path_id"],
                "score": total,
                "rank": last_rank,
                "suppression_reason": None,
            }
        )

    # Append suppressed paths so the full deck is in ``ranked_paths``.
    for p in suppressed:
        ranked_paths.append(
            {
                "path_id": p["path_id"],
                "score": None,
                "rank": None,
                "suppression_reason": p.get("suppression_reason") or "",
            }
        )

    # Tie-epsilon check on top two eligible totals.
    top_total = ranked_paths[0]["score"] if ranked_paths else None
    second_total: int | None = None
    if len(sorted_eligible) >= 2:
        second_total = totals[sorted_eligible[1]["path_id"]]

    no_clear_best = (
        second_total is not None
        and top_total is not None
        and (top_total - second_total) <= TIE_EPSILON
    )

    if no_clear_best:
        # Build a degradation-state reason list referencing the top two.
        top_two = sorted_eligible[:2]
        reasons = [
            (
                "The top two paths score within "
                f"{int(TIE_EPSILON)} point of each other — both are within "
                "your configured preferences."
            ),
            f"Close on: {top_two[0]['label']} and {top_two[1]['label']}.",
        ]
        return {
            "recommended_path_id": None,
            "recommendation_label": _build_label(
                recommended=None, state="no_clear_best_fit", preference=preference
            ),
            "recommendation_reasons": reasons,
            "ranked_paths": ranked_paths,
            "path_scores": path_scores,
            "tie_epsilon": TIE_EPSILON,
            "disclaimer": DISCLAIMER_TEXT,
        }

    # Happy path — single winner.
    recommended = sorted_eligible[0]
    label = _build_label(
        recommended=recommended, state="recommended", preference=preference
    )
    reasons = _build_reasons(
        eligible=eligible,
        recommended=recommended,
        path_scores=path_scores,
        okr_settings=okr_settings,
    )
    return {
        "recommended_path_id": recommended["path_id"],
        "recommendation_label": label,
        "recommendation_reasons": reasons,
        "ranked_paths": ranked_paths,
        "path_scores": path_scores,
        "tie_epsilon": TIE_EPSILON,
        "disclaimer": DISCLAIMER_TEXT,
    }


__all__ = [
    "TIE_EPSILON",
    "WEIGHT_FASTEST_BREAKEVEN",
    "WEIGHT_LOWEST_CAPITAL",
    "WEIGHT_LOWEST_OPPORTUNITY_COST",
    "WEIGHT_STRATEGY_PREFERENCE",
    "DISCLAIMER_TEXT",
    "STRATEGY_PREFERENCE_TO_PATH",
    "LABEL_TEMPLATES",
    "REASON_TEMPLATES",
    "score_recovery_paths",
]
