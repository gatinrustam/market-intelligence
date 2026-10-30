<?php

namespace App\Research;

use Carbon\CarbonImmutable;

class Display
{
    public static function utc(mixed $v): string
    {
        try {
            return $v ? CarbonImmutable::parse($v)->utc()->format('Y-m-d H:i:s.v').' UTC' : 'Unavailable';
        } catch (\Throwable $e) {
            return 'Unavailable';
        }
    }

    public static function text(mixed $v): string
    {
        return is_bool($v) ? ($v ? 'true' : 'false') : (is_array($v) ? json_encode($v, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) : ($v === null ? 'Unavailable' : (string) $v));
    }

    public static function color(string $v): string
    {
        return match ($v) {
            'healthy','ready','completed','high','LIVE' => 'success','failed','unavailable' => 'danger','blocked','degraded','partial','stale_market_data','RESEARCH HYPOTHETICAL' => 'warning',default => 'gray'
        };
    }
}
