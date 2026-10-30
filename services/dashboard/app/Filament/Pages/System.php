<?php

namespace App\Filament\Pages;

use App\Research\Health;
use Filament\Pages\Page;

class System extends Page
{
    protected static ?int $navigationSort = 6;

    protected string $view = 'filament.pages.system';

    protected function getViewData(): array
    {
        return ['data' => ['rows' => app(Health::class)->all()]];
    }
}
