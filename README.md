# KIRITO

KIRITO runs two Polymarket BTC live strategies in the same Docker process:

- BTC 5m: current 3-same early-entry strategy with the next window prearmed after confirmation.
- BTC 15m: after 2 same resolved windows, buy the opposite side in window 3; no advance/prearmed orders; after a loss, buy the same bet side in the next 15m window only after the previous window resolves.

Current sizing: fixed dollar martingale progression `$1, $2, $4, $8, $16...` using USDC-sized FAK buys.

Selected BTC 15m Chainlink/PM-resolution backtest with `$1000` start balance, `52c` FAK fill assumption, and `2_same_cancel`: 3,293 trades, 52.23% WR, ending balance `$1,735.23`, PnL `+$735.23`, max drawdown `-$256.31`, max stake `$256`, no ruin in the local PM dataset.

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
KIRITO_WINDOW_MINUTES=15
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

At runtime, `KIRITO_STATE_PATH` is used only as the base path. The process creates separate files beside it:

- `/app/data/kirito_5m_state.json`
- `/app/data/kirito_15m_state.json`

With `KIRITO_ORDER_MODE=fak_usdc`, every KIRITO entry is sent as a USDC-sized FAK market buy. The first cycle order is `KIRITO_BASE_STAKE_USDC`, and each loss multiplies the next order by `KIRITO_MULTIPLIER`.

If `KIRITO_ORDER_MODE=limit_shares`, balances below `KIRITO_FAK_BALANCE_THRESHOLD` still use USDC-sized FAK buys; balances at or above the threshold use marketable limit buys with `best ask + KIRITO_PRICE_PAD`, capped at `$0.99`, shares rounded by `KIRITO_SHARE_ROUND_DP`, and never below `KIRITO_MIN_SHARES`.

The bot stores cycle/order state in `KIRITO_STATE_PATH`, so restarts should not duplicate the same active setup.
