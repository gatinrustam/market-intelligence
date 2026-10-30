<?php

namespace App\Filament\Pages;

use App\Api\ArticleRouterClient;
use App\Api\ArticleSemanticClient;
use App\Api\CorrelationClient;
use App\Api\EventResearchClient;
use App\Research\NewsPresentation;
use Filament\Actions\Action;
use Filament\Notifications\Notification;
use Filament\Pages\Page;
use Illuminate\Support\Str;
use Illuminate\Validation\Rule;
use Livewire\Attributes\Locked;

class NewsDetail extends Page
{
    protected static bool $shouldRegisterNavigation = false;

    protected static ?string $slug = 'news/{routing}';

    protected static ?string $title = 'News Detail';

    protected string $view = 'filament.pages.news-detail';

    #[Locked]
    public string $routingId;

    #[Locked]
    public int $reviewRevision = 0;

    #[Locked]
    public string $requestId;

    #[Locked]
    public ?array $pendingPayload = null;

    public string $status = 'reviewed';

    public string $usefulness = '';

    public string $priority_override = '';

    public string $facts_correct = '';

    public string $event_type_correct = '';

    public string $duplicate = '';

    public bool $send_to_llm = false;

    public string $comment = '';

    public function mount(string $routing): void
    {
        abort_unless(Str::isUuid($routing), 404);
        $this->routingId = $routing;
        $this->requestId = (string) Str::uuid();
        $result = app(ArticleRouterClient::class)->article($routing);
        if ($result['ok']) {
            $this->reviewRevision = $result['data']['review']['revision'];
            $labels = $result['data']['labels'];
            if ($labels) {
                $last = end($labels);
                foreach (['status', 'usefulness', 'priority_override', 'comment'] as $field) {
                    $this->$field = $last[$field] ?? '';
                }
                foreach (['facts_correct', 'event_type_correct', 'duplicate'] as $field) {
                    $this->$field = ($last[$field] ?? null) === null ? '' : ($last[$field] ? 'yes' : 'no');
                }
                $this->send_to_llm = $last['send_to_llm'];
            }
        }
    }

    public function saveReview(): void
    {
        abort_unless(auth()->check(), 403);
        $this->validate([
            'status' => ['required', Rule::in(['new', 'reviewed', 'dismissed', 'escalated'])],
            'usefulness' => ['nullable', Rule::in(['useful', 'not_useful'])],
            'priority_override' => ['nullable', Rule::in(['critical', 'important', 'review', 'low', 'archive'])],
            'facts_correct' => ['nullable', Rule::in(['yes', 'no'])], 'event_type_correct' => ['nullable', Rule::in(['yes', 'no'])], 'duplicate' => ['nullable', Rule::in(['yes', 'no'])],
            'send_to_llm' => ['boolean'], 'comment' => ['string', 'max:2000'],
        ]);
        $payload = ['request_id' => $this->requestId, 'expected_revision' => $this->reviewRevision, 'reviewer' => auth()->user()->email,
            'status' => $this->status, 'usefulness' => $this->usefulness ?: null, 'priority_override' => $this->priority_override ?: null,
            'send_to_llm' => $this->send_to_llm, 'comment' => $this->comment];
        foreach (['facts_correct', 'event_type_correct', 'duplicate'] as $field) {
            $payload[$field] = $this->$field === '' ? null : $this->$field === 'yes';
        }
        if ($this->pendingPayload !== null && $this->pendingPayload !== $payload) {
            Notification::make()->danger()->title('Previous save was uncertain. Restore the previous values and retry, or reload to inspect saved history.')->send();

            return;
        }
        $this->pendingPayload = $payload;
        $result = app(ArticleRouterClient::class)->saveLabel($this->routingId, $payload);
        if (! $result['ok']) {
            Notification::make()->danger()->title($result['status'] === 409 ? 'Review conflict. Reload the article before editing.' : $result['error'])->send();

            return;
        }
        $this->reviewRevision = $result['data']['revision'];
        $this->requestId = (string) Str::uuid();
        $this->pendingPayload = null;
        Notification::make()->success()->title('Оценка сохранена. Исходный анализ не изменён.')->send();
    }

    public function getHeading(): string
    {
        return '';
    }

    public function reviewAction(): Action
    {
        return Action::make('review')->label('Оставить / изменить оценку')
            ->icon('heroicon-o-pencil-square')->outlined()
            ->modalHeading('Оценка статьи')->modalWidth('3xl')
            ->modalContent(fn () => view('research.news-review', $this->getViewData()))
            ->modalSubmitAction(false)->modalCancelActionLabel('Закрыть');
    }

    protected function getViewData(): array
    {
        $result = app(ArticleRouterClient::class)->article($this->routingId);
        $comparison = $result['ok'] ? app(EventResearchClient::class)->forDocument(
            $result['data']['machine']['document']['document_id'],
            $result['data']['snapshot']['intelligence']['document']['input_message_id'],
            $result['data']['machine']['document']['intelligence_id'] ?? $result['data']['snapshot']['intelligence']['intelligence_id'],
        ) : ['ok' => false, 'data' => [], 'error' => 'Exact document unavailable'];

        $correlation = $result['ok'] ? app(CorrelationClient::class)->forDocument(
            $result['data']['machine']['document']['document_id'],
            $result['data']['snapshot']['intelligence']['document']['input_message_id'],
            $result['data']['machine']['document']['intelligence_id'] ?? $result['data']['snapshot']['intelligence']['intelligence_id'],
        ) : ['ok' => false, 'data' => [], 'error' => 'Exact document unavailable'];

        $insight = $result['ok'] ? app(ArticleSemanticClient::class)->forDocument(
            $result['data']['machine']['document']['document_id'],
            $result['data']['snapshot']['intelligence']['document']['input_message_id'],
            $result['data']['machine']['document']['intelligence_id'] ?? $result['data']['snapshot']['intelligence']['intelligence_id'],
        ) : ['ok' => false, 'data' => [], 'error' => 'Exact document unavailable'];

        $presentation = $result['ok'] ? NewsPresentation::present($result['data'], $insight) : [];
        $market = $presentation ? app(NewsPresentation::class)->context($presentation['event']) : [];

        return ['presentation' => $presentation, 'market' => $market, 'insightResult' => $insight, 'result' => $result, 'comparisonResult' => $comparison, 'correlationResult' => $correlation];
    }
}
