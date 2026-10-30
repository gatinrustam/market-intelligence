<?php

namespace Tests\Feature;

use App\Api\EnrichmentClient;
use App\Api\EventsClient;
use App\Api\IngestionClient;
use App\Api\LlmAnalysisClient;
use App\Api\MarketContextClient;
use App\Api\MarketDataClient;
use App\Filament\Pages\Analyses;
use App\Filament\Pages\Evaluations;
use App\Filament\Pages\EventDetail;
use App\Filament\Pages\Events;
use App\Models\User;
use App\Research\Health;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Client\Factory;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Http;
use Livewire\Livewire;
use Tests\TestCase;

class ResearchTest extends TestCase
{
    use RefreshDatabase;

    private array $fixtures;

    private array $event;

    private array $decision;

    private string $eventId = 'd9b482b8-af7e-4fc9-970a-52b30196142e';

    private string $analysisId = '62d87b87-c182-584a-bc82-a57e3e44ae93';

    private string $llmStatus = 'not_run';

    private bool $llmDown = false;

    private bool $evaluationDown = false;

    private array $evaluationFixtures = [];

    private array $intelligenceFixtures = [];

    private bool $intelligenceDown = false;

    private array $documentIntelligenceFixtures = [];

    private bool $documentIntelligenceDown = false;

    protected function setUp(): void
    {
        parent::setUp();
        Cache::flush();
        $this->fixtures = json_decode(file_get_contents(base_path('tests/Fixtures/upstream.json')), true);
        $this->event = $this->fixtures['events/events/'.$this->eventId];
        $this->decision = $this->fixtures['market-context/contexts/c8e6b183-983a-5509-b7a5-7da8962fbe95/decision?basis=research_hypothetical'];
        $this->actingAs(User::factory()->create());
        Http::preventStrayRequests();
        Http::fake(function ($request) {
            $host = parse_url($request->url(), PHP_URL_HOST);
            $path = parse_url($request->url(), PHP_URL_PATH);
            parse_str(parse_url($request->url(), PHP_URL_QUERY) ?? '', $query);
            if ($host === 'document-intelligence' && str_ends_with($path, '/intelligence')) {
                return Http::response($this->documentIntelligenceFixtures, $this->documentIntelligenceDown ? 503 : 200);
            }
            if ($host === 'event-intelligence' && str_ends_with($path, '/intelligence')) {
                return Http::response($this->intelligenceFixtures, $this->intelligenceDown ? 503 : 200);
            }
            if ($host === 'evaluation') {
                if ($this->evaluationDown) {
                    return Http::response([], 503);
                }
                if ($path === '/metrics') {
                    $rows = ($query['origin'] ?? 'model') === 'fixture' ? [['group' => [$query['group_by'] => 'test-group', 'decision_basis' => 'source_published_at', 'policy_hash' => str_repeat('a', 64)], 'n' => 2, 'hits' => 1, 'misses' => 1, 'not_scored' => 1, 'unavailable' => 0, 'pending' => 0, 'direction_accuracy_pct' => '50.000000']] : [];

                    return Http::response(['rows' => $rows]);
                }
                if (str_ends_with($path, '/evaluations')) {
                    return Http::response($this->evaluationFixtures);
                }
            }
            if ($host === 'llm-analysis' && $this->llmDown) {
                return Http::response(['detail' => 'unavailable'], 503);
            }
            if ($path === '/health') {
                return Http::response(['status' => 'alive']);
            }
            if ($path === '/ready') {
                return Http::response(['database' => true, 'workers' => true, 'jetstream' => true]);
            }
            if ($host === 'events' && $path === '/events') {
                return Http::response(['items' => [$this->event], 'total' => 1, 'offset' => 0, 'limit' => 100]);
            }
            if ($host === 'events' && $path === '/events/'.$this->eventId) {
                return Http::response($this->event);
            }
            if ($host === 'events' && str_ends_with($path, '/input')) {
                return Http::response(['document' => $this->decision['known_information']['evidence'][0]['document']]);
            }
            if ($host === 'enrichment' && $path === '/sources') {
                return Http::response([['source_id' => 'sec_press_releases', 'documents_count' => 25, 'enrichment_states' => ['partial' => 25], 'errors' => ['http_403' => 25]]]);
            }
            if ($host === 'market-context' && str_ends_with($path, '/decision')) {
                $d = $this->decision;
                $d['historical_simulation'] = ($query['basis'] ?? 'live') === 'research_hypothetical';
                $d['decision_mode'] = $query['basis'] ?? 'live';

                return Http::response($d);
            }
            if ($host === 'llm-analysis' && $path === '/analyses') {
                return Http::response(['items' => $this->llmStatus === 'not_run' ? [] : [$this->summary()], 'total' => $this->llmStatus === 'not_run' ? 0 : 1]);
            }
            if ($host === 'llm-analysis' && $path === '/analyses/'.$this->analysisId) {
                return Http::response($this->analysis());
            }
            if ($host === 'market-data' && $path === '/market/snapshot') {
                return Http::response(['realtime' => ['available' => true, 'last_trade_price' => '100', 'best_bid' => '99', 'best_ask' => '101', 'spread_bps' => '2'], 'candle_1m' => ['available' => false]]);
            }
            if (isset($this->fixtures[$host.$path])) {
                return Http::response($this->fixtures[$host.$path]);
            }
            if ($path === '/stats') {
                return Http::response(['jobs' => []]);
            }

            return Http::response([], 404);
        });
    }

    private function summary(): array
    {
        return ['analysis_id' => $this->analysisId, 'event_id' => $this->eventId, 'event_revision' => 1, 'analysis_status' => $this->llmStatus, 'basis' => 'research_hypothetical', 'created_at' => '2026-09-20T00:00:00Z', 'configuration' => ['model' => 'gpt-6-astra', 'prompt_version' => 'btc_event_analysis_v1'], 'latency_ms' => 300, 'usage' => ['input_tokens' => 100, 'output_tokens' => 200]];
    }

    private function analysis(): array
    {
        return [...$this->summary(), 'error' => $this->llmStatus === 'blocked' ? 'market_decision_not_ready' : null, 'runs' => [['attempt' => 1, 'status' => $this->llmStatus, 'response_audit' => ['latency_ms' => 300, 'usage' => ['input_tokens' => 100, 'output_tokens' => 200]]]], 'analysis' => $this->llmStatus !== 'completed' ? null : ['asset' => ['relevance' => 'medium'], 'interpretation' => ['summary' => 'Fixture summary only', 'market_mechanism' => 'Fixture mechanism'], 'forecast' => array_map(fn ($n) => ['horizon_seconds' => $n, 'direction' => 'unclear', 'impact' => 'small', 'confidence' => 'low'], [60, 300, 900, 3600]), 'uncertainties' => ['Historical simulation, content unverified']]];
    }

    public function test_authentication_required_on_all_pages(): void
    {
        auth()->logout();
        foreach (['overview', 'events', 'analyses', 'evaluations', 'market', 'sources', 'system', 'events/'.$this->eventId, 'analyses/'.$this->analysisId] as $page) {
            $this->get('/admin/'.$page)->assertRedirect('/admin/login');
        }
        Http::assertNothingSent();
        $this->get('/admin/login')->assertOk();
    }

    public function test_overview_renders_six_services(): void
    {
        $this->get('/admin/overview')->assertOk()->assertSee('Pipeline')->assertSee('llm-analysis')->assertSee('BTCUSDT');
    }

    public function test_events_table_renders_and_filters(): void
    {
        Livewire::test(Events::class)->assertSee('Federal Reserve issues FOMC statement')->searchTable('not-existing')->assertDontSee('Federal Reserve issues FOMC statement')->searchTable('Federal Reserve')->assertSee('Federal Reserve issues FOMC statement')->filterTable('quality', 'low')->assertDontSee('Federal Reserve issues FOMC statement');
    }

    public function test_event_detail_separates_causal_and_outcomes(): void
    {
        $this->get('/admin/events/'.$this->eventId)->assertOk()->assertSee('CAUSAL')->assertSee('OUTCOMES')->assertSee('event-time anchored')->assertSee('Copy ID')->assertSee('first 1,000 characters');
    }

    public function test_historical_and_live_badges(): void
    {
        Livewire::test(EventDetail::class, ['event' => $this->eventId])->assertSee('LIVE')->set('basis', 'research_hypothetical')->assertSee('RESEARCH HYPOTHETICAL')->assertSee('source_published_at');
    }

    public function test_unavailable_market_reason_visible_without_price(): void
    {
        $this->decision['points'][2] = [...$this->decision['points'][2], 'available' => false, 'reason' => 'stale_market_data', 'price' => 'SENTINEL_STALE_PRICE', 'price_at' => null, 'age_seconds' => 99];
        $this->decision['market_data_status'] = 'market_data_unavailable';
        $this->get('/admin/events/'.$this->eventId)->assertOk()->assertSee('stale_market_data')->assertSee('market_data_unavailable')->assertDontSee('SENTINEL_STALE_PRICE');
    }

    public function test_llm_not_run(): void
    {
        $this->get('/admin/events/'.$this->eventId)->assertOk()->assertSee('Not run');
    }

    public function test_llm_blocked(): void
    {
        $this->llmStatus = 'blocked';
        $this->get('/admin/events/'.$this->eventId)->assertOk()->assertSee('market_decision_not_ready');
    }

    public function test_llm_completed_fixture(): void
    {
        $this->llmStatus = 'completed';
        $this->get('/admin/analyses/'.$this->analysisId)->assertOk()->assertSee('Fixture summary only')->assertSee('Fixture mechanism')->assertSee('not a calibrated probability')->assertSee('input_tokens');
    }

    public function test_analyses_table_filters(): void
    {
        $this->llmStatus = 'blocked';
        Livewire::test(Analyses::class)->assertSee('gpt-6-astra')->filterTable('status', 'completed')->assertCountTableRecords(0);
    }

    public function test_backend_outage_isolated(): void
    {
        $this->llmDown = true;
        $this->get('/admin/events')->assertOk()->assertSee('Federal Reserve issues FOMC statement')->assertSee('LLM Analysis');
        $this->get('/admin/events/'.$this->eventId)->assertOk()->assertSee('LLM Analysis unavailable');
        $this->get('/admin/market')->assertOk()->assertSee('BTCUSDT');
        $rows = collect(app(Health::class)->all())->keyBy('service');
        $this->assertSame('unavailable', $rows['llm-analysis']['status']);
        $this->assertSame('healthy', $rows['events']['status']);
    }

    public function test_sources_partial_fallback(): void
    {
        $this->get('/admin/sources')->assertOk()->assertSee('partial / RSS fallback')->assertSee('http_403')->assertSee('Банк России · новости')->assertSee('Банк России · пресс-релизы')->assertSee('Московская биржа');
    }

    public function test_system_renders(): void
    {
        $this->get('/admin/system')->assertOk()->assertSee('Last checked')->assertSee('http://events:8002');
    }

    public function test_all_upstream_calls_are_get(): void
    {
        foreach (['overview', 'events', 'analyses', 'evaluations', 'market', 'sources', 'system', 'events/'.$this->eventId] as $page) {
            $this->get('/admin/'.$page)->assertOk();
        }
        Http::assertNotSent(fn ($request) => $request->method() !== 'GET');
    }

    public function test_api_client_normalizes_and_empty_data(): void
    {
        $this->assertTrue(app(EventsClient::class)->all()['ok']);
        $this->assertCount(1, app(EventsClient::class)->all()['data']);
        $this->assertSame([], app(LlmAnalysisClient::class)->all()['data']);
        $this->assertTrue(app(IngestionClient::class)->sources()['ok']);
        $this->assertTrue(app(EnrichmentClient::class)->sources()['ok']);
        $this->assertTrue(app(MarketDataClient::class)->stats()['ok']);
        $this->assertTrue(app(MarketContextClient::class)->contexts($this->eventId)['ok']);
    }

    public function test_malformed_response_fallback(): void
    {
        Http::swap(new Factory);
        Http::fake(['*' => Http::response('<html>oops</html>', 200)]);
        $this->assertFalse(app(EventsClient::class)->all()['ok']);
        $this->get('/admin/events')->assertOk()->assertSee('Malformed response');
    }

    public function test_connection_failure_fallback(): void
    {
        Http::swap(new Factory);
        Http::fake(['*' => Http::failedConnection()]);
        $this->assertFalse(app(EventsClient::class)->all()['ok']);
        $this->get('/admin/overview')->assertOk()->assertSee('Service unavailable');
    }

    public function test_evidence_is_escaped(): void
    {
        $this->event['content']['canonical_title'] = '<script>alert("injected")</script>';
        $this->get('/admin/events/'.$this->eventId)->assertOk()->assertDontSee('<script>alert("injected")</script>', false)->assertSee('&lt;script&gt;', false);
    }

    public function test_invalid_identifier_does_not_call_upstream(): void
    {
        $this->get('/admin/events/not-a-uuid')->assertNotFound();
        Http::assertNothingSent();
    }

    public function test_no_upstream_write_routes(): void
    {
        $this->post('/admin/events/'.$this->eventId, ['edit' => true])->assertStatus(405);
        Http::assertNothingSent();
    }

    public function test_nested_malformed_event_is_unavailable(): void
    {
        $this->event['evidence']['documents'] = 'broken';
        $this->get('/admin/events')->assertOk()->assertSee('Malformed events response');
        $this->get('/admin/events/'.$this->eventId)->assertOk()->assertSee('Malformed event response');
    }

    public function test_outcome_in_decision_rejected(): void
    {
        $this->decision['points'][] = [...$this->decision['points'][2], 'offset_seconds' => 60];
        $this->get('/admin/events/'.$this->eventId)->assertOk()->assertSee('Malformed or mismatched decision response');
    }

    public function test_evaluation_metrics_default_excludes_fixtures_and_shows_sample_size(): void
    {
        Livewire::test(Evaluations::class)
            ->assertSee('n = 0')->assertDontSee('50.000000')
            ->set('origin', 'fixture')->assertSee('FIXTURE DATA')->assertSee('n · scored')->assertSee('50.000000')->assertSee('Not scored');
        Http::assertNotSent(fn ($request) => $request->method() !== 'GET');
    }

    public function test_evaluation_outage_does_not_break_event_or_market(): void
    {
        $this->evaluationDown = true;
        $this->get('/admin/events/'.$this->eventId)->assertSee('Evaluation unavailable')->assertSee('Federal Reserve issues FOMC statement');
        $this->get('/admin/evaluations')->assertSee('Evaluation unavailable');
        $this->get('/admin/market')->assertSee('BTCUSDT');
    }

    public function test_evaluation_detail_labels_fixture_and_separates_horizons(): void
    {
        $this->evaluationFixtures = [['evaluation_id' => '5cc45bed-42d1-5b5a-ac3f-09b88420c2b4', 'revision' => 2,
            'analysis' => ['analysis_id' => $this->analysisId, 'event_revision' => 1, 'model' => 'fixture/test'],
            'provenance' => ['origin' => 'fixture', 'fixture_label' => 'stage5-fixture'],
            'results' => array_map(fn ($n) => ['horizon_seconds' => $n, 'forecast' => ['direction' => 'unclear', 'impact' => 'small', 'confidence' => 'low'], 'status' => 'not_scored', 'actual' => ['return_pct' => '-0.18', 'direction' => 'down', 'impact' => 'small'], 'evaluation' => ['direction_result' => 'not_scored', 'impact_match' => true]], [60, 300, 900, 3600])]];
        $this->get('/admin/events/'.$this->eventId)->assertSee('FIXTURE — not a model result')->assertSee('-0.18')->assertSee('not_scored')->assertSee('60m')->assertSee('Evaluation revision');
    }

    public function test_intelligence_fields_for_exact_revision_are_read_only(): void
    {
        $this->intelligenceFixtures = [['intelligence_id' => '8c37d13b-5b5f-4f65-8449-e025e6d70da2', 'event' => ['event_id' => $this->eventId, 'event_revision' => 1],
            'relevance' => 'high', 'novelty' => 'new', 'information_quality' => 'high', 'event_specificity' => 'specific',
            'surprise' => ['status' => 'unavailable'], 'expectations' => ['source' => null], 'basis' => ['ruleset_version' => '1.0', 'matched_rule_ids' => ['fed.policy']]]];

        $this->get('/admin/events/'.$this->eventId)->assertSee('Event Intelligence')->assertSee('BTC relevance')->assertSee('specific')->assertSee('Unavailable — no consensus provider')->assertSee('fed.policy');
        Http::assertSent(fn ($request) => parse_url($request->url(), PHP_URL_HOST) === 'event-intelligence' && str_contains($request->url(), '/intelligence') && $request['event_revision'] === 1);
        Http::assertNotSent(fn ($request) => $request->method() !== 'GET');
    }

    public function test_intelligence_outage_does_not_hide_event(): void
    {
        $this->intelligenceDown = true;

        $this->get('/admin/events/'.$this->eventId)->assertSee('Event Intelligence unavailable')->assertSee('Federal Reserve issues FOMC statement');
    }

    public function test_intelligence_wrong_revision_is_not_shown(): void
    {
        $this->intelligenceFixtures = [['event' => ['event_id' => $this->eventId, 'event_revision' => 99], 'relevance' => 'forbidden-revision']];

        $this->get('/admin/events/'.$this->eventId)->assertSee('Malformed or mismatched intelligence response')->assertDontSee('forbidden-revision');
    }

    private function documentIntelligenceFixture(): array
    {
        $doc = $this->decision['known_information']['evidence'][0]['document'];
        $body = $doc['content']['body'];
        $text = mb_substr($body, 0, 30);
        $fact = ['fact_type' => 'monetary_policy.rate_decision', 'action' => 'hold', 'values' => [],
            'evidence' => ['document_id' => $doc['document_id'], 'sentence_id' => 0, 'start_char' => 0, 'end_char' => 30, 'text' => $text],
            'extraction' => ['extractor' => 'domain_facts', 'rule_id' => 'rate.hold.v1', 'extractor_version' => '1.0']];

        return ['document' => ['document_id' => $doc['document_id'], 'input_message_id' => $doc['message_id'], 'body_hash' => hash('sha256', $body)],
            'language' => 'en', 'processing' => ['status' => 'complete', 'warnings' => []],
            'extraction' => ['pipeline_version' => '1.0', 'entity_registry_version' => '1.0', 'fact_ruleset_version' => '1.0'],
            'entities' => [], 'measurements' => [], 'dates' => [], 'relations' => [], 'facts' => [$fact], 'topics' => []];
    }

    public function test_document_intelligence_shows_exact_highlight_and_read_only_basis(): void
    {
        $this->documentIntelligenceFixtures = [$this->documentIntelligenceFixture()];

        $this->get('/admin/events/'.$this->eventId)->assertSee('Document Intelligence')->assertSee('rate.hold.v1')->assertSee('monetary_policy.rate_decision')->assertSee('<mark ', false);
        Http::assertNotSent(fn ($request) => $request->method() !== 'GET');
    }

    public function test_document_intelligence_rejects_mismatched_evidence(): void
    {
        $value = $this->documentIntelligenceFixture();
        $value['facts'][0]['evidence']['text'] = 'invented fragment';
        $this->documentIntelligenceFixtures = [$value];

        $this->get('/admin/events/'.$this->eventId)->assertSee('Document intelligence evidence mismatch')->assertDontSee('invented fragment');
    }

    public function test_document_intelligence_escapes_source_fragment(): void
    {
        $this->decision['known_information']['evidence'][0]['document']['content']['body'] = '<script>alert("xss")</script> extra article content';
        $this->documentIntelligenceFixtures = [$this->documentIntelligenceFixture()];

        $this->get('/admin/events/'.$this->eventId)->assertSee('&lt;script&gt;', false)->assertDontSee('<script>alert("xss")</script>', false);
    }

    public function test_document_intelligence_outage_preserves_event_page(): void
    {
        $this->documentIntelligenceDown = true;

        $this->get('/admin/events/'.$this->eventId)->assertSee('Document Intelligence unavailable')->assertSee('Federal Reserve issues FOMC statement');
    }
}
