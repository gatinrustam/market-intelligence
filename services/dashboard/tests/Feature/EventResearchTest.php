<?php

namespace Tests\Feature;

use App\Api\EventResearchClient;
use App\Filament\Pages\NewsDetail;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Livewire\Livewire;
use Tests\TestCase;

class EventResearchTest extends TestCase
{
    use RefreshDatabase;

    private array $research;

    private array $article;

    private string $routingId = 'f6e416d1-4d65-4d58-8704-856d48b330a3';

    protected function setUp(): void
    {
        parent::setUp();
        $this->actingAs(User::factory()->create());
        Http::preventStrayRequests();
        $this->research = json_decode(file_get_contents(base_path('tests/Fixtures/event-research.json')), true);
        $this->article = json_decode(file_get_contents(base_path('tests/Fixtures/article.json')), true);
        $this->research['comparison']['document_id'] = $this->article['machine']['document']['document_id'];
        $this->research['result']['document']['document_id'] = $this->article['machine']['document']['document_id'];
        $this->research['result']['document']['input_message_id'] = $this->article['snapshot']['intelligence']['document']['input_message_id'];
        $this->research['result']['document']['intelligence_id'] = $this->article['machine']['document']['intelligence_id'];
    }

    public function test_news_detail_shows_read_only_fact_basis_conflict_and_evidence(): void
    {
        Http::fake(['http://article-router:8010/*' => Http::response($this->article), 'http://event-research:8011/*' => Http::response([$this->research])]);
        Livewire::test(NewsDetail::class, ['routing' => $this->routingId])->assertSee('Event Engine Comparison')->assertSee('primary_fact')->assertSee('classification_conflict')
            ->assertSee('regulator.enforcement')->assertSee($this->research['result']['candidates'][0]['fact_references'][0]['evidence']['text']);
        Http::assertNotSent(fn ($request) => $request->method() !== 'GET');
    }

    public function test_outage_keeps_article_and_review_available(): void
    {
        Http::fake(['http://article-router:8010/*' => Http::response($this->article), 'http://event-research:8011/*' => Http::response([], 503)]);
        Livewire::test(NewsDetail::class, ['routing' => $this->routingId])->assertSee('Event Engine Comparison unavailable')->assertSee('Human Review')->assertSee('Document Intelligence and evidence');
    }

    public function test_mismatched_input_fails_closed(): void
    {
        $this->research['result']['document']['input_message_id'] = 'a0000000-0000-4000-8000-000000000000';
        Http::fake(['http://event-research:8011/*' => Http::response([$this->research])]);
        $response = app(EventResearchClient::class)->forDocument($this->article['machine']['document']['document_id'], $this->article['snapshot']['intelligence']['document']['input_message_id']);
        $this->assertFalse($response['ok']);
        $this->assertSame([], $response['data']);
    }

    public function test_missing_research_is_explicit(): void
    {
        Http::fake(['http://article-router:8010/*' => Http::response($this->article), 'http://event-research:8011/*' => Http::response([])]);
        Livewire::test(NewsDetail::class, ['routing' => $this->routingId])->assertSee('No v2 research result for this exact document input.');
    }
}
