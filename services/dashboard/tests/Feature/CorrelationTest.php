<?php

namespace Tests\Feature;

use App\Api\CorrelationClient;
use App\Filament\Pages\NewsDetail;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Livewire\Livewire;
use Tests\TestCase;

class CorrelationTest extends TestCase
{
    use RefreshDatabase;

    private function article(): array
    {
        return json_decode(file_get_contents(base_path('tests/Fixtures/article.json')), true);
    }

    private function correlation(): array
    {
        $article = $this->article();
        $document = $article['machine']['document'];
        $document['input_message_id'] = $article['snapshot']['intelligence']['document']['input_message_id'];
        $decision = ['mode' => 'suggestion', 'candidate_a' => 'a', 'candidate_b' => 'b', 'reason' => 'Exact date missing', 'matched_fields' => ['action', 'measurements'], 'conflicting_fields' => [], 'features' => ['same_action' => true], 'v1_same_event' => false];

        return ['document' => $document, 'candidate_id' => 'a', 'fingerprint' => ['hash' => 'fingerprint-example', 'components' => ['action' => 'hold']], 'decisions' => [$decision], 'suggestions' => [$decision],
            'event' => ['mode' => 'research', 'production_canonical' => false, 'event_id' => 'research-event', 'revision' => 1, 'correlation_mode' => 'insufficient_data', 'ruleset_version' => 'correlation_v2.1', 'fingerprint_version' => 'fact_identity_v1', 'document_count' => 1, 'independent_source_count' => 1, 'candidate_ids' => ['a'],
                'documents' => [['document_id' => $document['document_id'], 'title' => '<script>alert(1)</script>', 'sources' => ['fed']]]]];
    }

    public function test_news_detail_shows_read_only_correlation_and_escaped_documents(): void
    {
        $this->actingAs(User::factory()->create());
        Http::preventStrayRequests();
        Http::fake(['http://article-router:8010/*' => Http::response($this->article()),
            'http://event-research:8011/documents/*/correlation' => Http::response([$this->correlation()]),
            'http://event-research:8011/documents/*/comparison' => Http::response([])]);

        Livewire::test(NewsDetail::class, ['routing' => 'f6e416d1-4d65-4d58-8704-856d48b330a3'])
            ->assertSee('Correlation')->assertSee('Exact date missing')->assertSee('fingerprint-example')
            ->assertSee('Independent sources')->assertDontSeeHtml('<script>alert(1)</script>');
        Http::assertNotSent(fn ($request) => $request->method() !== 'GET');
    }

    public function test_outage_keeps_document_review_available(): void
    {
        $this->actingAs(User::factory()->create());
        Http::preventStrayRequests();
        Http::fake(['http://article-router:8010/*' => Http::response($this->article()),
            'http://event-research:8011/documents/*/correlation' => Http::response([], 503),
            'http://event-research:8011/documents/*/comparison' => Http::response([])]);

        Livewire::test(NewsDetail::class, ['routing' => 'f6e416d1-4d65-4d58-8704-856d48b330a3'])
            ->assertSee('Correlation unavailable')->assertSee('Human Review');
    }

    public function test_wrong_input_or_unlinked_candidate_fails_closed(): void
    {
        Http::preventStrayRequests();
        $row = $this->correlation();
        $row['event']['candidate_ids'] = ['other'];
        Http::fake(['http://event-research:8011/documents/*/correlation' => Http::response([$row])]);

        $response = app(CorrelationClient::class)->forDocument($row['document']['document_id'], $row['document']['input_message_id']);
        $this->assertFalse($response['ok']);
        $this->assertSame([], $response['data']);
    }

    public function test_no_result_is_explicit(): void
    {
        $this->actingAs(User::factory()->create());
        Http::preventStrayRequests();
        Http::fake(['http://article-router:8010/*' => Http::response($this->article()),
            'http://event-research:8011/documents/*/correlation' => Http::response([]),
            'http://event-research:8011/documents/*/comparison' => Http::response([])]);

        Livewire::test(NewsDetail::class, ['routing' => 'f6e416d1-4d65-4d58-8704-856d48b330a3'])
            ->assertSee('No correlation result for this exact document input.');
    }
}
