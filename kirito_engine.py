#!/usr/bin/env python3
"""KIRITO early-entry 4-strike opposite strategy."""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from config import (
    GAMMA_URL,
    LOGGER,
    ActiveContract,
    BotConfig,
    TokenMarket,
    parse_jsonish_list,
)
from market_locator import GammaMarketLocator
from trader import PolymarketTrader


UP = "UP"
DOWN = "DOWN"


def _opposite(side: str) -> str:
    return DOWN if side == UP else UP


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


class KiritoEngine:
    """Pre-armed early-entry 4-strike opposite strategy."""

    def __init__(
        self,
        config: BotConfig,
        locator: GammaMarketLocator,
        trader: PolymarketTrader,
    ) -> None:
        self.config = config
        self.locator = locator
        self.trader = trader
        self.window_seconds = int(config.kirito_window_minutes) * 60
        self.state_path = Path(config.kirito_state_path)
        self.state: dict[str, Any] = self._load_state()

    def run(self) -> None:
        print(
            "INIT KIRITO "
            f"symbol={self.config.kirito_symbol} "
            f"window={self.config.kirito_window_minutes}m "
            f"base=min({self.config.kirito_base_pct:.2%} balance, "
            f"${self.config.kirito_base_max_usdc:.2f}) "
            f"mult={self.config.kirito_multiplier:g} "
            f"dry_run={self.config.dry_run}",
            flush=True,
        )
        while True:
            try:
                self.tick()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                LOGGER.exception("KIRITO tick failed: %s", exc)
                print(f"ERROR KIRITO tick failed: {exc}", flush=True)
            time.sleep(float(self.config.kirito_poll_seconds))

    def tick(self) -> None:
        resolved = self._fetch_recent_resolved_windows()
        resolved_by_start = {int(row["start_ts"]): row for row in resolved}
        self._process_pending_setup(resolved_by_start)
        self._process_active_cycle(resolved_by_start)
        self._maybe_start_cycle(resolved)
        self._save_state()

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._empty_state()
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw.setdefault("orders", {})
                raw.setdefault("cycle_seq", 0)
                raw.setdefault("last_setup_start_ts", 0)
                return raw
        except Exception as exc:
            LOGGER.error("KIRITO state load failed: %s", exc)
        return self._empty_state()

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "cycle_seq": 0,
            "last_setup_start_ts": 0,
            "pending_setup": None,
            "active_cycle": None,
            "orders": {},
            "updated_at": "",
        }

    def _save_state(self) -> None:
        self.state["updated_at"] = _utc_now_iso()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.state_path)

    def _fetch_recent_resolved_windows(self) -> list[dict[str, Any]]:
        fast = self._fetch_recent_binance_windows()
        if fast:
            return fast
        now_ts = int(time.time())
        current_start = (now_ts // self.window_seconds) * self.window_seconds
        out: list[dict[str, Any]] = []
        for i in range(1, int(self.config.kirito_history_windows) + 1):
            start_ts = current_start - i * self.window_seconds
            row = self._resolved_window(start_ts)
            if row is not None:
                out.append(row)
        return sorted(out, key=lambda x: int(x["start_ts"]))

    def _fetch_recent_binance_windows(self) -> list[dict[str, Any]]:
        if self.config.kirito_symbol != "BTC" or self.config.kirito_window_minutes != 5:
            return []
        try:
            response = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    "symbol": "BTCUSDT",
                    "interval": "5m",
                    "limit": max(10, int(self.config.kirito_history_windows) + 3),
                },
                timeout=min(5.0, float(self.config.request_timeout_seconds)),
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            LOGGER.debug("Binance recent BTC 5m fetch failed; falling back to Gamma: %s", exc)
            return []

        now_ms = int(time.time() * 1000)
        rows: list[dict[str, Any]] = []
        for kline in payload:
            try:
                start_ts = int(kline[0]) // 1000
                close_time_ms = int(kline[6])
                open_px = float(kline[1])
                close_px = float(kline[4])
            except (TypeError, ValueError, IndexError):
                continue
            if close_time_ms >= now_ms:
                continue
            winner = UP if close_px >= open_px else DOWN
            rows.append(
                {
                    "start_ts": start_ts,
                    "slug": self._slug(start_ts),
                    "winner": winner,
                    "source": "binance_5m",
                    "open": open_px,
                    "close": close_px,
                }
            )
        return sorted(rows[-int(self.config.kirito_history_windows) :], key=lambda x: int(x["start_ts"]))

    def _resolved_window(self, start_ts: int) -> dict[str, Any] | None:
        slug = self._slug(start_ts)
        market = self._gamma_market_by_slug(slug)
        if not market:
            return None
        winner = self._winner_from_market(market)
        if winner not in (UP, DOWN):
            return None
        return {"start_ts": int(start_ts), "slug": slug, "winner": winner}

    def _gamma_market_by_slug(self, slug: str) -> dict[str, Any] | None:
        try:
            resp = self.locator.session.get(
                f"{GAMMA_URL}/markets",
                params={"slug": slug, "closed": "true"},
                timeout=self.config.request_timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                return data[0]
        except Exception as exc:
            LOGGER.debug("Gamma resolved fetch failed %s: %s", slug, exc)
        return None

    def _winner_from_market(self, market: dict[str, Any]) -> str | None:
        for key in ("winningOutcome", "winner", "resolvedOutcome"):
            value = str(market.get(key) or "").strip().upper()
            if value in (UP, DOWN):
                return value

        metadata = {}
        events = market.get("events") or []
        if events and isinstance(events, list):
            metadata = (events[0] or {}).get("eventMetadata") or {}
        final_px = _float_or_none(
            market.get("finalPrice")
            or market.get("final_price")
            or market.get("resolutionPrice")
            or metadata.get("finalPrice")
        )
        beat_px = _float_or_none(
            market.get("priceToBeat")
            or market.get("price_to_beat")
            or market.get("openPrice")
            or metadata.get("priceToBeat")
        )
        if final_px is not None and beat_px is not None:
            return UP if final_px > beat_px else DOWN

        outcomes = [str(x).strip().upper() for x in parse_jsonish_list(market.get("outcomes"))]
        prices = [_float_or_none(x) for x in parse_jsonish_list(market.get("outcomePrices"))]
        if len(outcomes) >= 2 and len(prices) >= 2:
            valid = [(out, px) for out, px in zip(outcomes, prices) if px is not None]
            if valid:
                best_out, best_px = max(valid, key=lambda x: float(x[1]))
                if best_out in (UP, DOWN) and float(best_px) >= 0.90:
                    return best_out
        return None

    def _process_pending_setup(self, resolved_by_start: dict[int, dict[str, Any]]) -> None:
        pending = self.state.get("pending_setup")
        if not isinstance(pending, dict):
            return
        fourth = resolved_by_start.get(int(pending.get("fourth_start_ts") or 0))
        if not fourth:
            return

        setup_side = str(pending.get("setup_side") or "")
        current_key = str(pending.get("current_key") or "")
        if fourth["winner"] != setup_side:
            self._mark_order_role(current_key, "orphan")
            print(
                "ABANDON_SETUP "
                f"cycle={pending.get('cycle_id')} fourth={fourth['slug']} "
                f"winner={fourth['winner']} expected={setup_side}",
                flush=True,
            )
            self.state["pending_setup"] = None
            return

        active = {
            "cycle_id": int(pending.get("cycle_id") or 0),
            "setup_side": setup_side,
            "current_key": current_key,
            "prearmed_key": None,
        }
        self.state["pending_setup"] = None
        self.state["active_cycle"] = active
        current_order = self.state["orders"].get(current_key) or {}
        next_start = int(current_order.get("start_ts") or 0) + self.window_seconds
        next_stake = float(current_order.get("stake") or 0.0) * float(self.config.kirito_multiplier)
        prearmed_key = self._place_step_order(
            cycle_id=active["cycle_id"],
            start_ts=next_start,
            bet_side=str(current_order.get("bet_side") or _opposite(setup_side)),
            stake=next_stake,
            step=int(current_order.get("step") or 1) + 1,
            role="prearmed",
        )
        if prearmed_key:
            active["prearmed_key"] = prearmed_key
        print(
            "CONFIRM_SETUP "
            f"cycle={active['cycle_id']} fourth={fourth['slug']} "
            f"prearmed={bool(prearmed_key)}",
            flush=True,
        )

    def _process_active_cycle(self, resolved_by_start: dict[int, dict[str, Any]]) -> None:
        while True:
            active = self.state.get("active_cycle")
            if not isinstance(active, dict):
                return
            current_key = str(active.get("current_key") or "")
            current_order = self.state["orders"].get(current_key)
            if not isinstance(current_order, dict):
                self.state["active_cycle"] = None
                return
            resolution = resolved_by_start.get(int(current_order.get("start_ts") or 0))
            if not resolution:
                return

            bet_side = str(current_order.get("bet_side") or "")
            win = resolution["winner"] == bet_side
            current_order["resolved"] = True
            current_order["resolution"] = resolution["winner"]
            current_order["win"] = win
            current_order["resolved_at"] = _utc_now_iso()
            if win:
                prearmed_key = str(active.get("prearmed_key") or "")
                if prearmed_key:
                    self._mark_order_role(prearmed_key, "orphan")
                print(
                    "WIN "
                    f"cycle={active.get('cycle_id')} step={current_order.get('step')} "
                    f"slug={current_order.get('slug')} bet={bet_side} "
                    f"kept_next_orphan={bool(prearmed_key)}",
                    flush=True,
                )
                self.state["active_cycle"] = None
                return

            print(
                "LOSS "
                f"cycle={active.get('cycle_id')} step={current_order.get('step')} "
                f"slug={current_order.get('slug')} bet={bet_side} "
                f"winner={resolution['winner']}",
                flush=True,
            )
            prearmed_key = str(active.get("prearmed_key") or "")
            if prearmed_key and prearmed_key in self.state["orders"]:
                self._mark_order_role(prearmed_key, "current")
                active["current_key"] = prearmed_key
                active["prearmed_key"] = None
                promoted = self.state["orders"][prearmed_key]
            else:
                promoted = None

            if not promoted:
                next_start = int(current_order.get("start_ts") or 0) + self.window_seconds
                next_key = self._place_step_order(
                    cycle_id=int(active.get("cycle_id") or 0),
                    start_ts=next_start,
                    bet_side=bet_side,
                    stake=float(current_order.get("stake") or 0.0) * float(self.config.kirito_multiplier),
                    step=int(current_order.get("step") or 1) + 1,
                    role="current",
                )
                if not next_key:
                    print(f"STOP_CYCLE cycle={active.get('cycle_id')} reason=no_next_order", flush=True)
                    self.state["active_cycle"] = None
                    return
                active["current_key"] = next_key
                promoted = self.state["orders"][next_key]

            prearm_start = int(promoted.get("start_ts") or 0) + self.window_seconds
            prearm_key = self._place_step_order(
                cycle_id=int(active.get("cycle_id") or 0),
                start_ts=prearm_start,
                bet_side=str(promoted.get("bet_side") or bet_side),
                stake=float(promoted.get("stake") or 0.0) * float(self.config.kirito_multiplier),
                step=int(promoted.get("step") or 1) + 1,
                role="prearmed",
            )
            active["prearmed_key"] = prearm_key

    def _maybe_start_cycle(self, resolved: list[dict[str, Any]]) -> None:
        if self.state.get("pending_setup") or self.state.get("active_cycle"):
            return
        last3 = self._last_three_consecutive(resolved)
        if not last3:
            return
        side = str(last3[0]["winner"])
        if any(str(row["winner"]) != side for row in last3):
            return
        setup_end = int(last3[-1]["start_ts"])
        if int(self.state.get("last_setup_start_ts") or 0) == setup_end:
            return

        target_start = setup_end + 2 * self.window_seconds
        cycle_id = int(self.state.get("cycle_seq") or 0) + 1
        stake = self._base_stake()
        current_key = self._place_step_order(
            cycle_id=cycle_id,
            start_ts=target_start,
            bet_side=_opposite(side),
            stake=stake,
            step=1,
            role="current",
        )
        if not current_key:
            return
        self.state["cycle_seq"] = cycle_id
        self.state["last_setup_start_ts"] = setup_end
        self.state["pending_setup"] = {
            "cycle_id": cycle_id,
            "setup_side": side,
            "fourth_start_ts": setup_end + self.window_seconds,
            "current_key": current_key,
            "created_at": _utc_now_iso(),
        }
        print(
            "START_SETUP "
            f"cycle={cycle_id} side={side} bet={_opposite(side)} "
            f"target={self._slug(target_start)} stake=${stake:.2f}",
            flush=True,
        )

    def _last_three_consecutive(self, resolved: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        if len(resolved) < 3:
            return None
        tail = resolved[-3:]
        starts = [int(row["start_ts"]) for row in tail]
        if starts[1] - starts[0] != self.window_seconds:
            return None
        if starts[2] - starts[1] != self.window_seconds:
            return None
        return tail

    def _base_stake(self) -> float:
        balance = 0.0 if self.config.dry_run else self.trader.wallet_balance_usdc()
        if balance <= 0:
            balance = float(self.config.kirito_base_max_usdc)
        return max(
            0.01,
            min(
                balance * float(self.config.kirito_base_pct),
                float(self.config.kirito_base_max_usdc),
            ),
        )

    def _place_step_order(
        self,
        *,
        cycle_id: int,
        start_ts: int,
        bet_side: str,
        stake: float,
        step: int,
        role: str,
    ) -> str | None:
        slug = self._slug(start_ts)
        key = f"{cycle_id}:{step}:{slug}:{bet_side}"
        if key in self.state["orders"]:
            return key
        late_entry = int(time.time()) >= int(start_ts)
        contract = self.locator.get_contract_for_window_start(
            int(self.config.kirito_window_minutes),
            int(start_ts),
            market_symbol=self.config.kirito_symbol,
        )
        if contract is None:
            print(f"SKIP_ORDER cycle={cycle_id} step={step} slug={slug} reason=market_not_active", flush=True)
            return None
        token = contract.up if bet_side == UP else contract.down
        order = self._buy_token(contract, token, bet_side, stake, late_entry=late_entry)
        if not order:
            return None
        order.update(
            {
                "cycle_id": int(cycle_id),
                "step": int(step),
                "role": role,
                "start_ts": int(start_ts),
                "slug": slug,
                "bet_side": bet_side,
                "stake": float(stake),
                "created_at": _utc_now_iso(),
                "resolved": False,
            }
        )
        self.state["orders"][key] = order
        print(
            "ORDER "
            f"cycle={cycle_id} step={step} role={role} slug={slug} "
            f"side={bet_side} stake=${stake:.2f} shares={order.get('shares')} "
            f"limit={order.get('limit_price')}",
            flush=True,
        )
        return key

    def _buy_token(
        self,
        contract: ActiveContract,
        token: TokenMarket,
        side: str,
        stake: float,
        *,
        late_entry: bool = False,
    ) -> dict[str, Any] | None:
        try:
            self.trader.sync_ws_subscriptions([contract])
        except Exception:
            pass
        ask = self.trader.get_best_ask(token.token_id)
        if ask is None or ask <= 0:
            print(f"SKIP_ORDER slug={contract.slug} side={side} reason=no_ask", flush=True)
            return None
        limit_price = 0.55 if late_entry else min(0.99, round(float(ask) + float(self.config.kirito_price_pad), 2))
        try:
            balance = float(self.trader.wallet_balance_usdc()) if not self.config.dry_run else 0.0
        except Exception:
            balance = 0.0
        small_balance_fak = (
            balance > 0
            and balance < float(self.config.kirito_fak_balance_threshold)
        )
        if small_balance_fak:
            return self._buy_token_usdc(
                contract,
                token,
                side,
                max(float(self.config.kirito_fak_min_usdc), float(stake)),
            )

        shares_raw = max(float(self.config.kirito_min_shares), float(stake) / max(limit_price, 0.01))
        shares = round(shares_raw, int(self.config.kirito_share_round_dp))
        if shares <= 0:
            return None
        if self.config.dry_run:
            return {
                "order_id": f"dry-{int(time.time() * 1000)}",
                "status": "dry_run",
                "shares": shares,
                "filled_shares": shares,
                "filled_usdc": round(shares * limit_price, 4),
                "avg_price": limit_price,
                "limit_price": limit_price,
                "best_ask": float(ask),
                "late_entry": late_entry,
            }
        result = self.trader.place_marketable_buy_with_result(
            token,
            limit_price,
            shares,
            confirm_get_order=bool(self.config.polymarket_fak_confirm_get_order),
            requested_usdc=float(stake),
        )
        if not getattr(result, "matched_any", False):
            print(
                f"SKIP_ORDER slug={contract.slug} side={side} reason=no_fill "
                f"status={getattr(result, 'status', '')} error={getattr(result, 'error', '')} "
                f"limit={limit_price:.2f} best_ask={float(ask):.2f} late_entry={late_entry}",
                flush=True,
            )
            return None
        return {
            "order_id": str(getattr(result, "order_id", "")),
            "status": str(getattr(result, "status", "")),
            "shares": shares,
            "filled_shares": float(getattr(result, "filled_shares", 0.0)),
            "filled_usdc": float(getattr(result, "filled_usdc", 0.0)),
            "avg_price": float(getattr(result, "avg_price", 0.0)),
            "limit_price": limit_price,
            "best_ask": float(ask),
            "late_entry": late_entry,
        }

    def _buy_token_usdc(
        self,
        contract: ActiveContract,
        token: TokenMarket,
        side: str,
        usdc: float,
    ) -> dict[str, Any] | None:
        if self.config.dry_run:
            ask = self.trader.get_best_ask(token.token_id) or 0.52
            limit_price = min(0.99, round(float(ask) + float(self.config.kirito_price_pad), 2))
            shares = round(float(usdc) / max(limit_price, 0.01), 4)
            return {
                "order_id": f"dry-usdc-{int(time.time() * 1000)}",
                "status": "dry_run_usdc",
                "shares": shares,
                "filled_shares": shares,
                "filled_usdc": float(usdc),
                "avg_price": limit_price,
                "limit_price": limit_price,
                "best_ask": float(ask),
                "sizing_mode": "fak_usdc",
            }
        result = self.trader.place_market_buy_usdc_with_result(
            token,
            float(usdc),
            confirm_get_order=bool(self.config.polymarket_fak_confirm_get_order),
        )
        if not getattr(result, "matched_any", False):
            print(
                f"SKIP_ORDER slug={contract.slug} side={side} reason=no_fill_usdc "
                f"status={getattr(result, 'status', '')} error={getattr(result, 'error', '')} "
                f"usdc={float(usdc):.2f}",
                flush=True,
            )
            return None
        return {
            "order_id": str(getattr(result, "order_id", "")),
            "status": str(getattr(result, "status", "")),
            "shares": float(getattr(result, "filled_shares", 0.0)),
            "filled_shares": float(getattr(result, "filled_shares", 0.0)),
            "filled_usdc": float(getattr(result, "filled_usdc", 0.0)),
            "avg_price": float(getattr(result, "avg_price", 0.0)),
            "limit_price": float(getattr(result, "avg_price", 0.0)),
            "best_ask": 0.0,
            "sizing_mode": "fak_usdc",
        }

    def _mark_order_role(self, key: str, role: str) -> None:
        if key and key in self.state["orders"]:
            self.state["orders"][key]["role"] = role
            self.state["orders"][key]["role_updated_at"] = _utc_now_iso()

    def _slug(self, start_ts: int) -> str:
        return (
            f"{str(self.config.kirito_symbol).strip().lower()}"
            f"-updown-{int(self.config.kirito_window_minutes)}m-{int(start_ts)}"
        )
