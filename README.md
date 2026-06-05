# KIRITO

KIRITO currently runs only the BTC 5m live strategy by default:

- BTC 5m: first-reversal signal strategy. When the latest 5m candle is the first different color after two same-color 5m candles, the bot buys the same side as that reversal candle in the next 5m window and continues only after losses.

The BTC 15m engine is still in the codebase for future multi-window use, but it is disabled unless `KIRITO_ENABLED_WINDOWS=5,15` is set.

Default sizing: fixed dollar progression controlled by config, using USDC-sized FAK buys and stopping after 4 cycle orders by default.

The 5m live config also preserves cycle win streaks: after each winning cycle,
the next cycle's first order grows by `KIRITO_CYCLE_WIN_BASE_GROWTH`, capped by
`KIRITO_CYCLE_WIN_BASE_CAP_USDC`. A full 4-order cycle loss resets the base to
`KIRITO_BASE_STAKE_USDC` and skips `KIRITO_SKIP_SIGNALS_AFTER_CYCLE_LOSS` new
signals only when the prior clean win streak was greater than
`KIRITO_SKIP_AFTER_LOSS_MIN_WIN_STREAK`. Current tuned values are `1.15`, `$8`,
`3`, and `10` respectively. `KIRITO_RESET_WIN_STREAK_ON_ANY_LOSS=true` means a
cycle that recovers on step 2-4 still resets the next cycle's base to `$1`.

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
KIRITO_MULTIPLIER=2.5
KIRITO_MAX_CYCLE_STEPS=4
KIRITO_CYCLE_WIN_BASE_GROWTH=1.15
KIRITO_CYCLE_WIN_BASE_CAP_USDC=8
KIRITO_SKIP_SIGNALS_AFTER_CYCLE_LOSS=3
KIRITO_SKIP_AFTER_LOSS_MIN_WIN_STREAK=10
KIRITO_RESET_WIN_STREAK_ON_ANY_LOSS=false
KIRITO_ORDER_MODE=fak_usdc
KIRITO_PRICE_PAD=0.01
KIRITO_PRE_ENTRY_SECONDS=20
KIRITO_LIMIT_ORDER_MIN_USDC=3
KIRITO_MIN_SHARES=5
KIRITO_FAK_BALANCE_THRESHOLD=250
KIRITO_FAK_MIN_USDC=1
KIRITO_SHARE_ROUND_DP=1
KIRITO_STATE_PATH=/app/data/kirito_state.json
```

At runtime, `KIRITO_STATE_PATH` is used only as the base path. The process creates separate files beside it:

- `/app/data/kirito_5m_state.json`
- `/app/data/kirito_15m_state.json` if `KIRITO_ENABLED_WINDOWS` includes `15`

With `KIRITO_ORDER_MODE=fak_usdc`, entries up to `KIRITO_LIMIT_ORDER_MIN_USDC` are sent as USDC-sized FAK market buys, with spend rounded to 1 decimal USD. Entries above `KIRITO_LIMIT_ORDER_MIN_USDC` are sent as marketable limit buys at best ask plus `KIRITO_PRICE_PAD`; limit-order shares are rounded to 1 decimal and never below `KIRITO_MIN_SHARES`. The first cycle order is `KIRITO_BASE_STAKE_USDC`, each loss multiplies the next order by `KIRITO_MULTIPLIER`, and `KIRITO_MAX_CYCLE_STEPS` stops the cycle after that many orders.

When the 5m win-streak base sizing is enabled, the first cycle order is
`min(KIRITO_CYCLE_WIN_BASE_CAP_USDC, KIRITO_BASE_STAKE_USDC *
KIRITO_CYCLE_WIN_BASE_GROWTH^cycle_win_streak)`. The cycle win streak persists
in the state file and increments after a clean winning cycle. With
`KIRITO_RESET_WIN_STREAK_ON_ANY_LOSS=false`, recovered cycles keep the win
streak. A full cycle loss resets the streak and can skip new signals when the
previous streak was greater than `KIRITO_SKIP_AFTER_LOSS_MIN_WIN_STREAK`.

The 5m signal engine evaluates the forming Binance candle only during the final `KIRITO_PRE_ENTRY_SECONDS` before close, so it can buy the next Polymarket window before that window starts. If an active cycle is losing during that same near-close window, the next martingale step is prearmed for the next window.

Current 5m rule: `first_diff_after_same2`. If the previous two 5m candles are the same side and the current signal candle flips, the next window is bought in the flipped signal direction. Example: `DOWN, DOWN, UP` means buy `UP` in the next BTC 5m window.

If `KIRITO_ORDER_MODE=limit_shares`, balances below `KIRITO_FAK_BALANCE_THRESHOLD` still use USDC-sized FAK buys; balances at or above the threshold use marketable limit buys with `best ask + KIRITO_PRICE_PAD`, capped at `$0.99`, shares rounded to 1 decimal, and never below `KIRITO_MIN_SHARES`.

The bot stores cycle/order state in `KIRITO_STATE_PATH`, so restarts should not duplicate the same active setup.
