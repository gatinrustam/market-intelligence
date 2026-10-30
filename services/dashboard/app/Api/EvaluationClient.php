<?php

namespace App\Api;

class EvaluationClient extends ApiClient
{
    protected string $service = 'evaluation';

    public function forEvent(string $id): array
    {
        $result = $this->get('/events/'.rawurlencode($id).'/evaluations', ['origin' => 'all', 'limit' => 100], list: true);
        if ($result['ok']) {
            foreach ($result['data'] as $evaluation) {
                if (! is_string($evaluation['evaluation_id'] ?? null) || ! is_array($evaluation['results'] ?? null) || ! is_array($evaluation['provenance'] ?? null)) {
                    return [...$result, 'ok' => false, 'data' => [], 'error' => 'Malformed evaluation response'];
                }
                if (array_column($evaluation['results'], 'horizon_seconds') !== [60, 300, 900, 3600]) {
                    return [...$result, 'ok' => false, 'data' => [], 'error' => 'Malformed evaluation horizons'];
                }
            }
        }

        return $result;
    }

    public function metrics(string $group, string $origin): array
    {
        return $this->get('/metrics', ['group_by' => $group, 'origin' => $origin], required: ['rows']);
    }
}
