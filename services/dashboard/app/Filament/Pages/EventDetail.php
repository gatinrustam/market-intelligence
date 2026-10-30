<?php

namespace App\Filament\Pages;

use App\Research\DashboardData;
use Filament\Pages\Page;
use Illuminate\Support\Str;
use Livewire\Attributes\Locked;
use Livewire\Attributes\Url;

class EventDetail extends Page
{
    protected static bool $shouldRegisterNavigation = false;

    protected static ?string $slug = 'events/{event}';

    protected static ?string $title = 'Event detail';

    protected string $view = 'filament.pages.event-detail';

    #[Locked]
    public string $eventId;

    #[Url]
    public string $basis = 'live';

    public function mount(string $event): void
    {
        abort_unless(Str::isUuid($event), 404);
        $this->eventId = $event;
    }

    protected function getViewData(): array
    {
        abort_unless(in_array($this->basis, ['live', 'research_hypothetical'], true), 422);

        return ['data' => app(DashboardData::class)->event($this->eventId, $this->basis)];
    }
}
