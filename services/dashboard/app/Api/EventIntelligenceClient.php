<?php

namespace App\Api;

class EventIntelligenceClient extends ApiClient
{
    protected string $service = 'event-intelligence';

    public function forEvent(string $id, int $revision): array
    {
        $result = $this->get('/events/'.rawurlencode($id).'/intelligence', ['event_revision' => $revision, 'limit' => 100], list: true);
        if ($result['ok']) {
            foreach ($result['data'] as $item) {
                if (data_get($item, 'event.event_id') !== $id || data_get($item, 'event.event_revision') !== $revision || ! is_string($item['intelligence_id'] ?? null)
                    || ! in_array($item['relevance'] ?? null, ['none', 'low', 'medium', 'high'], true)
                    || ! in_array($item['novelty'] ?? null, ['new', 'update', 'duplicate_like', 'unknown'], true)
                    || ! in_array($item['information_quality'] ?? null, ['low', 'medium', 'high'], true)
                    || ! in_array($item['event_specificity'] ?? null, ['specific', 'general', 'commentary', 'unknown'], true)
                    || ! in_array(data_get($item, 'surprise.status'), ['available', 'unavailable', 'not_applicable'], true)
                    || ! is_array($item['expectations'] ?? null) || ! is_string(data_get($item, 'basis.ruleset_version'))) {
                    return [...$result, 'ok' => false, 'data' => [], 'error' => 'Malformed or mismatched intelligence response'];
                }
            }
        }

        return $result;
    }
}
