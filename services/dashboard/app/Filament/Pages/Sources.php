<?php

namespace App\Filament\Pages;

use App\Research\DashboardData;
use Filament\Pages\Page;

class Sources extends Page
{
    protected static ?int $navigationSort = 5;

    protected string $view = 'filament.pages.sources';

    protected function getViewData(): array
    {
        return ['data' => app(DashboardData::class)->sources()];
    }
}
