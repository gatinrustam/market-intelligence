<?php

namespace App\Filament\Pages;

use App\Api\ArticleRouterClient;
use App\Research\NewsPresentation;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Filters\SelectFilter;
use Filament\Tables\Table;
use Illuminate\Pagination\LengthAwarePaginator;

class NewsFeed extends CataloguePage
{
    protected static ?int $navigationSort = 1;

    protected static ?string $title = 'News Feed';

    protected ?array $articleCatalogue = null;

    public function catalogue(): array
    {
        if ($this->articleCatalogue !== null) {
            return $this->articleCatalogue;
        }
        $result = app(ArticleRouterClient::class)->articles();

        return $this->articleCatalogue = ['rows' => $result['ok'] ? $result['data'] : [], 'error' => $result['error'], 'truncated' => $result['truncated'] ?? false];
    }

    protected function records(?string $search, ?array $filters, int|string $page, int|string $recordsPerPage): LengthAwarePaginator
    {
        $rows = collect($this->catalogue()['rows']);
        if ($search) {
            $rows = $rows->filter(fn ($r) => str_contains(mb_strtolower($r['title']), mb_strtolower($search)));
        }
        foreach ($filters ?? [] as $field => $filter) {
            $value = $filter['value'] ?? null;
            if (! filled($value)) {
                continue;
            }
            $rows = $rows->filter(fn ($r) => match ($field) {
                'scope' => $value === 'all' || in_array($r['route'], ['critical', 'important', 'review'], true),
                'crypto_category' => in_array($value, $r['categories'] ?? [], true),
                'topic' => in_array($value, $r['topics'], true),
                'date' => substr($r['published'] ?? '', 0, 10) === $value,
                default => ($r[$field] ?? null) === $value,
            });
        }
        $per = is_numeric($recordsPerPage) ? (int) $recordsPerPage : 25;

        return new LengthAwarePaginator($rows->forPage((int) $page, $per), $rows->count(), $per, (int) $page);
    }

    protected function options(string $key): array
    {
        $rows = collect($this->catalogue()['rows']);
        $values = match ($key) {
            'topic' => $rows->flatMap(fn ($r) => $r['topics']),
            'date' => $rows->map(fn ($r) => substr($r['published'] ?? '', 0, 10)),
            default => $rows->pluck($key),
        };

        return $values->filter()->unique()->sort()->mapWithKeys(fn ($v) => [$v => $v])->all();
    }

    public function table(Table $table): Table
    {
        return $table->records(fn (?string $search, ?array $filters, int|string $page, int|string $recordsPerPage) => $this->records($search, $filters, $page, $recordsPerPage))
            ->searchable()->paginationPageOptions([10, 25, 50])->defaultPaginationPageOption(25)
            ->columns([
                TextColumn::make('published')->label('Время · UTC')->dateTime('d.m.Y H:i'),
                TextColumn::make('route')->label('Приоритет')->badge()->formatStateUsing(fn ($state) => NewsPresentation::label($state))->color(fn ($state) => NewsPresentation::color($state)),
                TextColumn::make('source')->label('Источник')->badge()->formatStateUsing(fn ($state) => NewsPresentation::source($state)),
                TextColumn::make('title')->label('Статья')->wrap()->limit(110),
                TextColumn::make('topics')->label('Темы')->badge()->formatStateUsing(fn ($state) => NewsPresentation::label($state))->limitList(2)->expandableLimitedList(),
                TextColumn::make('affected_assets')->label('Активы')->placeholder('В карточке статьи')->tooltip('Подтверждённые связи доступны в анализе статьи'),
                TextColumn::make('review_status')->label('Проверка')->badge()->formatStateUsing(fn ($state) => NewsPresentation::label($state)),
            ])->filters([
                SelectFilter::make('crypto_category')->label('Crypto')->options(['crypto' => 'Crypto · все', 'exchange' => 'Exchange', 'stablecoin' => 'Stablecoin', 'corporate_treasury' => 'Corporate Treasury', 'institutional' => 'Institutional', 'incidents' => 'Incidents']),
                SelectFilter::make('scope')->label('Visibility')->options(['queue' => 'Review queue', 'all' => 'All retained articles'])->default('queue'),
                ...array_map(fn ($key) => SelectFilter::make($key)->options(fn () => $this->options($key)), ['route', 'source', 'topic', 'review_status', 'date', 'language']),
            ])->recordUrl(fn (array $record) => NewsDetail::getUrl(['routing' => $record['id']]))->emptyStateHeading('No articles')->emptyStateDescription('Check filters or Article Router availability.');
    }
}
