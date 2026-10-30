<?php

namespace App\Research;

use App\Api\CorrelationClient;
use App\Api\DocumentIntelligenceClient;
use App\Api\EnrichmentClient;
use App\Api\EvaluationClient;
use App\Api\EventIntelligenceClient;
use App\Api\EventResearchClient;
use App\Api\EventsClient;
use App\Api\IngestionClient;
use App\Api\LlmAnalysisClient;
use App\Api\MarketContextClient;
use App\Api\MarketDataClient;
use Illuminate\Support\Facades\Cache;

class DashboardData
{
    public function __construct(public IngestionClient $ingestion, public EnrichmentClient $enrichment, public EventsClient $events, public MarketDataClient $market, public MarketContextClient $contexts, public LlmAnalysisClient $llm, public EvaluationClient $evaluations, public EventIntelligenceClient $intelligence, public DocumentIntelligenceClient $documentIntelligence) {}

    private function cached(string $key, \Closure $load): array
    {
        return Cache::remember('dashboard-'.$key, config('upstreams.cache_seconds'), $load);
    }

    public function catalogue(): array
    {
        return $this->cached('catalogue', function () {
            $e = $this->events->all();
            $a = $this->llm->all();
            $rows = [];
            $analyses = collect($a['data'])->filter(fn ($x) => is_array($x))->groupBy('event_id');
            foreach ($e['data'] as $item) {
                if (! is_array($item) || ! is_string(data_get($item, 'event.id'))) {
                    continue;
                }
                $id = data_get($item, 'event.id');
                $revision = data_get($item, 'event.revision');
                $latest = $analyses->get($id, collect())->first(fn ($a) => ($a['event_revision'] ?? null) === $revision);
                $rows[$id] = ['id' => $id, 'revision' => $revision, 'title' => data_get($item, 'content.canonical_title', 'Untitled'),
                    'detected_at' => Display::utc(data_get($item, 'time.first_detected_at')), 'event_type' => data_get($item, 'taxonomy.event_type', 'unknown'),
                    'source' => implode(', ', array_unique(array_column(data_get($item, 'evidence.documents', []), 'source_id'))),
                    'jurisdiction' => implode(', ', data_get($item, 'jurisdictions', [])), 'quality' => data_get($item, 'evidence.quality', 'unknown'),
                    'lifecycle' => data_get($item, 'lifecycle.status', 'unknown'), 'llm_status' => ! $a['ok'] ? 'unavailable' : ($latest['analysis_status'] ?? 'not_run')];
            }

            return ['rows' => $rows, 'error' => $e['error'], 'llm_error' => $a['error'], 'truncated' => ($e['truncated'] ?? false) || ($a['truncated'] ?? false)];
        });
    }

    public function analyses(): array
    {
        $result = $this->cached('analyses', fn () => $this->llm->all());
        $titles = $this->catalogue()['rows'];
        $rows = [];
        foreach ($result['data'] as $r) {
            if (! is_array($r) || ! is_string($r['analysis_id'] ?? null)) {
                continue;
            }
            $rows[$r['analysis_id']] = ['id' => $r['analysis_id'], 'event_id' => $r['event_id'] ?? '',
                'event' => $titles[$r['event_id'] ?? '']['title'] ?? ($r['event_id'] ?? 'Unknown event'), 'model' => data_get($r, 'configuration.model', 'Unavailable'),
                'prompt_version' => data_get($r, 'configuration.prompt_version', 'Unavailable'), 'mode' => ($r['basis'] ?? '') === 'live' ? 'LIVE' : 'RESEARCH HYPOTHETICAL',
                'status' => $r['analysis_status'] ?? 'unknown', 'created_at' => Display::utc($r['created_at'] ?? null), 'latency_ms' => $r['latency_ms'] ?? null,
                'token_usage' => Display::text($r['usage'] ?? null), 'revision' => $r['event_revision'] ?? null];
        }

        return ['rows' => $rows, 'error' => $result['error'], 'truncated' => $result['truncated'] ?? false];
    }

    public function overview(): array
    {
        return $this->cached('overview', function () {
            $e = $this->events->stats();
            $d = $this->enrichment->stats();
            $c = $this->contexts->stats();
            $a = $this->llm->stats();

            return ['counters' => ['News' => null, 'Documents' => $d['ok'] ? (is_array($d['data']['documents'] ?? null) ? array_sum($d['data']['documents']) : null) : null, 'Events' => $e['data']['events_total'] ?? null, 'Contexts' => $c['data']['contexts_total'] ?? null, 'Analyses' => $a['ok'] ? (is_array($a['data']['jobs'] ?? null) ? array_sum($a['data']['jobs']) : null) : null],
                'market' => $this->market(), 'errors' => array_filter([$e['error'], $d['error'], $c['error'], $a['error']])];
        });
    }

    public function market(): array
    {
        return $this->cached('market', function () {
            $s = $this->market->stats();
            $at = $s['data']['last_snapshot_at'] ?? null;
            $p = $at ? $this->market->snapshot($at) : ['ok' => false, 'data' => [], 'error' => 'not_collected'];

            return ['stats' => $s['data'], 'realtime' => data_get($p, 'data.realtime', []), 'error' => $s['error'] ?? $p['error'], 'checked_at' => now()->utc()->toIso8601String()];
        });
    }

    public function sources(): array
    {
        $i = $this->ingestion->sources();
        $e = $this->enrichment->sources();
        $rows = [];
        $summary = collect($e['data'])->keyBy('source_id');
        $states = collect($i['data'])->keyBy('id');
        $names = ['fed_monetary_policy' => 'Fed', 'ecb_press' => 'ECB', 'sec_press_releases' => 'SEC', 'cbr_events_ru' => 'Банк России · новости', 'cbr_press_ru' => 'Банк России · пресс-релизы', 'moex_news_ru' => 'Московская биржа'];
        foreach ($states as $id => $state) {
            $names[$id] = $state['name'] ?? NewsPresentation::source($id);
        }
        foreach ($names as $id => $name) {
            $a = $states->get($id, []);
            $b = $summary->get($id, []);
            $partial = ($b['enrichment_states']['partial'] ?? 0) > 0;
            $rows[] = ['source' => $name, 'source_id' => $id, 'health' => $a['status'] ?? 'unavailable', 'last_fetch' => Display::utc($a['last_success_at'] ?? null),
                'documents_count' => $b['documents_count'] ?? null, 'enrichment' => $partial ? 'partial / RSS fallback' : Display::text($b['enrichment_states'] ?? null),
                'errors' => Display::text(array_filter(['collector' => $a['last_error_type'] ?? null, 'enrichment' => $b['errors'] ?? null]))];
        }

        return ['rows' => $rows, 'errors' => array_filter([$i['error'], $e['error']])];
    }

    public function event(string $id, string $basis): array
    {
        $event = $this->events->event($id);
        $canonical = $event['data'];
        $contextResult = $this->contexts->contexts($id);
        $context = collect($contextResult['data'])->first(fn ($c) => data_get($c, 'event.event_revision') === data_get($canonical, 'event.revision'));
        $decision = $context ? $this->contexts->decision($context['context_id'], $basis) : ['ok' => false, 'data' => [], 'error' => $contextResult['error'] ?? 'No context for this event revision'];
        $documents = [];
        foreach (data_get($canonical, 'evidence.documents', []) as $ref) {
            // Stage 2 immutable input is pinned to the exact canonical revision.
            $response = $this->events->input($ref['document_id']);
            $doc = $response['data']['document'] ?? null;
            if ($doc && ($doc['message_id'] ?? null) !== $ref['input_message_id']) {
                $doc = null;
                $response['error'] = 'Evidence revision mismatch';
            }
            $documents[] = ['correlation' => app(CorrelationClient::class)->forDocument($ref['document_id'], $ref['input_message_id']), 'comparison' => app(EventResearchClient::class)->forDocument($ref['document_id'], $ref['input_message_id']), 'reference' => $ref, 'document' => $doc, 'error' => $response['error'], 'intelligence' => $doc ? $this->documentIntelligence->forDocument($ref['document_id'], $ref['input_message_id'], $doc['content']['body']) : ['ok' => false, 'data' => [], 'error' => 'Exact document unavailable']];
        }
        $all = $this->llm->all();
        $analyses = [];
        foreach ($all['data'] as $a) {
            if (($a['event_id'] ?? null) === $id && ($a['event_revision'] ?? null) === data_get($canonical, 'event.revision')) {
                $analyses[] = $this->llm->analysis($a['analysis_id']);
            }
        }

        return compact('event', 'canonical', 'context', 'decision', 'documents', 'analyses') + [
            'llm_error' => $all['error'],
            'evaluations' => $this->evaluations->forEvent($id),
            'intelligence' => $this->intelligence->forEvent($id, (int) data_get($canonical, 'event.revision', 1)),
        ];
    }

    public function evaluationMetrics(string $origin): array
    {
        return $this->cached('evaluation-metrics-'.$origin, function () use ($origin) {
            $result = [];
            foreach (['horizon', 'confidence', 'event_type'] as $group) {
                $result[$group] = $this->evaluations->metrics($group, $origin);
            }

            return $result;
        });
    }
}
