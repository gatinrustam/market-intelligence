<?php

namespace App\Filament\Pages;

use App\Research\DashboardData;
use App\Research\Display;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Filters\SelectFilter;
use Filament\Tables\Table;

class Events extends CataloguePage
{
    protected static ?int $navigationSort = 2;

    public function catalogue(): array
    {
        return app(DashboardData::class)->catalogue();
    }

    public function table(Table $table): Table
    {
        return $table->records(fn (?string $search, ?array $filters, int|string $page, int|string $recordsPerPage) => $this->records($search, $filters, $page, $recordsPerPage))
            ->searchable()->paginationPageOptions([10, 25, 50])->defaultPaginationPageOption(25)
            ->columns([
                TextColumn::make('detected_at')->label('Detected at · UTC'), TextColumn::make('event_type')->label('Event type')->wrap(),
                TextColumn::make('title')->label('Canonical title')->wrap()->limit(95), TextColumn::make('source')->wrap(), TextColumn::make('jurisdiction'),
                TextColumn::make('quality')->label('Evidence quality')->badge()->color(fn (string $state) => Display::color($state)),
                TextColumn::make('lifecycle')->badge(), TextColumn::make('llm_status')->label('LLM status · latest run')->badge()->color(fn (string $state) => Display::color($state)),
            ])->filters(array_map(fn ($key) => SelectFilter::make($key)->options(fn () => $this->options($key)), ['event_type', 'source', 'quality', 'lifecycle', 'llm_status']))
            ->recordUrl(fn (array $record) => EventDetail::getUrl(['event' => $record['id']]))->emptyStateHeading('No events')->emptyStateDescription('Check filters or upstream availability.');
    }
}
