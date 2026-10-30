<?php

namespace App\Api;

use Illuminate\Http\Client\Response;
use Illuminate\Support\Facades\Http;

abstract class ApiClient
{
    protected string $service;

    public function get(string $path, array $query = [], array $required = [], bool $list = false): array
    {
        $start = microtime(true);
        try {
            $response = Http::acceptJson()->connectTimeout(1)->timeout(config('upstreams.timeout'))
                ->withoutRedirecting()->get(rtrim(config('upstreams.services.'.$this->service), '/').$path, $query);

            return self::decode($response, $required, $list, $start);
        } catch (\Throwable $e) {
            return self::failure('Service unavailable / timeout', $start);
        }
    }

    public static function failure(string $error, float $start): array
    {
        return ['ok' => false, 'data' => [], 'error' => $error, 'status' => null, 'latency_ms' => round((microtime(true) - $start) * 1000), 'checked_at' => now()->utc()->toIso8601String()];
    }

    public static function decode(mixed $response, array $required, bool $list, float $start): array
    {
        $r = self::failure('Malformed response', $start);
        if (! $response instanceof Response) {
            return self::failure('Service unavailable / timeout', $start);
        }
        $r['status'] = $response->status();
        if (isset($response->handlerStats()['total_time'])) {
            $r['latency_ms'] = round($response->handlerStats()['total_time'] * 1000);
        }
        $data = $response->json();
        if (! is_array($data) || ($list && ! array_is_list($data))) {
            return $r;
        }
        if (! $response->successful()) {
            return [...$r, 'data' => $data, 'error' => 'HTTP '.$response->status()];
        }
        if ($list && ! collect($data)->every(fn ($v) => is_array($v))) {
            return $r;
        }
        foreach ($required as $key) {
            if (! array_key_exists($key, $data)) {
                return $r;
            }
            $type = match ($key) {
                'status','analysis_id','analysis_status','document_id','decision_at','decision_basis' => 'string','decision_ready','historical_simulation' => 'boolean','total' => 'integer',default => 'array'
            };
            if (gettype($data[$key]) !== $type) {
                return $r;
            }
        }

        return [...$r, 'ok' => true, 'data' => $data, 'error' => null];
    }

    public function catalogue(string $path): array
    {
        $items = [];
        $cap = config('upstreams.catalogue_limit');
        for ($offset = 0; $offset < $cap; $offset += 100) {
            $result = $this->get($path, ['offset' => $offset, 'limit' => 100], ['items', 'total']);
            if (! $result['ok'] || ! is_array($result['data']['items']) || ! array_is_list($result['data']['items']) || ! is_int($result['data']['total'])) {
                return [...$result, 'ok' => false, 'data' => [], 'error' => $result['error'] ?? 'Malformed catalogue'];
            }
            $items = array_merge($items, $result['data']['items']);
            $total = $result['data']['total'];
            if (count($items) >= $total || ! $result['data']['items']) {
                return [...$result, 'data' => $items, 'truncated' => false];
            }
        }

        return [...$result, 'data' => $items, 'truncated' => true];
    }

    public function stats(): array
    {
        return $this->get('/stats');
    }
}
