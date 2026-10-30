<?php

namespace Tests\Unit;

use App\Research\NewsPresentation;
use Tests\TestCase;

class NewsPresentationTest extends TestCase
{
    public function test_summary_is_extractive_and_rejected_topics_are_not_reintroduced(): void
    {
        $article = json_decode(file_get_contents(base_path('tests/Fixtures/article.json')), true);
        $article['snapshot']['events'] = [];
        $article['snapshot']['document']['source']['url'] = 'javascript:alert(1)';
        $insight = ['main_topics' => ['interest_rates'], 'key_claims' => [['evidence' => ['text' => 'Exact supported source quote.']]], 'affected_assets' => [], 'reranking' => ['decisions' => [['concept_id' => 'etf', 'decision' => 'rejected']]]];
        $p = NewsPresentation::present($article, ['ok' => true, 'data' => [['insight' => $insight]]]);
        $this->assertSame('Exact supported source quote.', $p['summary']);
        $this->assertSame(['interest_rates'], $p['topics']);
        $this->assertSame([], $p['assets']);
        $this->assertNull($p['url']);
        $this->assertSame($article['snapshot']['intelligence']['facts'][0]['evidence']['text'], $p['facts'][0]['text']);
    }

    public function test_wrong_input_event_is_not_used_and_missing_semantics_falls_back_to_body(): void
    {
        $article = json_decode(file_get_contents(base_path('tests/Fixtures/article.json')), true);
        $article['snapshot']['events'][0]['evidence']['documents'][0]['input_message_id'] = 'another-revision';
        $p = NewsPresentation::present($article, ['ok' => false, 'data' => []]);
        $this->assertNull($p['event']);
        $this->assertStringContainsString('Federal Reserve', $p['summary']);
        $this->assertNotEmpty($p['facts']);
    }

    public function test_decision_display_rejects_future_stale_and_outcome_points(): void
    {
        $base = ['offset_seconds' => 0, 'available' => true, 'price' => '100', 'price_at' => '2026-04-29T17:59:59Z', 'target_at' => '2026-04-29T18:00:00Z', 'age_seconds' => 1, 'max_age_seconds' => 60];
        $points = [$base, [...$base, 'price_at' => '2026-04-29T18:00:01Z'], [...$base, 'age_seconds' => 61], [...$base, 'offset_seconds' => 60], [...$base, 'available' => false], [...$base, 'target_at' => '2026-04-29T18:01:00Z']];
        $decision = ['ok' => true, 'data' => ['decision_at' => '2026-04-29T18:00:00Z', 'points' => $points]];
        $this->assertSame([$base], NewsPresentation::causalPoints($decision));
        $this->assertSame([], NewsPresentation::causalPoints(['ok' => false]));
    }
}
