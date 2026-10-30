<?php

namespace Tests\Feature;

use App\Api\ArticleSemanticClient;
use App\Filament\Pages\NewsDetail;
use App\Livewire\SemanticReview;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Livewire\Livewire;
use Tests\TestCase;

class ArticleSemanticTest extends TestCase
{
    use RefreshDatabase;

    private function article(): array
    {
        return json_decode(file_get_contents(base_path('tests/Fixtures/article.json')), true);
    }

    private function row(): array
    {
        $article = $this->article();
        $document = $article['machine']['document'];
        $document['input_message_id'] = $article['snapshot']['intelligence']['document']['input_message_id'];
        $document['language'] = 'en';
        $span = ['text' => '<script>alert(1)</script> Exact source claim.', 'start_char' => 0, 'end_char' => 40];
        $claim = ['claim_id' => 'a0000000-0000-4000-8000-000000000001', 'evidence' => $span, 'extractor' => 'semantic', 'status' => 'semantic_candidate', 'reason' => 'Extractive candidate, not independently verified.', 'supporting_fact_ids' => []];

        return ['insight' => ['semantic_id' => 'a0000000-0000-4000-8000-000000000002', 'document' => $document, 'status' => 'partial', 'potential_importance' => 'medium', 'article_type' => 'commentary',
            'why_it_matters' => ['Supported policy context'], 'main_topics' => ['monetary_policy'], 'affected_assets' => [], 'key_claims' => [$claim], 'important_numbers' => [], 'entities' => [],
            'routing' => ['old_route' => 'review', 'semantic_suggested_route' => 'important'], 'information_value' => ['market_relevance' => ['level' => 'medium', 'reasons' => ['Exact evidence']]],
            'limitations' => ['Partial observed source body'], 'provenance' => ['semantic_model' => 'BAAI/bge-m3', 'pipeline_version' => 'semantic_pipeline_v2'], 'conflicts' => []],
            'review' => ['revision' => 0], 'labels' => []];
    }

    public function test_insight_is_above_debug_sections_and_escapes_evidence(): void
    {
        $this->actingAs(User::factory()->create());
        Http::preventStrayRequests();
        Http::fake(['http://article-router:8010/*' => Http::response($this->article()),
            'http://article-semantic:8012/documents/*/insight' => Http::response([$this->row()]),
            'http://event-research:8011/*' => Http::response([])]);

        Livewire::test(NewsDetail::class, ['routing' => 'f6e416d1-4d65-4d58-8704-856d48b330a3'])
            ->assertSeeInOrder(['Что произошло', 'Ключевые факты и утверждения', 'Advanced / Audit', 'Routing features and reasons', 'ARTICLE INSIGHT'])
            ->assertSee('semantic_candidate')->assertSee('semantic_pipeline_v2')->assertSee('BAAI/bge-m3')->assertDontSeeHtml('<script>alert(1)</script>');
        Http::assertNotSent(fn ($request) => $request->method() !== 'GET');
    }

    public function test_semantic_outage_keeps_di_and_old_review_available(): void
    {
        $this->actingAs(User::factory()->create());
        Http::preventStrayRequests();
        Http::fake(['http://article-router:8010/*' => Http::response($this->article()),
            'http://article-semantic:8012/documents/*/insight' => Http::response([], 503),
            'http://event-research:8011/*' => Http::response([])]);

        Livewire::test(NewsDetail::class, ['routing' => 'f6e416d1-4d65-4d58-8704-856d48b330a3'])
            ->assertSee('Article Insight unavailable')->assertSee('Human Review')->assertSee('Document Intelligence and evidence');
    }

    public function test_insight_for_wrong_input_fails_closed(): void
    {
        $row = $this->row();
        Http::preventStrayRequests();
        Http::fake(['http://article-semantic:8012/documents/*/insight' => Http::response([$row])]);

        $response = app(ArticleSemanticClient::class)->forDocument($row['insight']['document']['document_id'], 'wrong-input', $row['insight']['document']['intelligence_id']);
        $this->assertFalse($response['ok']);
    }

    public function test_semantic_labels_only_write_to_separate_review_service(): void
    {
        $this->actingAs(User::factory()->create());
        config(['upstreams.semantic_review_token' => 'test-review-token']);
        Http::preventStrayRequests();
        Http::fake(['http://article-semantic:8012/reviews/*/labels' => Http::response(['revision' => 1])]);
        $row = $this->row();

        Livewire::test(SemanticReview::class, ['semanticId' => $row['insight']['semantic_id'], 'review' => $row['review'], 'labels' => [], 'claims' => $row['insight']['key_claims']])
            ->set('semantic_correct', 'yes')->set('gold_important', 'yes')->set('gold_assets', ['rates'])
            ->call('save')->assertSee('Semantic review saved. Machine analysis unchanged.');
        Http::assertSent(fn ($request) => $request->method() === 'POST' && $request['semantic_correct'] === true && $request['gold_assets'] === ['rates']);
        Http::assertSentCount(1);
    }

    public function test_claim_labels_cannot_reference_another_result(): void
    {
        $this->actingAs(User::factory()->create());
        Http::preventStrayRequests();
        $row = $this->row();

        Livewire::test(SemanticReview::class, ['semanticId' => $row['insight']['semantic_id'], 'review' => $row['review'], 'labels' => [], 'claims' => $row['insight']['key_claims']])
            ->set('correct_claim_ids', ['unrelated-claim'])->call('save')->assertHasErrors(['correct_claim_ids.0']);
        Http::assertNothingSent();
    }

    public function test_semantic_review_conflict_is_visible(): void
    {
        $this->actingAs(User::factory()->create());
        Http::preventStrayRequests();
        Http::fake(['http://article-semantic:8012/reviews/*/labels' => Http::response([], 409)]);
        $row = $this->row();

        Livewire::test(SemanticReview::class, ['semanticId' => $row['insight']['semantic_id'], 'review' => $row['review'], 'labels' => [], 'claims' => $row['insight']['key_claims']])
            ->call('save')->assertSee('Semantic review conflict. Reload before editing.');
    }

    public function test_russian_comparison_preserves_source_text_and_escapes_both_versions(): void
    {
        $this->actingAs(User::factory()->create());
        $row = $this->row();
        $row['insight']['document']['language'] = 'ru';
        $row['insight']['key_claims'][0]['evidence']['text'] = 'Банк России сохранил ключевую ставку. <script>alert(1)</script>';
        $row['baseline_insight'] = $row['insight'];
        $row['insight']['comparison'] = ['concepts_removed' => ['etf'], 'concepts_added' => [], 'assets_removed' => ['crypto_market'], 'assets_added' => []];
        Http::preventStrayRequests();
        Http::fake(['http://article-router:8010/*' => Http::response($this->article()),
            'http://article-semantic:8012/documents/*/insight' => Http::response([$row]),
            'http://event-research:8011/*' => Http::response([])]);
        Livewire::test(NewsDetail::class, ['routing' => 'f6e416d1-4d65-4d58-8704-856d48b330a3'])
            ->assertSee('DI-5 vs DI-5.1')->assertSee('Исключенные темы')
            ->assertSee('Банк России сохранил ключевую ставку.')->assertDontSeeHtml('<script>alert(1)</script>');
        Http::assertNotSent(fn ($request) => $request->method() !== 'GET');
    }

    public function test_russian_review_sends_concepts_and_false_positives_separately(): void
    {
        $this->actingAs(User::factory()->create());
        Http::preventStrayRequests();
        Http::fake(['http://article-semantic:8012/reviews/*/labels' => Http::response(['revision' => 1])]);
        $row = $this->row();
        Livewire::test(SemanticReview::class, ['semanticId' => $row['insight']['semantic_id'], 'review' => $row['review'], 'labels' => [], 'claims' => [], 'language' => 'ru'])
            ->set('concepts_correct', 'no')->set('gold_concepts_text', 'interest_rates, inflation')
            ->set('false_positives_text', 'crypto_exchange')->set('gold_assets', ['RUB', 'rates'])
            ->call('save')->assertSee('Оценка сохранена отдельно.');
        Http::assertSent(fn ($request) => $request['concepts_correct'] === false && $request['gold_concepts'] === ['interest_rates', 'inflation'] && $request['false_positives'] === ['crypto_exchange'] && $request['gold_assets'] === ['RUB', 'rates']);
        Http::assertSentCount(1);
    }
}
