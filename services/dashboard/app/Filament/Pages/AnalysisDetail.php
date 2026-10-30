<?php

namespace App\Filament\Pages;

use App\Api\LlmAnalysisClient;
use Filament\Pages\Page;
use Illuminate\Support\Str;
use Livewire\Attributes\Locked;

class AnalysisDetail extends Page
{
    protected static bool $shouldRegisterNavigation = false;

    protected static ?string $slug = 'analyses/{analysis}';

    protected static ?string $title = 'Analysis detail';

    protected string $view = 'filament.pages.analysis-detail';

    #[Locked]
    public string $analysisId;

    public function mount(string $analysis): void
    {
        abort_unless(Str::isUuid($analysis), 404);
        $this->analysisId = $analysis;
    }

    protected function getViewData(): array
    {
        return ['result' => app(LlmAnalysisClient::class)->analysis($this->analysisId)];
    }
}
