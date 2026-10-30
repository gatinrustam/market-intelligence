<?php

namespace App\Livewire;

use App\Api\ArticleSemanticClient;
use Illuminate\Contracts\View\View;
use Illuminate\Support\Str;
use Illuminate\Validation\Rule;
use Livewire\Attributes\Locked;
use Livewire\Component;

class SemanticReview extends Component
{
    #[Locked]
    public string $semanticId;

    #[Locked]
    public int $revision = 0;

    #[Locked]
    public string $requestId;

    #[Locked]
    public ?array $pendingPayload = null;

    #[Locked]
    public array $claims = [];

    public string $concepts_correct = '';

    public string $false_positives_text = '';

    public string $gold_concepts_text = '';

    #[Locked]
    public string $language = 'en';

    public string $semantic_correct = '';

    public string $claims_correct = '';

    public string $assets_correct = '';

    public string $importance_correct = '';

    public string $missing_context = '';

    public string $gold_important = '';

    public array $gold_assets = [];

    public array $correct_claim_ids = [];

    public string $comment = '';

    public string $feedback = '';

    public function mount(string $semanticId, array $review, array $labels, array $claims, string $language = 'en'): void
    {
        $this->semanticId = $semanticId;
        $this->language = $language;
        $this->revision = $review['revision'];
        $this->requestId = (string) Str::uuid();
        $this->claims = $claims;
        if ($labels) {
            $label = end($labels);
            foreach (['concepts_correct', 'semantic_correct', 'claims_correct', 'assets_correct', 'importance_correct', 'missing_context', 'gold_important'] as $field) {
                $this->$field = ($label[$field] ?? null) === null ? '' : ($label[$field] ? 'yes' : 'no');
            }
            $this->gold_assets = $label['gold_assets'] ?? [];
            $this->correct_claim_ids = $label['correct_claim_ids'] ?? [];
            $this->comment = $label['comment'] ?? '';
            $this->false_positives_text = implode("\n", $label['false_positives'] ?? []);
            $this->gold_concepts_text = implode(', ', $label['gold_concepts'] ?? []);
        }
    }

    public function save(): void
    {
        abort_unless(auth()->check(), 403);
        $rules = ['false_positives_text' => ['string', 'max:4000'], 'gold_concepts_text' => ['string', 'max:2000'], 'comment' => ['string', 'max:4000'], 'gold_assets' => ['array'],
            'gold_assets.*' => [Rule::in(['BTC', 'ETH', 'crypto_market', 'USD', 'EUR', 'US_equities', 'specific_company', 'rates', 'gold', 'RUB', 'RU_equities', 'fx_market'])],
            'correct_claim_ids' => ['array'], 'correct_claim_ids.*' => [Rule::in(array_column($this->claims, 'claim_id'))]];
        $booleans = ['concepts_correct', 'semantic_correct', 'claims_correct', 'assets_correct', 'importance_correct', 'missing_context', 'gold_important'];
        foreach ($booleans as $field) {
            $rules[$field] = ['nullable', Rule::in(['yes', 'no'])];
        }
        $this->validate($rules);
        $payload = ['request_id' => $this->requestId, 'expected_revision' => $this->revision, 'status' => 'reviewed',
            'reviewer' => auth()->user()->email, 'false_positives' => array_values(array_filter(array_map('trim', explode("\n", $this->false_positives_text)))), 'gold_concepts' => array_values(array_filter(array_map('trim', explode(',', $this->gold_concepts_text)))), 'gold_assets' => $this->gold_assets, 'correct_claim_ids' => $this->correct_claim_ids, 'comment' => $this->comment];
        foreach ($booleans as $field) {
            $payload[$field] = $this->$field === '' ? null : $this->$field === 'yes';
        }
        if ($this->pendingPayload !== null && $this->pendingPayload !== $payload) {
            $this->feedback = 'Previous save uncertain. Restore unchanged values and retry, or reload.';

            return;
        }
        $this->pendingPayload = $payload;
        $response = app(ArticleSemanticClient::class)->saveLabel($this->semanticId, $payload);
        if (! $response['ok']) {
            $this->feedback = $response['status'] === 409 ? 'Semantic review conflict. Reload before editing.' : $response['error'];

            return;
        }
        $this->revision = $response['data']['revision'];
        $this->requestId = (string) Str::uuid();
        $this->pendingPayload = null;
        $this->feedback = $this->language === 'ru' ? 'Оценка сохранена отдельно. Результат анализа не изменён.' : 'Semantic review saved. Machine analysis unchanged.';
    }

    public function render(): View
    {
        return view('livewire.semantic-review');
    }
}
