# KIRITO

KIRITO is a Polymarket BTC 5m live bot for the selected backtest variant:

- after 3 same resolved BTC 5m windows, buy the opposite side in window 5;
- if window 4 confirms the same streak, pre-arm window 6;
- after each loss, promote the already-open next window and pre-arm one more;
- after a win, keep/abandon the already-open next-window position and end the cycle.

Backtest selected: `abandon_prearmed_on_win`, 3,560 trades, 51.15% WR, ending balance `$6,052.39` from `$100`, max drawdown `-$1,587.56`, max stake `$1,759.28`, no ruin in the local 90-day PM dataset.

## Run

```powershell
copy .env.example .env
docker compose up --build
```

Set real wallet values in `.env`, then switch `POLY_DRY_RUN=false` for live trading.

## Important Env

```env
BOT_STRATEGY_MODE=kirito_early4
KIRITO_SYMBOL=BTC
KIRITO_WINDOW_MINUTES=5
KIRITO_BASE_PCT=0.01
KIRITO_BASE_MAX_USDC=20
KIRITO_MULTIPLIER=2.0
KIRITO_PRICE_PAD=0.02
KIRITO_MIN_SHARES=5
KIRITO_FAK_BALANCE_THRESHOLD=250
KIRITO_FAK_MIN_USDC=1
KIRITO_SHARE_ROUND_DP=1
KIRITO_STATE_PATH=/app/data/kirito_state.json
```

When wallet balance is below `KIRITO_FAK_BALANCE_THRESHOLD`, orders are USDC-sized FAK buys with at least `KIRITO_FAK_MIN_USDC`. At or above the threshold, orders use marketable limit buys with `best ask + KIRITO_PRICE_PAD`, capped at `$0.99`; shares are rounded to one decimal and never below 5 shares.

The bot stores cycle/order state in `KIRITO_STATE_PATH`, so restarts should not duplicate the same active setup.
