<?php

namespace App\Api;

class MarketContextClient extends ApiClient
{
    protected string $service = 'market-context';

    private function validPoints(mixed $points, bool $decision): bool
    {
        if (! is_array($points) || ! array_is_list($points)) {
            return false;
        }
        $keys = ['offset_seconds', 'target_at', 'available', 'price', 'price_at', 'status', 'reason', 'resolution', 'bid', 'ask', 'spread_bps', 'return_pct_from_anchor'];
        if ($decision) {
            $keys = array_merge($keys, ['age_seconds', 'max_age_seconds']);
        }
        foreach ($points as $p) {
            if (! is_array($p)) {
                return false;
            }foreach ($keys as $k) {
                if (! array_key_exists($k, $p)) {
                    return false;
                }
            }if (! is_int($p['offset_seconds']) || ! is_bool($p['available'])) {
                return false;
            }
        }

        return ! $decision || array_column($points, 'offset_seconds') === [-900, -300, 0];
    }

    public function contexts(string $id): array
    {
        $r = $this->get('/events/'.rawurlencode($id).'/contexts', ['limit' => 100], list: true);
        if ($r['ok']) {
            foreach ($r['data'] as $p) {
                if (! is_string($p['context_id'] ?? null) || ! $this->validPoints($p['points'] ?? null, false)) {
                    return [...$r, 'ok' => false, 'data' => [], 'error' => 'Malformed context response'];
                }
            }
        }

        return $r;
    }

    public function decision(string $id, string $basis): array
    {
        $r = $this->get('/contexts/'.rawurlencode($id).'/decision', ['basis' => $basis], ['decision_at', 'decision_basis', 'historical_simulation', 'points', 'decision_ready']);
        if ($r['ok'] && (! $this->validPoints($r['data']['points'], true) || ($r['data']['decision_mode'] ?? null) !== $basis || $r['data']['historical_simulation'] !== ($basis === 'research_hypothetical'))) {
            return [...$r, 'ok' => false, 'data' => [], 'error' => 'Malformed or mismatched decision response'];
        }

        return $r;
    }
}
