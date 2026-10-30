<?php

namespace App\Filament\Pages;

use App\Research\DashboardData;
use Filament\Pages\Page;

class Overview extends Page
{
    protected static ?int $navigationSort = 1;

    protected string $view = 'filament.pages.overview';

    protected function getViewData(): array
    {
        return ['data' => app(DashboardData::class)->overview()];
    }
}
