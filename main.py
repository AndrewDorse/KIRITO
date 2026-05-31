#!/usr/bin/env python3
"""KIRITO Docker entrypoint."""

from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import replace
from pathlib import Path


def _configure_logging() -> None:
    """Keep HTTP/SDK quiet. App logger defaults to ERROR; trade events go to stdout."""
    for name in (
        "urllib3",
        "requests",
        "websocket",
        "websockets",
        "py_clob_client",
        "py_clob_client_v2",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)

    app = logging.getLogger("polymarket_btc_ladder")
    level_name = (os.getenv("BOT_LOG_LEVEL") or "ERROR").strip().upper()
    app.setLevel(getattr(logging, level_name, logging.INFO))
    if not app.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        app.addHandler(handler)
    app.propagate = False

    logging.getLogger().setLevel(logging.WARNING)


def _enabled_kirito_windows() -> set[int]:
    raw = (os.getenv("KIRITO_ENABLED_WINDOWS") or "5").strip()
    enabled: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            window = int(part, 10)
        except ValueError:
            print(f"Config error: invalid KIRITO_ENABLED_WINDOWS segment {part!r}", file=sys.stderr)
            return set()
        if window not in (5, 15):
            print("Config error: KIRITO_ENABLED_WINDOWS supports only 5 and/or 15.", file=sys.stderr)
            return set()
        enabled.add(window)
    return enabled or {5}


def main() -> int:
    _configure_logging()

    from config import BotConfig, BotConfigError
    from kirito_engine import KiritoEngine, STRATEGY_NO_PREARM_15M, STRATEGY_SIGNAL_5M
    from market_locator import GammaMarketLocator
    from trader import PolymarketTrader, wallet_config_hint_for_error

    try:
        config = BotConfig.from_env()
    except BotConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    if config.strategy_mode != "kirito_early4":
        print(
            "KIRITO image expects BOT_STRATEGY_MODE=kirito_early4 "
            f"(got {config.strategy_mode!r}).",
            file=sys.stderr,
        )
        return 2

    if config.dry_run:
        logging.getLogger("polymarket_btc_ladder").error(
            "POLY_DRY_RUN=true: bot will NOT place real orders. "
            "Set POLY_DRY_RUN=false for live trading."
        )

    locator = GammaMarketLocator(config)
    try:
        trader = PolymarketTrader(config)
    except Exception as exc:
        print(f"WALLET_FAIL init: {exc}", file=sys.stderr)
        print(wallet_config_hint_for_error(exc), file=sys.stderr)
        return 2

    if not config.dry_run:
        ok, detail = trader.verify_clob_ready()
        print(f"WALLET_CHECK {'OK' if ok else 'FAIL'} {detail}", flush=True)
        if not ok:
            print(wallet_config_hint_for_error(Exception(detail)), file=sys.stderr)
            return 2

    base_state = Path(config.kirito_state_path)
    enabled_windows = _enabled_kirito_windows()
    if not enabled_windows:
        return 2
    all_engine_specs = [
        (
            5,
            "kirito-5m",
            replace(
                config,
                kirito_window_minutes=5,
                kirito_state_path=str(base_state.with_name("kirito_5m_state.json")),
            ),
            STRATEGY_SIGNAL_5M,
        ),
        (
            15,
            "kirito-15m",
            replace(
                config,
                kirito_window_minutes=15,
                kirito_state_path=str(base_state.with_name("kirito_15m_state.json")),
            ),
            STRATEGY_NO_PREARM_15M,
        ),
    ]
    engine_specs = [spec for spec in all_engine_specs if spec[0] in enabled_windows]
    print(
        "KIRITO_ENABLED_WINDOWS "
        f"{','.join(str(spec[0]) for spec in engine_specs)}",
        flush=True,
    )
    threads: list[threading.Thread] = []
    for _window, name, engine_config, strategy_kind in engine_specs:
        engine = KiritoEngine(
            engine_config,
            GammaMarketLocator(engine_config),
            trader,
            strategy_kind=strategy_kind,
        )
        thread = threading.Thread(target=engine.run, name=name, daemon=False)
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
