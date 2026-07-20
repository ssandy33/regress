"""Decision Dashboard action engine — Next Actions ranking.

The engine is a pure function: given the already-composed status, KPI,
positions, and open-legs slices of a dashboard payload, it returns a
deterministically ranked list of action cards for the frontend to render.

Determinism matters because the section is e2e-tested and the rendering
order is part of the user-visible contract. Sort keys (see
``_sort_key_for``) include the action's stable ``id`` as the final tie
breaker so the engine is bit-for-bit reproducible across runs.

Design rules (per ``frontend/design-specs/decision-dashboard-v05.md`` §2.2
and §14.7):
- Server-side; the frontend renders what it receives.
- No memoization — recomputed on every dashboard load. Cost is one pass
  over already-loaded arrays.
- Cap the output at 8 entries; the frontend hides past 3 behind
  ``[Show N more]``.
- Each action's ``id`` is ``"{action_id}.{subject_id}"`` so React keys are
  stable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import quote

from app.services.rule_monitor import card_reason_for
from app.services.rules_config import DEFAULT_RULES_CONFIG, RulesConfig

# Cap from spec §2.2: anything beyond 8 cards is noise; the user should
# triage in the destination tool.
MAX_ACTIONS = 8

# How soon a Schwab refresh-token expiry should trigger a P1 warning
# action. Schwab refresh tokens last 7 days from issuance, so a 7-day
# threshold would fire immediately after every re-auth and never clear.
# Mirrors the 48-hour log threshold in ``schwab_auth.py:_refresh_tokens``.
TOKEN_EXPIRING_DAYS = 2

# Large-loser dollar threshold (spec §2.2 / Q1). The *percentage* side of the
# largest-loser trigger is the configured
# ``rules_config.risk.loss_review_threshold_pct`` (Trading Rules Layer, issue
# #156), resolved by the dashboard and passed into ``_largest_loser_action``.
# This dollar threshold is an intentionally-retained absolute-loss secondary
# OR-trigger — PRD #209 §R5 models the loss-review rule as a percentage only,
# so a large-share position with a shallow percentage loss still flags on
# absolute dollars. It is a hardcoded heuristic, not a trader-facing rule
# (ADR-002), and mirrors :mod:`app.routers.positions` so the dashboard CTA and
# the recovery page agree on what "flagged" means.
LARGE_LOSER_DOLLAR_THRESHOLD = -1000.0  # -$1,000

# Cap on per-leg ITM short-DTE cards. Spec §2.2: "one card per leg, capped
# at 3 most-urgent".
ITM_SHORT_DTE_CAP = 3

# The DTE threshold for the ITM/short-DTE cards is a trading rule — it is
# resolved from ``rules_config.management.expiration_warning_days`` (issue
# #156) and passed in by the dashboard. The catalog default is 7, so the
# behavior is unchanged when no ``rules_config`` row is stored.

# Sort priority bases per spec §14.7. Lower number = ranked first inside
# the priority bucket. Two sub-bucket keys live alongside these to break
# ties within a single severity bucket (see ``_sub_bucket_for``).
_PRIORITY_RANK: dict[str, int] = {"P0": 0, "P1": 1, "P2": 2}


def _slugify_ticker(ticker: str | None) -> str:
    """Lowercase ticker stub used in stable action IDs."""
    return (ticker or "unknown").lower()


def _format_dollar(amount: float) -> str:
    """Render a signed dollar amount with comma grouping (e.g. ``-$1,420``)."""
    sign = "-" if amount < 0 else "+"
    return f"{sign}${abs(amount):,.0f}"


def _format_signed_pct(pct: float) -> str:
    """Render a signed percentage at one decimal place (e.g. ``-7.2%``)."""
    return f"{pct * 100:+.1f}%"


def _parse_iso_to_utc(value: str | None) -> datetime | None:
    """Best-effort ISO timestamp parser; returns ``None`` on failure."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _sub_bucket_for(action: dict) -> int:
    """Within-bucket ordering key. Lower sorts first.

    Rules per spec §14.7:
    - Within P0: ``data.*`` ranks above ``position.*`` (trust data before
      losses).
    - Within P1: data issues rank above expiration issues, which rank
      above other position issues.
    - Within P2: covered-call candidates rank above the no-open-legs
      scanner card (revenue before lowest-urgency).
    """
    action_id = action["action_id"]
    if action_id.startswith("data."):
        return 0
    if action_id.startswith("expiration."):
        return 1
    if action_id == "leg.profit_take_review":
        # P1, after expiration.* — a deadline outranks an opportunity (§4.2).
        return 2
    if action_id == "leg.dte_review":
        # P2: below cc_candidate(0), above the no-legs scanner(9).
        return 1
    if action_id == "position.cc_candidate":
        # P2 tiebreaker: CC candidates outrank the scanner.
        return 0
    if action_id == "journal.no_open_legs":
        return 9
    return 5


def _tie_breaker_for(action: dict) -> tuple:
    """Tail-end deterministic ordering tuple.

    - P1 expiration cards sort by DTE ascending (closest deadline first).
    - P2 covered-call candidates sort by ticker A→Z.
    - All others fall back to the action ID for a stable lexical order.
    """
    action_id = action["action_id"]
    subject_ticker = (action.get("subject") or {}).get("ticker") or ""
    if action_id == "expiration.itm_short_dte":
        return (action.get("_dte", 0), subject_ticker)
    if action_id == "expiration.short_dte":
        return (action.get("_dte", 0), subject_ticker)
    if action_id in ("leg.profit_take_review", "leg.dte_review"):
        # The §R6 leg cards sort by DTE ascending, then ticker A→Z.
        return (action.get("_dte", 0), subject_ticker)
    if action_id == "position.cc_candidate":
        return (0, subject_ticker)
    return (0, action["id"])


def _sort_key_for(action: dict) -> tuple:
    """Composite deterministic sort key. Lower sorts first.

    Components, in priority order:
    1. priority bucket (P0 < P1 < P2)
    2. within-bucket sub-bucket (e.g. data > position inside P0)
    3. action-type tie breaker (DTE asc / ticker A→Z)
    4. action id (final lexical fallback so equal-priority duplicates
       remain stable)
    """
    return (
        _PRIORITY_RANK[action["priority"]],
        _sub_bucket_for(action),
        _tie_breaker_for(action),
        action["id"],
    )


# --- Action builders --------------------------------------------------------


def _schwab_disconnected_action(schwab_status: dict) -> dict | None:
    """Build a ``data.schwab_disconnected`` card when Schwab is unusable."""
    configured = schwab_status.get("configured")
    valid = schwab_status.get("valid")
    if configured is False or valid is False:
        return {
            "id": "data.schwab_disconnected.schwab",
            "action_id": "data.schwab_disconnected",
            "priority": "P0",
            "title": "Reconnect Schwab",
            "subject": {},
            "reason": (
                "Schwab is disconnected — live prices and trade import are unavailable."
            ),
            "cta": {
                "label": "Open Schwab settings",
                "href": "/settings#schwab",
                "kind": "link",
            },
        }
    return None


def _cache_very_stale_action(cache_status: dict) -> dict | None:
    """Build a ``data.cache_very_stale`` card when very-stale entries exist."""
    very_stale = int(cache_status.get("very_stale") or 0)
    if very_stale <= 0:
        return None
    return {
        "id": "data.cache_very_stale.cache",
        "action_id": "data.cache_very_stale",
        "priority": "P0",
        "title": "Refresh stale market data",
        "subject": {"amount": f"{very_stale} item{'s' if very_stale != 1 else ''}"},
        "reason": (
            f"{very_stale} cached item{'s are' if very_stale != 1 else ' is'} "
            f"over 90 days old. Refresh before trusting downstream metrics."
        ),
        "cta": {
            "label": "Refresh stale data",
            "href": "#refresh-stale-cache",
            "kind": "inline",
        },
    }


def _schwab_token_expiring_action(
    schwab_status: dict, now: datetime | None = None
) -> dict | None:
    """Build a ``data.schwab_token_expiring`` card when expiry is within ``TOKEN_EXPIRING_DAYS``."""
    if schwab_status.get("configured") is not True or schwab_status.get("valid") is False:
        # Disconnected cases are handled by the P0 card above; don't
        # double-emit.
        return None
    expiry_iso = schwab_status.get("expires_at")
    expires_at = _parse_iso_to_utc(expiry_iso)
    if expires_at is None:
        return None
    now = now or datetime.now(timezone.utc)
    delta = expires_at - now
    if delta.total_seconds() < 0:
        # Already expired — `data.schwab_disconnected` handles that case
        # via `valid == False`; this builder is for soon-to-expire only.
        return None
    if delta.total_seconds() > TOKEN_EXPIRING_DAYS * 86400:
        return None
    days = max(delta.days, 0)
    when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
    return {
        "id": "data.schwab_token_expiring.schwab",
        "action_id": "data.schwab_token_expiring",
        "priority": "P1",
        "title": "Renew Schwab token",
        "subject": {"amount": when},
        "reason": (
            f"Schwab refresh token expires {when} — renew before the next session."
        ),
        "cta": {
            "label": "Open Schwab settings",
            "href": "/settings#schwab",
            "kind": "link",
        },
    }


def _loser_drawdown(row: dict) -> tuple[float | None, float | None, bool]:
    """Return ``(eval_pl, eval_pct, on_raw)`` — the drawdown figures the loss
    trigger evaluates for one position row.

    Per ADR #416 (PRD #415 R6, Option B) the review/risk trigger fires on the
    **raw broker-basis** drawdown so a premium-softened (adjusted) basis cannot
    silently pull a real mark-to-market hole back above threshold. When the raw
    figure is absent (CSP/0-share rows carry no broker basis) it falls back to the
    adjusted figure — the conservative choice, since for premium-collected
    positions raw P&L ≤ adjusted P&L, so adjusted-when-raw-null never over-fires.
    ``on_raw`` reports which basis was used so the card can label its firing basis.
    """
    raw_pl = row.get("raw_unrealized_pl")
    if raw_pl is not None:
        return raw_pl, row.get("raw_pl_pct"), True
    return row.get("unrealized_pl"), row.get("pl_pct"), False


def _largest_loser_action(
    positions: Iterable[dict], loss_review_threshold_pct: float
) -> dict | None:
    """Build a ``position.large_loser`` card for the single worst loser.

    Spec §2.2: surface only the single largest loser per cycle, even when
    multiple positions breach the threshold. Trigger is whichever-fires-first
    between the configured loss-review threshold and ``-$1,000``.

    v1.9.0 (#422, ADR #416 Option B): the drawdown inputs are the **raw**
    broker-basis figures (:func:`_loser_drawdown`), falling back to the adjusted
    figures only when the raw basis is genuinely absent. The card labels its
    firing basis via ``trigger_basis="raw"`` when raw drove it.

    ``loss_review_threshold_pct`` is the configured
    ``rules_config.risk.loss_review_threshold_pct`` — a *whole-percent* value
    (e.g. ``-15.0`` for −15%). ``pl_pct`` is a *fraction* (e.g. ``-0.15``), so
    the threshold is divided by 100 before comparison. This mirrors
    :func:`app.routers.positions._is_flagged` so the dashboard largest-loser
    card and the recovery flag gate agree.
    """
    candidates: list[tuple[float, str, dict, float | None, bool]] = []
    for row in positions:
        eval_pl, eval_pct, on_raw = _loser_drawdown(row)
        if eval_pl is None or eval_pl >= 0:
            continue
        triggered = eval_pl <= LARGE_LOSER_DOLLAR_THRESHOLD or (
            eval_pct is not None and eval_pct <= loss_review_threshold_pct / 100.0
        )
        if not triggered:
            continue
        candidates.append((eval_pl, row["ticker"], row, eval_pct, on_raw))
    if not candidates:
        return None
    # Most negative eval_pl wins; ticker A→Z is the deterministic tie
    # breaker so equal-loss positions don't shuffle between runs.
    candidates.sort(key=lambda c: (c[0], c[1]))
    eval_pl, ticker, worst, eval_pct, on_raw = candidates[0]
    amount_dollars = _format_dollar(eval_pl)
    amount_pct = _format_signed_pct(eval_pct) if eval_pct is not None else ""
    # Issue #164: single space between ticker and dollar amount.
    # The earlier ``f"{ticker}  {amount_dollars}"`` rendered as
    # ``AAPL  -$1,234`` in the UI; the frontend prints the string verbatim
    # so the double space was a visible cosmetic defect.
    amount = (
        f"{ticker} {amount_dollars} ({amount_pct})"
        if amount_pct
        else f"{ticker} {amount_dollars}"
    )
    # R6: when the raw basis drove the trigger, spell out the raw-vs-adjusted
    # divergence so the user understands why a card fired below the softer
    # adjusted number they see as the headline. ``trigger_basis="raw"`` drives the
    # frontend "fired on raw basis" tag + ``data-trigger-basis``.
    trigger_basis: str | None = None
    if on_raw:
        trigger_basis = "raw"
        adjusted_pct = worst.get("pl_pct")
        adjusted_note = (
            f" ({_format_signed_pct(adjusted_pct)} adjusted)"
            if adjusted_pct is not None
            else ""
        )
        raw_figure = amount_pct if amount_pct else amount_dollars
        reason = (
            f"Down {raw_figure} on raw broker basis{adjusted_note}. "
            f"Below your {loss_review_threshold_pct:g}% review threshold "
            "(or -$1,000 absolute)."
        )
    else:
        reason = (
            f"Position is below your {loss_review_threshold_pct:g}% "
            "review threshold (or -$1,000 absolute)."
        )
    return {
        "id": f"position.large_loser.{worst['id']}",
        "action_id": "position.large_loser",
        "priority": "P0",
        "title": f"Review {ticker}",
        "subject": {"ticker": ticker, "amount": amount},
        "trigger_basis": trigger_basis,
        "reason": reason,
        # V0.5.8 (#182): the CTA destination moved from the Journal filter
        # page to the new Recovery Plan route. Same PR ships the
        # destination so the link never 404s mid-deploy.
        "cta": {
            "label": f"Review {ticker}",
            "href": f"/positions/{quote(str(worst['id']), safe='')}/recovery",
            "kind": "link",
        },
    }


def _itm_short_dte_actions(
    open_legs: Iterable[dict], short_dte_max: int
) -> list[dict]:
    """Build up to ``ITM_SHORT_DTE_CAP`` per-leg ``expiration.itm_short_dte`` cards.

    ``short_dte_max`` is the DTE threshold resolved from
    ``rules_config.management.expiration_warning_days`` (issue #156).
    """
    cards: list[dict] = []
    for leg in open_legs:
        dte = leg.get("dte")
        moneyness = leg.get("moneyness") or {}
        if dte is None or dte > short_dte_max:
            continue
        if moneyness.get("state") != "ITM":
            continue
        ticker = leg["ticker"]
        strike = leg["strike"]
        option_letter = "P" if leg.get("type") == "put" else "C"
        cards.append(
            {
                "id": f"expiration.itm_short_dte.{leg['id']}",
                "action_id": "expiration.itm_short_dte",
                "priority": "P1",
                "title": f"Roll {ticker} {strike:g}{option_letter}",
                "subject": {
                    "ticker": ticker,
                    "amount": f"{int(dte)} DTE · ITM",
                },
                "reason": (
                    f"Short {leg.get('type', 'put')} is ITM with {int(dte)} day"
                    f"{'s' if dte != 1 else ''} to expiration."
                ),
                # #375: route to the per-leg BTC decision screen (byte-identical
                # to the buy-to-close cards) instead of the Journal data table —
                # the leg id is already in scope, so the urgent ITM card lands on
                # a decision view, not a dead-end.
                "cta": {
                    "label": "Review buy-to-close",
                    "href": (
                        f"/positions/{quote(str(leg['position_id']), safe='')}"
                        f"/legs/{quote(str(leg['id']), safe='')}/btc"
                    ),
                    "kind": "link",
                },
                # Sort metadata consumed by `_tie_breaker_for`.
                "_dte": int(dte),
            }
        )
    cards.sort(key=lambda c: (c["_dte"], c["subject"]["ticker"], c["id"]))
    return cards[:ITM_SHORT_DTE_CAP]


def _short_dte_aggregate_actions(
    open_legs: Iterable[dict], short_dte_max: int
) -> list[dict]:
    """Build aggregated ``expiration.short_dte`` cards — one per ticker.

    Aggregated because a short-DTE OTM book often contains the same ticker
    repeatedly, and per-leg cards would crowd out higher-priority signals.
    ``short_dte_max`` is the DTE threshold resolved from
    ``rules_config.management.expiration_warning_days`` (issue #156).
    """
    by_ticker: dict[str, dict] = {}
    for leg in open_legs:
        dte = leg.get("dte")
        moneyness = leg.get("moneyness") or {}
        if dte is None or dte > short_dte_max:
            continue
        if moneyness.get("state") == "ITM":
            # ITM legs are handled by the per-leg card.
            continue
        ticker = leg["ticker"]
        entry = by_ticker.get(ticker)
        # #375: retain the min-DTE leg's own position_id + id so the aggregate
        # card can route to that most-urgent leg's BTC decision screen. Strict
        # `<` keeps first-seen ties (the first leg at a given min DTE wins).
        if entry is None or dte < entry["min_dte"]:
            by_ticker[ticker] = {
                "ticker": ticker,
                "min_dte": int(dte),
                "position_id": leg["position_id"],
                "leg_id": leg["id"],
                "leg_count": (entry["leg_count"] + 1) if entry else 1,
            }
        else:
            entry["leg_count"] += 1
    cards: list[dict] = []
    for ticker, entry in by_ticker.items():
        count = entry["leg_count"]
        leg_word = "leg" if count == 1 else "legs"
        cards.append(
            {
                "id": f"expiration.short_dte.{ticker.lower()}",
                "action_id": "expiration.short_dte",
                "priority": "P1",
                "title": f"Review {ticker} legs",
                "subject": {
                    "ticker": ticker,
                    "amount": f"{count} {leg_word} ≤ {short_dte_max} DTE",
                },
                "reason": (
                    f"{count} open {leg_word} on {ticker} expire within "
                    f"{short_dte_max} days."
                ),
                # #375: route the aggregate card to the most-urgent (min-DTE)
                # leg's BTC decision screen instead of the Journal data table,
                # so a multi-leg ticker still lands on a decision view.
                "cta": {
                    "label": "Review buy-to-close",
                    "href": (
                        f"/positions/{quote(str(entry['position_id']), safe='')}"
                        f"/legs/{quote(str(entry['leg_id']), safe='')}/btc"
                    ),
                    "kind": "link",
                },
                "_dte": entry["min_dte"],
            }
        )
    cards.sort(key=lambda c: (c["_dte"], c["subject"]["ticker"], c["id"]))
    return cards


def _leg_profit_take_review_actions(
    open_legs: Iterable[dict],
    profit_review_pct: float,
    dte_review_days: int,
    expiration_warning_days: int,
) -> list[dict]:
    """Build ``leg.profit_take_review`` cards — one per leg whose *governing*
    verdict is ``profit_take_review`` (issue #240, spec §4).

    Reads ``leg["verdict"]`` / ``leg["triggered_rules"]`` already computed by
    :mod:`app.services.rule_monitor` — the engine does NOT re-evaluate. Because
    ``verdict`` is already the §R6 governing rule, filtering on it gives
    one-leg-one-card by construction: a leg whose governing verdict is
    ``expiration``/``assignment`` is skipped, so it cannot double-emit
    alongside the existing ``expiration.*`` cards (spec §4.2).
    """
    cards: list[dict] = []
    for leg in open_legs:
        if leg.get("verdict") != "profit_take_review":
            continue
        dte = leg.get("dte")
        ticker = leg["ticker"]
        strike = leg["strike"]
        option_letter = "P" if leg.get("type") == "put" else "C"
        triggered_rules = leg.get("triggered_rules") or []
        cards.append(
            {
                "id": f"leg.profit_take_review.{leg['id']}",
                "action_id": "leg.profit_take_review",
                "priority": "P1",
                # `opportunity` tone — a profit-take is a win, not a warning;
                # NextActionCard renders it emerald with a ✓ glyph (§4.3 Q6).
                "tone": "opportunity",
                "title": "Buy-to-close review",
                "subject": {
                    "ticker": ticker,
                    "amount": f"{strike:g}{option_letter}",
                },
                "reason": card_reason_for(
                    triggered_rules,
                    profit_review_pct=profit_review_pct,
                    dte_review_days=dte_review_days,
                    expiration_warning_days=expiration_warning_days,
                ),
                "cta": {
                    "label": "Review buy-to-close",
                    "href": (
                        f"/positions/{quote(str(leg['position_id']), safe='')}"
                        f"/legs/{quote(str(leg['id']), safe='')}/btc"
                    ),
                    "kind": "link",
                },
                "triggered_rules": triggered_rules,
                # Sort metadata consumed by `_tie_breaker_for`.
                "_dte": int(dte) if dte is not None else 0,
            }
        )
    cards.sort(key=lambda c: (c["_dte"], c["subject"]["ticker"], c["id"]))
    return cards


def _leg_dte_review_actions(
    open_legs: Iterable[dict], dte_review_days: int
) -> list[dict]:
    """Build ``leg.dte_review`` cards — one per leg whose *governing* verdict
    is ``dte_review`` (issue #240, spec §4).

    Like :func:`_leg_profit_take_review_actions`, filters on the precomputed
    ``verdict`` so a leg already governed by a higher-precedence rule
    (``expiration``/``assignment``/``profit_take_review``) is skipped — one
    leg, one card. ``priority`` is ``P2`` and the card carries no ``tone``
    key, so it defaults to ``"warning"`` (slate treatment).
    """
    cards: list[dict] = []
    for leg in open_legs:
        if leg.get("verdict") != "dte_review":
            continue
        dte = leg.get("dte")
        ticker = leg["ticker"]
        strike = leg["strike"]
        option_letter = "P" if leg.get("type") == "put" else "C"
        triggered_rules = leg.get("triggered_rules") or []
        cards.append(
            {
                "id": f"leg.dte_review.{leg['id']}",
                "action_id": "leg.dte_review",
                "priority": "P2",
                "title": f"{dte_review_days}-day review",
                "subject": {
                    "ticker": ticker,
                    "amount": f"{strike:g}{option_letter}",
                },
                "reason": card_reason_for(
                    triggered_rules,
                    profit_review_pct=50.0,
                    dte_review_days=dte_review_days,
                ),
                "cta": {
                    "label": "Review buy-to-close",
                    "href": (
                        f"/positions/{quote(str(leg['position_id']), safe='')}"
                        f"/legs/{quote(str(leg['id']), safe='')}/btc"
                    ),
                    "kind": "link",
                },
                "triggered_rules": triggered_rules,
                "_dte": int(dte) if dte is not None else 0,
            }
        )
    cards.sort(key=lambda c: (c["_dte"], c["subject"]["ticker"], c["id"]))
    return cards


def _cc_candidate_actions(
    positions: Iterable[dict],
    open_legs: Iterable[dict],
) -> list[dict]:
    """Build ``position.cc_candidate`` cards for unsold-call positions.

    Trigger per spec §2.2: ``shares >= 100`` AND no open call leg on that
    ticker. V0.5 assumes every ticker is options-tradable (spec §10 Q6).
    """
    tickers_with_open_calls = {
        leg["ticker"] for leg in open_legs if leg.get("type") == "call"
    }
    cards: list[dict] = []
    for row in positions:
        if (row.get("shares") or 0) < 100:
            continue
        ticker = row["ticker"]
        if ticker in tickers_with_open_calls:
            continue
        shares_int = int(row["shares"])
        href = (
            f"/options?ticker={quote(ticker, safe='')}"
            f"&strategy=covered_call"
            f"&shares={shares_int}"
        )
        # OptionScanRequest.cost_basis is per-share; broker_cost_basis is total.
        # Divide before emitting so the scanner's 10% rule and capital math
        # match (issue #186). Round to 4 decimals to avoid IEEE 754 float
        # noise leaking into the URL (issue #188 — e.g., 1320.66/100 →
        # 13.206600000000002 without round()); 4 decimals matches the
        # precision convention used by recompute_position_state.
        broker_cost_basis = row.get("broker_cost_basis")
        if broker_cost_basis is not None and shares_int > 0:
            cost_basis_per_share = round(broker_cost_basis / shares_int, 4)
            href += f"&cost_basis={quote(str(cost_basis_per_share), safe='')}"
        cards.append(
            {
                "id": f"position.cc_candidate.{_slugify_ticker(ticker)}",
                "action_id": "position.cc_candidate",
                "priority": "P2",
                "title": f"Consider covered call on {ticker}",
                "subject": {
                    "ticker": ticker,
                    "amount": f"{shares_int} shares",
                },
                "reason": (
                    f"You hold {shares_int} {ticker} shares with no open "
                    "call leg — consider writing a covered call."
                ),
                "cta": {
                    "label": f"Scan {ticker}",
                    "href": href,
                    "kind": "link",
                },
            }
        )
    cards.sort(key=lambda c: c["subject"]["ticker"] or "")
    return cards


def _no_open_legs_action(kpis: dict) -> dict | None:
    """Build the single ``journal.no_open_legs`` card when no legs are open.

    Per locked decision: emit even when there are no positions at all — the
    scanner card directs the user to start there.
    """
    if int(kpis.get("open_legs") or 0) != 0:
        return None
    return {
        "id": "journal.no_open_legs.scanner",
        "action_id": "journal.no_open_legs",
        "priority": "P2",
        "title": "Run scanner — no open legs",
        "subject": {},
        "reason": "No open option legs across the journal — run the scanner to find new ideas.",
        "cta": {
            "label": "Open Options",
            "href": "/options",
            "kind": "link",
        },
    }


def _strip_internal_keys(action: dict) -> dict:
    """Drop sort-only metadata (``_dte`` etc.) before emitting to the client."""
    return {k: v for k, v in action.items() if not k.startswith("_")}


def compute_next_actions(
    *,
    status: dict,
    kpis: dict,
    positions: list[dict],
    open_legs: list[dict],
    rules: RulesConfig = DEFAULT_RULES_CONFIG,
    now: datetime | None = None,
) -> list[dict]:
    """Compute the ranked Next Actions list for the dashboard payload.

    Pure function: every input is plain in-memory data already loaded by
    :func:`app.services.dashboard.build_dashboard_payload`. Output is
    deterministic for any given input — same input, same order, byte for
    byte.

    ``rules`` is the resolved :class:`~app.services.rules_config.RulesConfig`
    (issue #156); the caller — ``routers/dashboard.py`` via
    ``build_dashboard_payload`` — resolves it so the engine keeps no DB
    dependency. It defaults to the catalog defaults so a caller that omits it
    behaves exactly as before.

    Returns at most :data:`MAX_ACTIONS` entries.
    """
    candidates: list[dict] = []

    # DTE threshold for the ITM/short-DTE expiration cards — a trading rule.
    short_dte_max = rules.management.expiration_warning_days

    schwab = status.get("schwab", {}) or {}
    cache = status.get("cache", {}) or {}

    schwab_card = _schwab_disconnected_action(schwab)
    if schwab_card is not None:
        candidates.append(schwab_card)

    cache_card = _cache_very_stale_action(cache)
    if cache_card is not None:
        candidates.append(cache_card)

    # Token-expiring is only meaningful when Schwab is otherwise healthy —
    # the builder short-circuits the disconnected case.
    token_card = _schwab_token_expiring_action(schwab, now=now)
    if token_card is not None:
        candidates.append(token_card)

    loser_card = _largest_loser_action(
        positions, rules.risk.loss_review_threshold_pct
    )
    if loser_card is not None:
        candidates.append(loser_card)

    candidates.extend(_itm_short_dte_actions(open_legs, short_dte_max))
    candidates.extend(_short_dte_aggregate_actions(open_legs, short_dte_max))
    # §R6 rule-monitor leg cards (issue #240). These read each leg's
    # precomputed `verdict` — filtering on the governing rule means a leg
    # already covered by an expiration.* card is skipped, so one leg yields
    # exactly one card across all four families.
    candidates.extend(
        _leg_profit_take_review_actions(
            open_legs,
            rules.management.profit_review_pct,
            rules.management.dte_review_days,
            rules.management.expiration_warning_days,
        )
    )
    candidates.extend(
        _leg_dte_review_actions(open_legs, rules.management.dte_review_days)
    )
    candidates.extend(_cc_candidate_actions(positions, open_legs))

    no_legs_card = _no_open_legs_action(kpis)
    if no_legs_card is not None:
        candidates.append(no_legs_card)

    candidates.sort(key=_sort_key_for)
    return [_strip_internal_keys(card) for card in candidates[:MAX_ACTIONS]]
