<?php

namespace App\Api;

class MarketDataClient extends ApiClient
{
    protected string $service = 'market-data';

    public function snapshot(string $at): array
    {
        return $this->get('/market/snapshot', ['at' => $at, 'mode' => 'causal', 'symbol' => 'BTCUSDT'], ['realtime', 'candle_1m']);
    }
}
