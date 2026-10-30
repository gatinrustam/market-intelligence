<?php

namespace Tests\Feature;

use App\Api\ArticleRouterClient;
use App\Filament\Pages\NewsDetail;
use App\Filament\Pages\NewsFeed;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Livewire\Livewire;
use Tests\TestCase;

class ArticleRouterTest extends TestCase
{
    use RefreshDatabase;

    private string $id = 'f6e416d1-4d65-4d58-8704-856d48b330a3';

    private array $detail;

    protected function setUp(): void
    {
        parent::setUp();
        $this->actingAs(User::factory()->create(['email' => 'reviewer@local.test']));
        $this->detail = json_decode(file_get_contents(base_path('tests/Fixtures/article.json')), true);
        config(['upstreams.article_review_token' => 'review-test-secret']);
        Http::preventStrayRequests();
    }

    private function fake(int $saveStatus = 200): void
    {
        Http::fake(function ($request) use ($saveStatus) {
            if ($request->method() === 'POST') {
                return Http::response(['revision' => 1, 'request_id' => $request['request_id']], $saveStatus);
            }
            if (str_contains($request->url(), '/articles/'.$this->id)) {
                return Http::response($this->detail);
            }
            $base = ['source' => 'fed', 'published' => '2026-04-29T18:00:00Z', 'language' => 'en', 'topics' => ['monetary_policy'], 'route' => 'important', 'market_relevance' => 'high', 'crypto_relevance' => 'none', 'financial_fact_count' => 1, 'measurement_count' => 2, 'document_quality' => 'high', 'review_status' => 'new'];

            return Http::response(['items' => [['id' => $this->id, 'title' => 'Fed rate decision', ...$base], ['id' => 'other', 'title' => 'Personnel departure', ...array_merge($base, ['route' => 'low', 'source' => 'sec', 'topics' => ['personnel']])]], 'total' => 2]);
        });
    }

    public function test_feed_default_queue_and_filters_search(): void
    {
        $this->fake();
        Livewire::test(NewsFeed::class)->assertSee('Fed rate decision')->assertDontSee('Personnel departure')
            ->filterTable('scope', 'all')->assertSee('Personnel departure')->searchTable('departure')->assertDontSee('Fed rate decision');
        Livewire::test(NewsFeed::class)->filterTable('scope', 'all')->filterTable('topic', 'personnel')->assertSee('Personnel departure')->assertDontSee('Fed rate decision');
        Livewire::test(NewsFeed::class)->filterTable('date', '2026-04-30')->assertDontSee('Fed rate decision');
        Livewire::test(NewsFeed::class)->filterTable('language', 'ru')->assertDontSee('Fed rate decision');
        Livewire::test(NewsFeed::class)->filterTable('review_status', 'reviewed')->assertDontSee('Fed rate decision');
    }

    public function test_crypto_filter_uses_category_metadata(): void
    {
        $base = ['published' => '2026-09-20T12:00:00Z', 'language' => 'en', 'topics' => [], 'route' => 'review', 'review_status' => 'new'];
        Http::fake(['*' => Http::response(['items' => [
            [...$base, 'id' => 'kraken', 'title' => 'Funding incident', 'source' => 'kraken_status_incidents', 'categories' => ['crypto', 'exchange', 'incidents']],
            [...$base, 'id' => 'circle', 'title' => 'Payments update', 'source' => 'circle_pressroom', 'categories' => ['crypto', 'stablecoin']],
            [...$base, 'id' => 'fed', 'title' => 'Policy decision', 'source' => 'fed_monetary_policy'],
        ], 'total' => 3])]);
        Livewire::test(NewsFeed::class)->filterTable('crypto_category', 'crypto')
            ->assertSee('Funding incident')->assertSee('Payments update')->assertDontSee('Policy decision');
        Livewire::test(NewsFeed::class)->filterTable('crypto_category', 'incidents')
            ->assertSee('Funding incident')->assertSee('Kraken')->assertDontSee('Payments update');
        Livewire::test(NewsFeed::class)->filterTable('crypto_category', 'stablecoin')
            ->assertSee('Payments update')->assertSee('Circle')->assertDontSee('Funding incident');
    }

    public function test_detail_evidence_and_save_only_labels_with_authenticated_reviewer(): void
    {
        $this->fake();
        Livewire::test(NewsDetail::class, ['routing' => $this->id])->assertSee('Routing features and reasons')->assertSee('3‑1/2 to 3‑3/4 percent')->assertDontSeeHtml('@js($key)')
            ->set('usefulness', 'useful')->set('priority_override', 'important')->set('facts_correct', 'yes')->set('send_to_llm', true)
            ->set('comment', 'UI test')->call('saveReview')->assertHasNoErrors()->assertSet('reviewRevision', 1);
        Http::assertSent(fn ($r) => $r->method() === 'POST' && $r->url() === 'http://article-router:8010/reviews/'.$this->id.'/labels' && $r->hasHeader('Authorization', 'Bearer review-test-secret') && $r['reviewer'] === 'reviewer@local.test' && $r['send_to_llm'] === true && $r['facts_correct'] === true && $r['expected_revision'] === 0);
        Http::assertNotSent(fn ($r) => $r->method() !== 'GET' && ! str_contains($r->url(), '/reviews/'));
    }

    public function test_outage_and_conflict_do_not_claim_save(): void
    {
        $this->fake(409);
        Livewire::test(NewsDetail::class, ['routing' => $this->id])->call('saveReview')->assertSet('reviewRevision', 0);
    }

    public function test_backend_outage_is_visible(): void
    {
        Http::fake(['*' => Http::response([], 503)]);
        Livewire::test(NewsFeed::class)->assertSee('HTTP 503');
        Livewire::test(NewsDetail::class, ['routing' => $this->id])->assertSee('Article Router unavailable');
    }

    public function test_labels_validated_and_missing_token_fails_closed(): void
    {
        $this->fake();
        Livewire::test(NewsDetail::class, ['routing' => $this->id])->set('priority_override', 'buy')->call('saveReview')->assertHasErrors(['priority_override']);
        Http::assertNotSent(fn ($r) => $r->method() === 'POST');
        config(['upstreams.article_review_token' => '']);
        $this->assertFalse(app(ArticleRouterClient::class)->saveLabel($this->id, [])['ok']);
        Http::assertNotSent(fn ($r) => $r->method() === 'POST');
    }

    public function test_review_pages_require_authentication(): void
    {
        auth()->logout();
        $this->get(NewsDetail::getUrl(['routing' => $this->id]))->assertRedirect();
        $this->get(NewsFeed::getUrl())->assertRedirect();
    }

    public function test_review_action_opens_modal_without_writing(): void
    {
        $this->fake();
        Livewire::test(NewsDetail::class, ['routing' => $this->id])
            ->mountAction('review')->assertActionMounted('review');
        Http::assertNotSent(fn ($r) => $r->method() !== 'GET');
    }

    public function test_completed_ai_is_displayed_for_exact_event_revision(): void
    {
        $this->assertAiStatus('completed');
    }

    public function test_blocked_ai_has_readable_reason(): void
    {
        $this->assertAiStatus('blocked');
    }

    private function assertAiStatus(string $status): void
    {
        $analysis = ['analysis_id' => 'a0000000-0000-4000-8000-000000000003', 'event_id' => $this->detail['snapshot']['events'][0]['event']['id'], 'event_revision' => 1, 'analysis_status' => $status, 'basis' => 'research_hypothetical', 'configuration' => ['model' => 'gpt-6-astra'], 'runs' => [], 'error' => 'market_decision_not_ready', 'analysis' => ['interpretation' => ['summary' => 'Stored model interpretation'], 'asset' => ['relevance' => 'high'], 'forecast' => []]];
        Http::fake(function ($request) use ($analysis) {
            if (str_contains($request->url(), '/articles/')) {
                return Http::response($this->detail);
            }
            if (str_contains($request->url(), 'llm-analysis:8005/analyses/')) {
                return Http::response($analysis);
            }
            if (str_contains($request->url(), 'llm-analysis:8005/analyses')) {
                return Http::response(['items' => [$analysis], 'total' => 1]);
            }

            return Http::response([]);
        });
        Livewire::test(NewsDetail::class, ['routing' => $this->id])
            ->assertSee($status === 'completed' ? 'Stored model interpretation' : 'Не готов рыночный контекст на момент решения')
            ->assertSee('Историческая симуляция · не live-решение');
        Http::assertNotSent(fn ($r) => $r->method() !== 'GET');
    }
}
