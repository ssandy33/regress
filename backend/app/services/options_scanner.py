import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import yfinance as yf

from app.models.schemas import (
    MarketContext,
    OptionScanRequest,
    RejectedStrike,
    RuleCompliance,
    StrikeRecommendation,
)

logger = logging.getLogger(__name__)


def _safe_float(val, default=0.0) -> float:
    """Convert to float, treating NaN/None as default."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if math.isnan(f) else f
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=0) -> int:
    """Convert to int, treating NaN/None as default."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if math.isnan(f) else int(f)
    except (ValueError, TypeError):
        return default


class OptionScannerError(Exception):
    pass


class OptionScanner:
    """Scans option chains for wheel strategy opportunities (CC and CSP)."""

    def scan(self, request: OptionScanRequest) -> dict:
        """Main entry point: fetch market data, filter strikes, rank, return."""
        self._validate_request(request)

        ticker_obj = yf.Ticker(request.ticker)

        current_price = self._get_current_price(ticker_obj, request.ticker)
        earnings_date = self._get_earnings_date(ticker_obj)
        market_context = self._get_market_context(ticker_obj)

        # Get expirations within DTE range, excluding earnings buffer
        valid_expirations = self._get_valid_expirations(
            ticker_obj,
            request.min_dte,
            request.max_dte,
            earnings_date,
            request.exclude_earnings_dte,
        )

        if not valid_expirations:
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

        # Process each expiration
        candidates = []
        rejected = []

        for exp_str in valid_expirations:
            try:
                chain = ticker_obj.option_chain(exp_str)
            except Exception as e:
                logger.warning(f"Failed to fetch chain for {request.ticker} {exp_str}: {e}")
                continue

            options_df = chain.calls if request.strategy == "covered_call" else chain.puts

            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - datetime.now().date()).days

            for _, row in options_df.iterrows():
                strike = float(row["strike"])
                bid = _safe_float(row.get("bid"))
                ask = _safe_float(row.get("ask"))
                mid = round((bid + ask) / 2, 4)
                delta = _safe_float(row.get("delta")) if "delta" in row.index else None
                oi = _safe_int(row.get("openInterest"))
                vol = _safe_int(row.get("volume"))
                iv = _safe_float(row.get("impliedVolatility"))

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

                # Calculate metrics
                metrics = self._calculate_metrics(
                    request, strike, current_price, mid, dte,
                )

                # Check return target after calculation
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

                flags = []
                if delta is None:
                    flags.append("missing_greeks")

                compliance = RuleCompliance(
                    passes_10pct_rule=self._passes_10pct_rule(request, strike),
                    passes_dte_range=request.min_dte <= dte <= request.max_dte,
                    passes_delta_range=(
                        delta is None
                        or request.min_delta <= abs(delta) <= request.max_delta
                    ),
                    passes_earnings_check=True,  # already filtered at expiration level
                    passes_return_target=metrics["return_on_capital_pct"] >= request.min_return_pct,
                )

                gamma = _safe_float(row.get("gamma")) if "gamma" in row.index else None
                theta = _safe_float(row.get("theta")) if "theta" in row.index else None
                vega = _safe_float(row.get("vega")) if "vega" in row.index else None

                candidates.append(StrikeRecommendation(
                    rank=0,  # set during ranking
                    strike=strike,
                    expiration=exp_str,
                    dte=dte,
                    bid=bid,
                    ask=ask,
                    mid=mid,
                    delta=delta if delta is not None else 0.0,
                    gamma=gamma,
                    theta=theta,
                    vega=vega,
                    iv=iv if iv else None,
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
                    flags=flags,
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

    def _get_current_price(self, ticker_obj, symbol: str) -> float:
        # Try fast_info first (lightweight, avoids rate limits)
        try:
            fi = ticker_obj.fast_info
            price = getattr(fi, "last_price", None) or getattr(fi, "previous_close", None)
            if price and price > 0:
                return float(price)
            logger.debug(f"{symbol}: fast_info returned no valid price")
        except Exception as e:
            logger.warning(f"{symbol}: fast_info failed: {e}")

        try:
            hist = ticker_obj.history(period="5d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
            logger.debug(f"{symbol}: history(5d) returned empty")
        except Exception as e:
            logger.warning(f"{symbol}: history failed: {e}")

        try:
            info = ticker_obj.info
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            if price:
                return float(price)
            logger.debug(f"{symbol}: info returned no price keys")
        except Exception as e:
            logger.warning(f"{symbol}: info failed: {e}")

        raise OptionScannerError(f"Cannot get current price for '{symbol}'")

    def _get_earnings_date(self, ticker_obj) -> Optional[str]:
        try:
            cal = ticker_obj.calendar
            if cal is not None:
                if hasattr(cal, "get"):
                    ed = cal.get("Earnings Date")
                    if ed and len(ed) > 0:
                        return ed[0].strftime("%Y-%m-%d") if hasattr(ed[0], "strftime") else str(ed[0])
                elif hasattr(cal, "iloc"):
                    return cal.iloc[0, 0].strftime("%Y-%m-%d")
        except Exception:
            pass

        try:
            ed = ticker_obj.get_earnings_dates(limit=4)
            if ed is not None and not ed.empty:
                future = ed.index[ed.index >= datetime.now()]
                if len(future) > 0:
                    return future[0].strftime("%Y-%m-%d")
        except Exception:
            pass

        return None

    def _get_market_context(self, ticker_obj) -> MarketContext:
        vix = None
        try:
            vix_ticker = yf.Ticker("^VIX")
            fi = vix_ticker.fast_info
            vix_price = getattr(fi, "last_price", None) or getattr(fi, "previous_close", None)
            if vix_price and vix_price > 0:
                vix = round(float(vix_price), 2)
        except Exception:
            pass

        try:
            fi = ticker_obj.fast_info
            return MarketContext(
                vix=vix,
                beta=None,  # not available in fast_info
                fifty_two_week_high=getattr(fi, "year_high", None),
                fifty_two_week_low=getattr(fi, "year_low", None),
                avg_volume=None,
            )
        except Exception:
            pass

        try:
            info = ticker_obj.info
            return MarketContext(
                vix=vix,
                beta=info.get("beta"),
                fifty_two_week_high=info.get("fiftyTwoWeekHigh"),
                fifty_two_week_low=info.get("fiftyTwoWeekLow"),
                avg_volume=info.get("averageDailyVolume10Day") or info.get("averageVolume"),
            )
        except Exception as e:
            logger.warning(f"Failed to get market context: {e}")
            return MarketContext(vix=vix)

    def _get_valid_expirations(
        self,
        ticker_obj,
        min_dte: int,
        max_dte: int,
        earnings_date: Optional[str],
        exclude_earnings_dte: int,
    ) -> list[str]:
        try:
            all_exps = ticker_obj.options
        except Exception:
            raise OptionScannerError(
                f"No options available for '{ticker_obj.ticker}'"
            )

        if not all_exps:
            raise OptionScannerError(
                f"No options available for '{ticker_obj.ticker}'"
            )

        today = datetime.now().date()
        earnings_dt = (
            datetime.strptime(earnings_date, "%Y-%m-%d").date()
            if earnings_date
            else None
        )

        valid = []
        for exp_str in all_exps:
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

        # Delta filter (skip if missing)
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
