"""Per-leg §R6 rule-monitor — the verdict layer (issue #240).

This module owns the ManagementTriggers §R6 rule evaluation that sits *on
top of* the already-shipped ``% CAPT`` profit-target signal (PR #241). It is
pure: every input is a plain value, every output is a plain dict. There is no
DB access, no I/O, and nothing here raises — so the dashboard route's
generic-500 wrapper is untouched.

The keystone export is :func:`evaluate_leg_rules`. It evaluates all four §R6
rules against an open leg (fired and not-fired alike), resolves precedence to
a single governing rule, and returns a ``(verdict, verdict_label, reasoning,
triggered_rules)`` tuple. ``dashboard_legs.py`` calls it once per leg; the
result feeds three render sites — the ``ACTION`` verdict column, the inspect
panel, and the two new NextActions cards — so all three agree by construction.

Advice-framing discipline (spec §11): every ``reasoning`` string attributes
the verdict to *the user's ruleset* — "Your 50% profit-take rule triggered" —
never to the app. The app reports what the user's own rules said.
"""

from __future__ import annotations

# Highest priority first. The governing rule owns the verdict, the verdict
# label, the reasoning sentence, and the single emitted card. Spec §1.
RULE_PRECEDENCE: tuple[str, ...] = (
    "assignment",      # expiration_warning_days window AND leg is ITM
    "expiration",      # expiration_warning_days window, OTM
    "profit_review",   # profit_review_pct threshold crossed
    "dte_review",      # dte_review_days window
)

# Precedence/verdict key -> the leg ``verdict`` string the frontend ACTION
# column keys its visual treatment off. These are the verdict *buckets*.
_RULE_ID_TO_VERDICT: dict[str, str] = {
    "assignment": "assignment",
    "expiration": "expiration",
    "profit_review": "profit_take_review",
    "dte_review": "dte_review",
}

# Precedence/verdict key -> the spec §6.2 ``rule_id`` enum carried on the
# RuleEvaluation dict. ``assignment`` and ``expiration`` are two verdict
# buckets from the one §R6 ``expiration_warning`` rule, so the precedence key
# and the ``rule_id`` differ — this map keeps the mapping explicit.
_RULE_ID_FOR_BUCKET: dict[str, str] = {
    "assignment": "assignment_risk",
    "expiration": "expiration_warning",
    "profit_review": "profit_review",
    "dte_review": "dte_review",
}


def _format_dollars(amount: float) -> str:
    """Render a dollar amount with comma grouping (e.g. ``$22.84``)."""
    return f"${amount:,.2f}"


def _captured_dollars(captured_pct: float | None, premium: float | None) -> float | None:
    """Dollar value of the captured premium fraction, or ``None`` when unknown."""
    if captured_pct is None or premium is None:
        return None
    return round(captured_pct * premium, 2)


def _moneyness_label(moneyness_state: str | None) -> str:
    """Human label for the assignment-risk metric Value column."""
    if moneyness_state == "ITM":
        return "ITM"
    if moneyness_state == "ATM":
        return "ATM"
    if moneyness_state == "OTM":
        return "OTM"
    return "—"


def _reasoning_for(
    governing: str | None,
    *,
    dte: int,
    captured_pct: float | None,
    premium: float | None,
    profit_review_pct: float,
    dte_review_days: int,
    expiration_warning_days: int,
    also_fired: list[str],
    short: bool = False,
) -> str:
    """Build the §3.4 plain-language reasoning sentence.

    ``short=True`` returns the compact card ``reason`` form; ``short=False``
    returns the full inspect-panel sentence. Both share this one dispatch so
    the card and the table can never drift. ``also_fired`` is the list of
    non-governing precedence keys that also triggered — appended as a clause
    when present (spec §3.5).

    Every sentence attributes the verdict to the user's ruleset (spec §11).
    """
    pct = f"{profit_review_pct:g}"

    if governing is None:
        return "No management rule has triggered for this leg yet."

    if governing == "profit_review":
        captured = round((captured_pct or 0.0) * 100)
        if short:
            sentence = (
                f"Your {pct}% profit-take rule triggered — "
                f"{captured}% of max premium captured."
            )
        else:
            dollars = _captured_dollars(captured_pct, premium)
            if dollars is not None and premium is not None:
                amount_clause = (
                    f" ({_format_dollars(dollars)} of {_format_dollars(premium)})"
                )
            else:
                amount_clause = ""
            sentence = (
                f"Your {pct}% profit-take rule triggered. This leg has captured "
                f"{captured}% of its max premium{amount_clause} — past the "
                f"{pct}% review threshold you set."
            )
    elif governing == "dte_review":
        if short:
            sentence = (
                f"{dte} days to expiration — your review window. "
                "Decide: hold, roll, or close."
            )
        else:
            sentence = (
                f"This leg is inside your {dte_review_days}-day review window "
                f"({dte} days to expiration). Your rule says: decide — "
                "hold, roll, or close."
            )
    elif governing == "expiration":
        sentence = (
            f"Your expiration rule triggered — {dte} days to expiration, "
            f"inside your {expiration_warning_days}-day warning window."
        )
    else:  # assignment
        sentence = (
            f"Your expiration rule triggered and this leg is ITM — "
            f"{dte} days to expiration with assignment risk."
        )

    if also_fired:
        clauses = []
        for key in also_fired:
            if key == "dte_review":
                clauses.append(f"inside your {dte_review_days}-day review window")
            elif key == "profit_review":
                clauses.append(f"past your {pct}% profit-take threshold")
            elif key == "expiration":
                clauses.append(
                    f"inside your {expiration_warning_days}-day warning window"
                )
        if clauses:
            joined = "; ".join(clauses)
            # Trim the trailing period before appending the parenthetical.
            stem = sentence[:-1] if sentence.endswith(".") else sentence
            sentence = f"{stem} (this leg is also {joined})."

    return sentence


def _verdict_label(governing: str | None, profit_review_pct: float, dte_review_days: int) -> str:
    """Render the fully-formed verdict label string for the ACTION column.

    Server-rendered so the frontend does no threshold parsing — the label
    says exactly what the user's rule said (spec §2.2). The user's configured
    thresholds are interpolated, so a 65% ``profit_review_pct`` reads
    ``Review · 65%``.
    """
    if governing == "profit_review":
        return f"Review · {profit_review_pct:g}%"
    if governing == "dte_review":
        return f"Review · {dte_review_days:g}d"
    if governing == "expiration":
        return "Close · exp"
    if governing == "assignment":
        return "Close · ITM"
    return "Hold"


def evaluate_leg_rules(
    *,
    dte: int,
    moneyness_state: str | None,
    profit_target_status: dict,
    premium: float | None,
    current_mid: float | None,
    profit_review_pct: float = 50.0,
    dte_review_days: int = 21,
    expiration_warning_days: int = 7,
    assignment_risk: str = "low",
) -> tuple[str, str, str, list[dict]]:
    """Evaluate the four §R6 management rules against one open leg.

    Returns ``(verdict, verdict_label, reasoning, triggered_rules)``:

    - ``verdict`` — the governing rule's verdict bucket (``profit_take_review``
      / ``dte_review`` / ``expiration`` / ``assignment``), or ``"hold"`` when
      nothing fired.
    - ``verdict_label`` — the fully-rendered ACTION-column label string
      (``"Review · 50%"`` / ``"Hold"`` / …). Server-rendered; no frontend
      threshold parsing.
    - ``reasoning`` — the §3.4 plain-language sentence for the governing rule;
      the "nothing triggered" sentence when ``verdict == "hold"``.
    - ``triggered_rules`` — one RuleEvaluation dict per §R6 rule, fired and
      not-fired alike, in fixed :data:`RULE_PRECEDENCE` order.

    Graceful degradation (spec §2.5): when ``current_mid`` is ``None`` the
    ``captured_pct`` is ``None``, the ``profit_review`` row is
    ``status="no"`` / ``value_display="—"``, and ``profit_review`` can never
    be the governing rule — the verdict falls back to the DTE/moneyness rules.
    """
    captured_pct = (profit_target_status or {}).get("captured_pct")
    is_itm = moneyness_state == "ITM"
    in_warning_window = 0 <= dte <= expiration_warning_days
    in_dte_window = 0 <= dte <= dte_review_days
    expired = dte < 0

    # --- assignment (7d ITM) — never a countdown: triggered or no. ----------
    if in_warning_window and is_itm:
        assignment_status = "triggered"
    else:
        assignment_status = "no"

    # --- expiration (7d OTM) — carries the not-yet countdown for non-ITM. ---
    if in_warning_window and not is_itm:
        expiration_status = "triggered"
    elif expired:
        expiration_status = "no"
    elif dte > expiration_warning_days:
        expiration_status = "not_yet"
    else:
        # In the warning window but ITM — the assignment rule owns this leg;
        # the expiration row reports "no" so it is not double-flagged.
        expiration_status = "no"

    # --- profit_review — unevaluable without a live mid. --------------------
    threshold_fraction = profit_review_pct / 100
    if captured_pct is None:
        profit_status = "no"
    elif captured_pct >= threshold_fraction:
        profit_status = "triggered"
    else:
        profit_status = "not_yet"

    # --- dte_review (21d window) — carries a not-yet countdown. -------------
    if in_dte_window:
        dte_review_status = "triggered"
    elif expired:
        dte_review_status = "no"
    else:
        dte_review_status = "not_yet"

    status_by_bucket: dict[str, str] = {
        "assignment": assignment_status,
        "expiration": expiration_status,
        "profit_review": profit_status,
        "dte_review": dte_review_status,
    }

    # Governing rule = first triggered rule in precedence order.
    governing: str | None = None
    for key in RULE_PRECEDENCE:
        if status_by_bucket[key] == "triggered":
            governing = key
            break

    verdict = _RULE_ID_TO_VERDICT.get(governing, "hold") if governing else "hold"
    verdict_label = _verdict_label(governing, profit_review_pct, dte_review_days)

    also_fired = [
        key
        for key in RULE_PRECEDENCE
        if key != governing and status_by_bucket[key] == "triggered"
    ]
    reasoning = _reasoning_for(
        governing,
        dte=dte,
        captured_pct=captured_pct,
        premium=premium,
        profit_review_pct=profit_review_pct,
        dte_review_days=dte_review_days,
        expiration_warning_days=expiration_warning_days,
        also_fired=also_fired,
    )

    # --- Build the four RuleEvaluation dicts, in RULE_PRECEDENCE order. -----
    dte_value = f"{dte} d"
    captured_value = (
        f"{round(captured_pct * 100)}%" if captured_pct is not None else "—"
    )
    moneyness_value = _moneyness_label(moneyness_state)

    rows: list[dict] = []
    for key in RULE_PRECEDENCE:
        status = status_by_bucket[key]
        is_governing = key == governing
        if key == "assignment":
            metric_label = "Assignment risk"
            value_display = moneyness_value
            rule_display = "Review at ≥ High"
        elif key == "expiration":
            metric_label = "Days to expiration"
            value_display = dte_value
            rule_display = f"Warn at ≤ {expiration_warning_days} d"
        elif key == "profit_review":
            metric_label = "Premium captured"
            value_display = captured_value
            rule_display = f"Review at ≥ {profit_review_pct:g}%"
        else:  # dte_review
            metric_label = "Days to expiration"
            value_display = dte_value
            rule_display = f"Review at ≤ {dte_review_days} d"
        rows.append(
            {
                "rule_id": _RULE_ID_FOR_BUCKET[key],
                "metric_label": metric_label,
                "value_display": value_display,
                "rule_display": rule_display,
                "status": status,
                "is_governing": is_governing,
                "reasoning": reasoning if is_governing else None,
            }
        )

    return verdict, verdict_label, reasoning, rows


def card_reason_for(triggered_rules: list[dict], *, profit_review_pct: float, dte_review_days: int) -> str:
    """Build the short-form card ``reason`` from a leg's ``triggered_rules``.

    Reads the governing rule off the already-evaluated ``triggered_rules``
    array so the card and the inspect table share one reasoning source and
    never drift. Returns an empty string when no rule governs (the engine
    only emits a card when a rule fired, so this is defensive).
    """
    governing_row = next(
        (r for r in triggered_rules if r.get("is_governing")), None
    )
    if governing_row is None:
        return ""
    rule_id = governing_row.get("rule_id")
    bucket = next(
        (k for k, v in _RULE_ID_FOR_BUCKET.items() if v == rule_id), None
    )
    captured_pct: float | None = None
    if governing_row.get("value_display", "").endswith("%"):
        try:
            captured_pct = int(governing_row["value_display"][:-1]) / 100
        except ValueError:
            captured_pct = None
    dte = 0
    for row in triggered_rules:
        if row.get("metric_label") == "Days to expiration":
            try:
                dte = int(str(row.get("value_display", "0")).split()[0])
            except (ValueError, IndexError):
                dte = 0
            break
    return _reasoning_for(
        bucket,
        dte=dte,
        captured_pct=captured_pct,
        premium=None,
        profit_review_pct=profit_review_pct,
        dte_review_days=dte_review_days,
        expiration_warning_days=7,
        also_fired=[],
        short=True,
    )


__all__ = [
    "RULE_PRECEDENCE",
    "evaluate_leg_rules",
    "card_reason_for",
]
