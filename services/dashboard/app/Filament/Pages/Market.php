<?php

namespace App\Filament\Pages;

use App\Research\DashboardData;
use Filament\Pages\Page;

class Market extends Page
{
    protected static ?int $navigationSort = 4;

    protected string $view = 'filament.pages.market';

    protected function getViewData(): array
    {
        return ['data' => app(DashboardData::class)->market()];
    }
}
