<?php

namespace App\Filament\Pages;

use Filament\Pages\Page;
use Filament\Tables\Concerns\InteractsWithTable;
use Filament\Tables\Contracts\HasTable;
use Illuminate\Pagination\LengthAwarePaginator;

abstract class CataloguePage extends Page implements HasTable
{
    use InteractsWithTable;

    protected string $view = 'filament.pages.catalogue';

    abstract public function catalogue(): array;

    protected function records(?string $search, ?array $filters, int|string $page, int|string $recordsPerPage): LengthAwarePaginator
    {
        $rows = collect($this->catalogue()['rows']);
        if ($search) {
            $rows = $rows->filter(fn ($r) => str_contains(mb_strtolower($r['title'] ?? $r['event'] ?? ''), mb_strtolower($search)));
        }
        foreach ($filters ?? [] as $field => $filter) {
            if (filled($filter['value'] ?? null)) {
                $rows = $rows->filter(fn ($r) => $field === 'source' ? in_array($filter['value'], explode(', ', $r['source'] ?? ''), true) : ($r[$field] ?? null) === $filter['value']);
            }
        }
        $per = is_numeric($recordsPerPage) ? (int) $recordsPerPage : 25;

        return new LengthAwarePaginator($rows->forPage((int) $page, $per), $rows->count(), $per, (int) $page);
    }

    protected function options(string $key): array
    {
        $values = collect($this->catalogue()['rows'])->pluck($key);
        if ($key === 'source') {
            $values = $values->flatMap(fn ($v) => explode(', ', $v));
        }

        return $values->unique()->sort()->mapWithKeys(fn ($v) => [$v => $v])->all();
    }
}
