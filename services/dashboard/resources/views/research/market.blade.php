<x-research-error :message="$data['error']" />
<x-filament::section heading="BTCUSDT · Binance spot">
<x-research-fields :fields="[
'Last price'=>data_get($data,'realtime.last_trade_price'),'Bid'=>data_get($data,'realtime.best_bid'),'Ask'=>data_get($data,'realtime.best_ask'),
'Spread · bps'=>data_get($data,'realtime.spread_bps'),'Provider connected'=>data_get($data,'stats.provider_connected'),
'Last snapshot'=>\App\Research\Display::utc(data_get($data,'stats.last_snapshot_at')),'Last candle'=>\App\Research\Display::utc(data_get($data,'stats.last_candle_at')),
'Last market update'=>\App\Research\Display::utc(data_get($data,'stats.last_market_event_at')),
'Reconnect count'=>data_get($data,'stats.reconnect_count'),'Outbox pending'=>data_get($data,'stats.outbox_pending')
]" />
<p style="margin-top:1rem">Last stored observation; this diagnostics block does not imply a fresh decision-time quote.</p>
</x-filament::section>
