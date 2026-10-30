<?php

namespace App\Filament\Pages;

use App\Research\DashboardData;
use App\Research\Display;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Filters\SelectFilter;
use Filament\Tables\Table;

class Analyses extends CataloguePage
{
    protected static ?int $navigationSort = 3;

    public function catalogue(): array
    {
        return app(DashboardData::class)->analyses();
    }

    public function table(Table $table): Table
    {
        return $table->records(fn (?string $search, ?array $filters, int|string $page, int|string $recordsPerPage) => $this->records($search, $filters, $page, $recordsPerPage))
            ->searchable()->paginationPageOptions([10, 25, 50])->columns([
                TextColumn::make('event')->wrap()->limit(80), TextColumn::make('model'), TextColumn::make('prompt_version'),
                TextColumn::make('mode')->badge()->color(fn (string $state) => Display::color($state)), TextColumn::make('status')->badge()->color(fn (string $state) => Display::color($state)),
                TextColumn::make('created_at')->label('Created at · UTC'), TextColumn::make('latency_ms')->label('Latency · ms')->placeholder('Unavailable'), TextColumn::make('token_usage')->label('Token usage')->wrap(),
            ])->filters(array_map(fn ($key) => SelectFilter::make($key)->options(fn () => $this->options($key)), ['status', 'model', 'mode']))
            ->recordUrl(fn (array $record) => AnalysisDetail::getUrl(['analysis' => $record['id']]))->emptyStateHeading('Not run')->emptyStateDescription('No analyses available. This dashboard never starts LLM jobs.');
    }
}
