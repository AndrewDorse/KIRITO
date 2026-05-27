# KIRITO

KIRITO is a Polymarket BTC 5m live bot for the selected backtest variant:

- after 3 same resolved BTC 5m windows, buy the opposite side in window 5;
- if window 4 confirms the same streak, pre-arm window 6;
- after each loss, promote the already-open next window and pre-arm one more;
- after a win, keep/abandon the already-open next-window position and end the cycle.

Current sizing: fixed dollar martingale progression `$1, $2, $4, $8, $16...` using USDC-sized FAK buys.

Latest comparable backtest with `$1000` start balance, `52c` FAK fill assumption, and `abandon_prearmed_on_win`: 3,599 trades, 51.13% WR, ending balance `$2,248.08`, PnL `+$1,248.08`, max drawdown `-$228.92`, max stake `$256`, no ruin in the local PM dataset.

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
KIRITO_BASE_STAKE_USDC=1
KIRITO_MULTIPLIER=2.0
KIRITO_ORDER_MODE=fak_usdc
KIRITO_PRICE_PAD=0.02
KIRITO_MIN_SHARES=5
KIRITO_FAK_BALANCE_THRESHOLD=250
KIRITO_FAK_MIN_USDC=1
KIRITO_SHARE_ROUND_DP=1
KIRITO_STATE_PATH=/app/data/kirito_state.json
```

With `KIRITO_ORDER_MODE=fak_usdc`, every KIRITO entry is sent as a USDC-sized FAK market buy. The first cycle order is `KIRITO_BASE_STAKE_USDC`, and each loss multiplies the next pre-armed order by `KIRITO_MULTIPLIER`.

If `KIRITO_ORDER_MODE=limit_shares`, balances below `KIRITO_FAK_BALANCE_THRESHOLD` still use USDC-sized FAK buys; balances at or above the threshold use marketable limit buys with `best ask + KIRITO_PRICE_PAD`, capped at `$0.99`, shares rounded by `KIRITO_SHARE_ROUND_DP`, and never below `KIRITO_MIN_SHARES`.

The bot stores cycle/order state in `KIRITO_STATE_PATH`, so restarts should not duplicate the same active setup.
