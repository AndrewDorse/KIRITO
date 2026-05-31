# KIRITO

KIRITO currently runs only the BTC 5m live strategy by default:

- BTC 5m: confirmed-candle signal strategy. When the latest closed 5m candle matches the configured high-WR signal family, the bot buys the opposite side in the next 5m window and continues only after losses.

The BTC 15m engine is still in the codebase for future multi-window use, but it is disabled unless `KIRITO_ENABLED_WINDOWS=5,15` is set.

Default sizing: fixed dollar progression `$1, $2, $4`, using USDC-sized FAK buys and stopping after 3 cycle orders.

Extra in-cycle boost rules are enabled:

- BTC 5m: when placing a new in-cycle/prearmed step, double that step again if the latest resolved candle has `wick >= 1.25x median(wick last20)` and closes near the high/low extreme.
- BTC 15m: when the previous 15m step loses, double the next step again if that previous candle has `lower_wick >= 2.0x mean(lower_wick last50)`.

Both rules use recent closed Binance BTCUSDT candles for fast candle features. If Binance is unavailable, the bot falls back to Gamma/PM resolution and simply skips the extra boost because wick history is missing.

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
KIRITO_ENABLED_WINDOWS=5
KIRITO_WINDOW_MINUTES=15
KIRITO_BASE_STAKE_USDC=1
KIRITO_MULTIPLIER=2.0
KIRITO_MAX_CYCLE_STEPS=3
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
- `/app/data/kirito_15m_state.json` if `KIRITO_ENABLED_WINDOWS` includes `15`

With `KIRITO_ORDER_MODE=fak_usdc`, every KIRITO entry is sent as a USDC-sized FAK market buy. The first cycle order is `KIRITO_BASE_STAKE_USDC`, each loss multiplies the next order by `KIRITO_MULTIPLIER`, and `KIRITO_MAX_CYCLE_STEPS` stops the cycle after that many orders.

If `KIRITO_ORDER_MODE=limit_shares`, balances below `KIRITO_FAK_BALANCE_THRESHOLD` still use USDC-sized FAK buys; balances at or above the threshold use marketable limit buys with `best ask + KIRITO_PRICE_PAD`, capped at `$0.99`, shares rounded by `KIRITO_SHARE_ROUND_DP`, and never below `KIRITO_MIN_SHARES`.

The bot stores cycle/order state in `KIRITO_STATE_PATH`, so restarts should not duplicate the same active setup.
