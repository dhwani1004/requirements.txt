"""
eToro Cost Calculator
Accounts for: spread, overnight swap, weekend triple swap, currency conversion.
All costs reduce your effective take profit and widen breakeven win rate.
"""

ETORO_COSTS = {
    'XAUUSD': {
        'spread_usd':        0.45,   # ~$0.45 typical spread
        'overnight_usd':     1.20,   # per 100 units per night
        'currency_conv_pct': 0.005,
        'min_trade_usd':     10.0,
    },
    'XAGUSD': {
        'spread_usd':        0.05,   # ~$0.05 typical spread (Silver is in $/oz)
        'overnight_usd':     0.45,   # Silver overnight cheaper than Gold
        'currency_conv_pct': 0.005,
        'min_trade_usd':     10.0,
        # Note: Silver is ~60x cheaper than Gold per oz, but more volatile %
        # eToro Silver CFD = 1 unit = 1 oz. Moves are 2-3% intraday normal.
    },
}

EURUSD_RATE = 1.08


def calculate_etoro_costs(symbol, entry_price, stop_loss, take_profit,
                           risk_eur, direction, estimated_hold_hours=24.0):
    costs = ETORO_COSTS.get(symbol, ETORO_COSTS['XAUUSD'])

    raw_stop_dist = abs(entry_price - stop_loss)
    if raw_stop_dist == 0:
        raw_stop_dist = 1.0

    risk_usd = risk_eur * EURUSD_RATE
    units = risk_usd / raw_stop_dist

    spread_cost_usd     = costs['spread_usd']
    nights              = max(1, estimated_hold_hours / 24)
    overnight_cost_usd  = costs['overnight_usd'] * nights * (units / 100)
    conversion_cost_usd = risk_usd * costs['currency_conv_pct']

    total_cost_usd = spread_cost_usd + overnight_cost_usd + conversion_cost_usd
    total_cost_eur = total_cost_usd / EURUSD_RATE

    cost_in_price = total_cost_usd / units if units > 0 else 0

    if direction == 'bullish':
        adjusted_tp = take_profit - cost_in_price
    else:
        adjusted_tp = take_profit + cost_in_price

    real_reward = abs(adjusted_tp - entry_price)
    real_risk   = abs(stop_loss - entry_price) + cost_in_price
    adjusted_rr = round(real_reward / real_risk, 2) if real_risk > 0 else 0
    breakeven   = round(real_risk / (real_risk + real_reward) * 100, 1) if (real_risk + real_reward) > 0 else 50.0

    return {
        'adjusted_tp':        round(adjusted_tp, 4),
        'adjusted_rr':        adjusted_rr,
        'total_cost_usd':     round(total_cost_usd, 2),
        'total_cost_eur':     round(total_cost_eur, 2),
        'breakeven_win_rate': breakeven,
        'cost_breakdown': {
            'spread_usd':     round(spread_cost_usd, 2),
            'overnight_usd':  round(overnight_cost_usd, 2),
            'conversion_usd': round(conversion_cost_usd, 2),
        }
    }


def format_cost_summary(costs):
    bd = costs['cost_breakdown']
    return (
        f"Spread: ${bd['spread_usd']:.2f} | "
        f"Overnight: ${bd['overnight_usd']:.2f} | "
        f"Conv: ${bd['conversion_usd']:.2f}\n"
        f"Total cost: ~\u20ac{costs['total_cost_eur']:.2f} | "
        f"Real R/R: 1:{costs['adjusted_rr']} | "
        f"Breakeven: {costs['breakeven_win_rate']}% wins needed"
    )


class EToroCalculator:
    """Wrapper class — handles both old and new calling conventions."""

    def calculate(self, symbol, entry_price, stop_loss, take_profit,
                  risk_eur=None, direction=None, estimated_hold_hours=24.0,
                  action=None, quantity=None, capital_eur=None):
        # Normalise args — support both old (action=) and new (direction=) style
        if direction is None:
            direction = 'bullish' if (action or 'BUY') == 'BUY' else 'bearish'
        if risk_eur is None:
            risk_eur = (capital_eur or 675) * 0.03
        result = calculate_etoro_costs(symbol, entry_price, stop_loss, take_profit,
                                       risk_eur, direction, estimated_hold_hours)
        result['net_rr'] = result.get('adjusted_rr', 2.0)
        return result

    def format_summary(self, costs):
        return format_cost_summary(costs)
