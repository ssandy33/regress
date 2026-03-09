import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.models.schemas import (
    MarketContext,
    OptionScanRequest,
    RejectedStrike,
    RuleCompliance,
    StrikeRecommendation,
)
from app.services.schwab_client import SchwabClient, SchwabClientError
from app.services.schwab_auth import SchwabAuthError
from app.services.alpha_vantage_client import get_next_earnings_date
from app.utils.parsing import to_float, to_int

logger = logging.getLogger(__name__)


class OptionScannerError(Exception):
    pass


class OptionScanner:
    """Scans option chains for wheel strategy opportunities (CC and CSP)."""

    def scan(self, request: OptionScanRequest) -> dict:
        """Main entry point: fetch Schwab chain, filter strikes, rank, return."""
        self._validate_request(request)

        today = datetime.now().date()
        from_date = (today + timedelta(days=request.min_dte)).strftime("%Y-%m-%d")
        to_date = (today + timedelta(days=request.max_dte)).strftime("%Y-%m-%d")

        contract_type = "CALL" if request.strategy == "covered_call" else "PUT"

        client = SchwabClient()
        try:
            chain_data = client.get_option_chain(
                request.ticker,
                contract_type=contract_type,
                from_date=from_date,
                to_date=to_date,
            )
        except SchwabAuthError as e:
            logger.error("Schwab auth error scanning '%s': %s", request.ticker, e)
            raise OptionScannerError(
                "Options scanning is unavailable. Please contact your administrator "
                "to configure the Schwab API connection."
            ) from e
        except SchwabClientError as e:
            logger.error("Schwab client error scanning '%s': %s", request.ticker, e)
            raise OptionScannerError(
                f"Failed to fetch option chain for '{request.ticker}'. Please try again later."
            ) from e

        # Extract underlying price from chain response
        underlying = chain_data.get("underlying", {})
        current_price = underlying.get("last", 0) or underlying.get("close", 0)
        if not current_price or current_price <= 0:
            current_price = self._get_current_price_fallback(client, request.ticker)

        fifty_two_week_high = underlying.get("fiftyTwoWeekHigh")
        fifty_two_week_low = underlying.get("fiftyTwoWeekLow")
        daily_volume = underlying.get("totalVolume")

        # Earnings date from Alpha Vantage (Schwab chains don't include this)
        earnings_date = get_next_earnings_date(request.ticker)

        # Market context: VIX from Schwab, 52-week data from underlying quote
        vix = self._get_vix(client)
        market_context = MarketContext(
            vix=vix,
            beta=None,
            fifty_two_week_high=fifty_two_week_high,
            fifty_two_week_low=fifty_two_week_low,
            daily_volume=daily_volume,
        )

        # Parse the expiration date maps
        if request.strategy == "covered_call":
            exp_date_map = chain_data.get("callExpDateMap", {})
        else:
            exp_date_map = chain_data.get("putExpDateMap", {})

        if not exp_date_map:
            return {
                "ticker": request.ticker,
                "current_price": current_price,
                "strategy": request.strategy,
                "scan_time": datetime.now(timezone.utc).isoformat(),
                "earnings_date": earnings_date,
                "iv_rank": None,
                "recommendations": [],
                "rejected": [],
                "market_context": market_context,
            }

        candidates = []
        rejected = []

        valid_exps = set(self._get_valid_expirations(
            exp_date_map, request.min_dte, request.max_dte,
            earnings_date, request.exclude_earnings_dte,
        ))

        for exp_key, strikes_map in exp_date_map.items():
            exp_str = exp_key.split(":")[0]
            if exp_str not in valid_exps:
                continue

            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days

            for strike_str, contracts in strikes_map.items():
                if not contracts:
                    continue
                contract = contracts[0]  # first contract at this strike

                strike = to_float(contract.get("strikePrice", strike_str))
                bid = to_float(contract.get("bid"))
                ask = to_float(contract.get("ask"))
                mid = to_float(contract.get("mark")) or round((bid + ask) / 2, 4)
                oi = to_int(contract.get("openInterest"))
                vol = to_int(contract.get("totalVolume"))
                vol_raw = to_float(contract.get("volatility"), None)
                iv = vol_raw / 100.0 if vol_raw else None

                # Native Schwab Greeks — default None to distinguish missing from zero
                delta = to_float(contract.get("delta"), None)
                gamma = to_float(contract.get("gamma"), None)
                theta = to_float(contract.get("theta"), None)
                vega = to_float(contract.get("vega"), None)

                reasons = self._check_rejection(
                    request, strike, current_price, delta, oi, bid, mid, dte,
                )

                if reasons:
                    rejected.append(RejectedStrike(
                        strike=strike,
                        expiration=exp_str,
                        rejection_reasons=reasons,
                    ))
                    continue

                metrics = self._calculate_metrics(
                    request, strike, current_price, mid, dte,
                )

                if metrics["return_on_capital_pct"] < request.min_return_pct:
                    rejected.append(RejectedStrike(
                        strike=strike,
                        expiration=exp_str,
                        rejection_reasons=[
                            f"return_below_target: {metrics['return_on_capital_pct']:.2f}% < {request.min_return_pct}%"
                        ],
                    ))
                    continue

                if request.max_return_pct and metrics["return_on_capital_pct"] > request.max_return_pct:
                    rejected.append(RejectedStrike(
                        strike=strike,
                        expiration=exp_str,
                        rejection_reasons=[
                            f"return_above_cap: {metrics['return_on_capital_pct']:.2f}% > {request.max_return_pct}%"
                        ],
                    ))
                    continue

                compliance = RuleCompliance(
                    passes_10pct_rule=self._passes_10pct_rule(request, strike),
                    passes_dte_range=request.min_dte <= dte <= request.max_dte,
                    passes_delta_range=(
                        delta is not None and request.min_delta <= abs(delta) <= request.max_delta
                    ),
                    passes_earnings_check=True,
                    passes_return_target=metrics["return_on_capital_pct"] >= request.min_return_pct,
                )

                candidates.append(StrikeRecommendation(
                    rank=0,
                    strike=strike,
                    expiration=exp_str,
                    dte=dte,
                    bid=bid,
                    ask=ask,
                    mid=mid,
                    delta=delta,
                    gamma=gamma,
                    theta=theta,
                    vega=vega,
                    iv=iv,
                    open_interest=oi,
                    volume=vol,
                    premium_per_contract=metrics["premium_per_contract"],
                    total_premium=metrics["total_premium"],
                    return_on_capital_pct=metrics["return_on_capital_pct"],
                    annualized_return_pct=metrics["annualized_return_pct"],
                    distance_from_price_pct=metrics["distance_from_price_pct"],
                    distance_from_basis_pct=metrics.get("distance_from_basis_pct"),
                    max_profit=metrics["max_profit"],
                    breakeven=metrics.get("breakeven"),
                    fifty_pct_profit_target=metrics["fifty_pct_profit_target"],
                    rule_compliance=compliance,
                    greeks_source="market",
                    flags=[],
                ))

        ranked = self._rank_strikes(candidates)

        return {
            "ticker": request.ticker,
            "current_price": current_price,
            "strategy": request.strategy,
            "scan_time": datetime.now(timezone.utc).isoformat(),
            "earnings_date": earnings_date,
            "iv_rank": None,
            "recommendations": ranked[:20],
            "rejected": rejected[:50],
            "market_context": market_context,
        }

    # ---- Validation ----

    def _validate_request(self, req: OptionScanRequest):
        if req.strategy not in ("covered_call", "cash_secured_put"):
            raise ValueError(f"Invalid strategy: {req.strategy}")
        if req.strategy == "covered_call" and not req.cost_basis:
            raise ValueError("cost_basis is required for covered_call strategy")
        if req.strategy == "cash_secured_put" and not req.capital_available:
            raise ValueError("capital_available is required for cash_secured_put strategy")

    # ---- Data fetching ----

    def _get_current_price_fallback(self, client: SchwabClient, symbol: str) -> float:
        last_error = None
        try:
            quote = client.get_quote(symbol)
            price = quote.get("lastPrice")
            if price and price > 0:
                return float(price)
            logger.warning("Quote for '%s' returned invalid price: %s", symbol, price)
        except (SchwabClientError, SchwabAuthError) as e:
            last_error = e
        raise OptionScannerError(f"Cannot get current price for '{symbol}'") from last_error

    def _get_vix(self, client: SchwabClient) -> Optional[float]:
        try:
            vix_quote = client.get_quote("^VIX")
            vix_price = vix_quote.get("lastPrice")
            if vix_price and vix_price > 0:
                return round(float(vix_price), 2)
        except (SchwabClientError, SchwabAuthError):
            pass
        return None

    def _get_valid_expirations(
        self,
        exp_date_map: dict,
        min_dte: int,
        max_dte: int,
        earnings_date: Optional[str],
        exclude_earnings_dte: int,
    ) -> list[str]:
        today = datetime.now().date()
        earnings_dt = (
            datetime.strptime(earnings_date, "%Y-%m-%d").date()
            if earnings_date
            else None
        )

        valid = []
        for exp_key in exp_date_map:
            exp_str = exp_key.split(":")[0]
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days

            if dte < min_dte or dte > max_dte:
                continue

            if earnings_dt and abs((exp_date - earnings_dt).days) <= exclude_earnings_dte:
                continue

            valid.append(exp_str)

        return valid

    # ---- Filtering ----

    def _check_rejection(
        self,
        req: OptionScanRequest,
        strike: float,
        current_price: float,
        delta: Optional[float],
        oi: int,
        bid: float,
        mid: float,
        dte: int,
    ) -> list[str]:
        """Return list of rejection reasons, or empty list if strike passes."""
        reasons = []

        # Strategy-specific strike filter
        if req.strategy == "covered_call":
            min_strike = req.cost_basis * (1 + req.min_call_distance_pct / 100)
            if strike < min_strike:
                distance = ((strike - req.cost_basis) / req.cost_basis) * 100
                reasons.append(
                    f"fails_10pct_rule: strike {distance:.1f}% above basis, "
                    f"requires {req.min_call_distance_pct}%"
                )
        else:  # cash_secured_put
            if strike > current_price:
                reasons.append(
                    f"itm_put: strike ${strike:.2f} > price ${current_price:.2f}"
                )

        # Delta filter
        if delta is not None:
            if abs(delta) < req.min_delta or abs(delta) > req.max_delta:
                reasons.append(
                    f"delta_out_of_range: |{delta:.2f}| not in "
                    f"[{req.min_delta}, {req.max_delta}]"
                )

        # Liquidity filter
        if oi < 50:
            reasons.append(f"low_open_interest: {oi} < 50")
        if bid <= 0:
            reasons.append("zero_bid")

        return reasons

    def _passes_10pct_rule(self, req: OptionScanRequest, strike: float) -> bool:
        if req.strategy != "covered_call" or not req.cost_basis:
            return True
        min_strike = req.cost_basis * (1 + req.min_call_distance_pct / 100)
        return strike >= min_strike

    # ---- Metrics ----

    def _calculate_metrics(
        self,
        req: OptionScanRequest,
        strike: float,
        current_price: float,
        mid: float,
        dte: int,
    ) -> dict:
        if req.strategy == "covered_call":
            shares = req.shares_held or 100
            premium_per_contract = mid * 100
            total_premium = premium_per_contract * (shares / 100)
            capital_at_risk = req.cost_basis * shares
            return_on_capital = (total_premium / capital_at_risk) * 100 if capital_at_risk > 0 else 0
            annualized = return_on_capital * (365 / dte) if dte > 0 else 0
            distance_price = ((strike - current_price) / current_price) * 100
            distance_basis = ((strike - req.cost_basis) / req.cost_basis) * 100
            max_profit = total_premium + ((strike - req.cost_basis) * shares)
            fifty_pct = total_premium * 0.5

            return {
                "premium_per_contract": round(premium_per_contract, 2),
                "total_premium": round(total_premium, 2),
                "return_on_capital_pct": round(return_on_capital, 4),
                "annualized_return_pct": round(annualized, 2),
                "distance_from_price_pct": round(distance_price, 2),
                "distance_from_basis_pct": round(distance_basis, 2),
                "max_profit": round(max_profit, 2),
                "fifty_pct_profit_target": round(fifty_pct, 2),
            }

        else:  # cash_secured_put
            premium_per_contract = mid * 100
            capital_at_risk = strike * 100
            num_contracts = int(req.capital_available / capital_at_risk) if capital_at_risk > 0 else 0
            total_premium = premium_per_contract * max(num_contracts, 1)
            return_on_capital = (premium_per_contract / capital_at_risk) * 100 if capital_at_risk > 0 else 0
            annualized = return_on_capital * (365 / dte) if dte > 0 else 0
            distance_price = ((current_price - strike) / current_price) * 100
            breakeven = strike - mid
            fifty_pct = premium_per_contract * max(num_contracts, 1) * 0.5

            return {
                "premium_per_contract": round(premium_per_contract, 2),
                "total_premium": round(total_premium, 2),
                "return_on_capital_pct": round(return_on_capital, 4),
                "annualized_return_pct": round(annualized, 2),
                "distance_from_price_pct": round(distance_price, 2),
                "max_profit": round(total_premium, 2),
                "breakeven": round(breakeven, 2),
                "fifty_pct_profit_target": round(fifty_pct, 2),
            }

    # ---- Ranking ----

    def _rank_strikes(self, candidates: list[StrikeRecommendation]) -> list[StrikeRecommendation]:
        if not candidates:
            return []

        if len(candidates) == 1:
            candidates[0] = candidates[0].model_copy(update={"rank": 1})
            return candidates

        returns = [c.return_on_capital_pct for c in candidates]
        distances = [c.distance_from_price_pct for c in candidates]
        liquidity = [c.open_interest + c.volume for c in candidates]
        dte_inv = [1 / c.dte if c.dte > 0 else 0 for c in candidates]
        delta_cons = [1 - abs(c.delta) for c in candidates]

        scores = []
        for i in range(len(candidates)):
            score = (
                0.35 * _normalize_val(returns[i], returns)
                + 0.25 * _normalize_val(distances[i], distances)
                + 0.20 * _normalize_val(liquidity[i], liquidity)
                + 0.10 * _normalize_val(dte_inv[i], dte_inv)
                + 0.10 * _normalize_val(delta_cons[i], delta_cons)
            )
            scores.append(score)

        indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        ranked = []
        for rank, (idx, _score) in enumerate(indexed, start=1):
            updated = candidates[idx].model_copy(update={"rank": rank})
            ranked.append(updated)

        return ranked


def _normalize_val(value: float, all_values: list[float]) -> float:
    """Min-max normalize a single value within its dataset."""
    min_v = min(all_values)
    max_v = max(all_values)
    if max_v == min_v:
        return 0.5
    return (value - min_v) / (max_v - min_v)
