<?php

namespace App\Research;

use App\Api\ApiClient;
use Illuminate\Http\Client\Pool;
use Illuminate\Support\Arr;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Http;

class Health
{
    public function all(): array
    {
        return Cache::remember('upstream-health', config('upstreams.cache_seconds'), function () {
            $start = microtime(true);
            $urls = config('upstreams.services');
            try {
                $responses = Http::pool(function (Pool $pool) use ($urls) {
                    $requests = [];
                    foreach ($urls as $name => $url) {
                        foreach (['health', 'ready'] as $path) {
                            $requests[] = $pool->as($name.'/'.$path)->acceptJson()->connectTimeout(1)->timeout(config('upstreams.timeout'))->withoutRedirecting()->get($url.'/'.$path);
                        }
                    }

                    return $requests;
                });
            } catch (\Throwable $e) {
                $responses = [];
            }
            $rows = [];
            foreach ($urls as $name => $url) {
                $health = ApiClient::decode($responses[$name.'/health'] ?? null, ['status'], false, $start);
                $ready = ApiClient::decode($responses[$name.'/ready'] ?? null, [], false, $start);
                $flags = Arr::flatten($ready['data']);
                $validReady = $ready['ok'] && count($flags) > 0 && collect($flags)->every(fn ($v) => $v === true);
                $rows[] = ['service' => $name, 'url' => $url, 'status' => ! $health['ok'] ? 'unavailable' : ($validReady ? 'healthy' : 'degraded'),
                    'health' => $health['ok'] ? 'healthy' : $health['error'], 'ready' => $validReady ? 'ready' : ($ready['error'] ?? 'not ready'),
                    'latency_ms' => max($health['latency_ms'], $ready['latency_ms']), 'checked_at' => $health['checked_at']];
            }

            return $rows;
        });
    }
}
