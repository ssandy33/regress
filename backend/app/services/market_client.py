"""Market-data provider seam for QA-gated deterministic stub pricing (issue #349).

The dashboard and BTC-detail services need live quotes, option mids, and deltas
to compute assignment-risk depth (#318) and the buy-to-close decision panel
(#319). QA has no Schwab feed, so those surfaces collapse to their degraded
states there — which means the v1.7 acceptance criteria cannot be validated on
QA before promoting to prod.

This module introduces a thin provider seam: :func:`get_market_client` returns
the real :class:`app.services.schwab_client.SchwabClient` when
``settings.pricing_mode == "live"`` (the default, and the only value prod ever
runs with), or a :class:`StubSchwabClient` reading deterministic values from the
``quote_stubs`` / ``option_mark_stubs`` tables when ``pricing_mode == "stub"``.

**Prod-safety invariant:** prod compose never sets ``PRICING_MODE``, so
``settings.pricing_mode`` stays ``"live"`` and :class:`StubSchwabClient` is never
constructed on production. The stub path is unreachable on prod by configuration,
not by a runtime check — the seam simply hands back the real client.

The stub client returns Schwab-shaped dicts: ``get_quote`` mirrors
:meth:`SchwabClient.get_quote` (a ``quote``-node dict with ``lastPrice``), and
``get_option_chain`` mirrors :meth:`SchwabClient.get_option_chain` (nested
``callExpDateMap`` / ``putExpDateMap`` with ``mark`` / ``delta`` / ``strikePrice``
keys). This means every downstream consumer — ``dashboard.py``,
``dashboard_legs.build_option_leg_index``, ``btc_detail.py`` — is unchanged.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.models.database import OptionMarkStub, QuoteStub
from app.services.schwab_client import SchwabClient, SchwabClientError

logger = logging.getLogger(__name__)


class StubSchwabClient:
    """Deterministic, in-DB stand-in for :class:`SchwabClient` (QA only).

    Reads the synthetic ``quote_stubs`` / ``option_mark_stubs`` rows seeded by
    ``seed-qa`` and returns Schwab-shaped dicts so the dashboard / BTC-detail
    code paths run identically to the live feed. Constructed only when
    ``settings.pricing_mode == "stub"`` (never on prod — see module docstring).

    Implements the subset of the :class:`SchwabClient` surface the
    dashboard/BTC paths call: :meth:`get_quote` and :meth:`get_option_chain`.
    """

    def __init__(self, db: DBSession) -> None:
        """Bind the stub client to a request-scoped DB session."""
        self._db = db

    def get_quote(self, ticker: str) -> dict:
        """Return a Schwab-shaped quote dict for ``ticker`` from the stub table.

        Mirrors :meth:`SchwabClient.get_quote`: returns a ``quote``-node dict
        carrying ``lastPrice`` / ``mark``. Raises :class:`SchwabClientError`
        when no stub row exists (same contract as the live client's no-data
        case), so the dashboard's per-ticker guard degrades that ticker.
        """
        row = self._db.query(QuoteStub).filter(QuoteStub.ticker == ticker).first()
        if row is None:
            raise SchwabClientError(f"No stub quote for '{ticker}'")
        return {"lastPrice": row.last_price, "mark": row.last_price}

    def get_option_chain(
        self,
        ticker: str,
        contract_type: str = "ALL",
        from_date: str | None = None,
        to_date: str | None = None,
        strike_count: int | None = None,
    ) -> dict:
        """Return a Schwab-shaped option chain dict from the stub marks table.

        Reassembles ``option_mark_stubs`` rows into the nested
        ``callExpDateMap`` / ``putExpDateMap`` structure that
        :func:`app.services.dashboard_legs.build_option_leg_index` parses. The
        ``contract_type`` / ``*_date`` / ``strike_count`` args are accepted for
        signature parity with the live client and ignored — the stub returns
        every seeded leg for the ticker.

        Returns a valid chain with **empty** maps when the ticker has no seeded
        marks (the "no live option mark" archetype). A real Schwab chain for a
        tradable ticker still returns a payload — the specific illiquid strike
        is simply absent — so the leg degrades to ``current_mid=None`` and the
        BTC panel renders its ``"—"`` sentinel rather than 500-ing the page.
        """
        rows = (
            self._db.query(OptionMarkStub)
            .filter(OptionMarkStub.ticker == ticker)
            .all()
        )
        call_map: dict[str, dict] = {}
        put_map: dict[str, dict] = {}
        for row in rows:
            target = call_map if row.option_type == "call" else put_map
            # Schwab keys expirations as "YYYY-MM-DD:DTE"; build_option_leg_index
            # only reads the date prefix, so a ":0" DTE suffix is a harmless,
            # parser-compatible filler.
            exp_key = f"{row.expiration}:0"
            strike_key = f"{row.strike:.1f}"
            contract: dict = {
                "strikePrice": row.strike,
                "mark": row.mid,
                "bid": row.mid,
                "ask": row.mid,
            }
            if row.delta is not None:
                contract["delta"] = row.delta
            target.setdefault(exp_key, {})[strike_key] = [contract]

        return {
            "symbol": ticker,
            "callExpDateMap": call_map,
            "putExpDateMap": put_map,
        }


def get_market_client(db: DBSession) -> SchwabClient | StubSchwabClient:
    """Return the live or stub market-data client based on ``pricing_mode``.

    ``settings.pricing_mode == "stub"`` yields a :class:`StubSchwabClient`
    bound to ``db`` (QA only); any other value (including the prod default
    ``"live"``) yields the real :class:`SchwabClient`. ``db`` is accepted
    unconditionally so call sites are uniform; the live client ignores it.
    """
    if settings.pricing_mode == "stub":
        logger.info(
            "market_client.select",
            extra={"event": "market_client.select", "outcome": "success"},
        )
        return StubSchwabClient(db)
    return SchwabClient()


__all__ = ["StubSchwabClient", "get_market_client"]
