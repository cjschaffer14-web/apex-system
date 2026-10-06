# External verification notes (for implementation review)

These notes were independently checked against current official/public documentation on 2026-10-03 and are included to prevent hard-coding stale assumptions.

1. Federal Reserve H.4.1 data are generally released Thursday at 4:30 p.m. Eastern. Historical release calendars should still be used to handle holidays and exceptional release dates.
2. Binance perpetual funding is **not safe to model as universally 8-hour**. Binance documentation/announcements show funding intervals can vary and have changed; therefore the engine should use actual funding-event timestamps/interval metadata.
3. Maintenance-margin rates are tiered by product/notional and can change. Do not use one universal MMR constant.

Implementation rule: external schedules belong in versioned data/config tables with provenance, not as timeless constants in strategy code.
