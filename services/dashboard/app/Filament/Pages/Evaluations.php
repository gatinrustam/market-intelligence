<?php

namespace App\Filament\Pages;

use App\Research\DashboardData;
use Filament\Pages\Page;
use Livewire\Attributes\Url;

class Evaluations extends Page
{
    protected static ?int $navigationSort = 4;

    protected string $view = 'filament.pages.evaluations';

    #[Url]
    public string $origin = 'model';

    protected function getViewData(): array
    {
        if (! in_array($this->origin, ['model', 'fixture'], true)) {
            $this->origin = 'model';
        }

        return ['data' => app(DashboardData::class)->evaluationMetrics($this->origin)];
    }
}
