<?php

namespace App\Api;

class EventResearchClient extends ApiClient
{
    protected string $service = 'event-research';

    public function forDocument(string $id, string $messageId, ?string $intelligenceId = null): array
    {
        $response = $this->get('/documents/'.rawurlencode($id).'/comparison', list: true);
        if (! $response['ok']) {
            return $response;
        }
        $rows = [];
        foreach ($response['data'] as $row) {
            $result = $row['result'] ?? [];
            $comparison = $row['comparison'] ?? [];
            if (data_get($result, 'document.document_id') !== $id || data_get($result, 'document.input_message_id') !== $messageId
                || ($result['mode'] ?? null) !== 'research' || ($result['production_canonical'] ?? null) !== false || ($result['merge_enabled'] ?? null) !== false
                || ! is_array($result['candidates'] ?? null) || ! is_array($result['conflicts'] ?? null) || ! is_array($result['basis'] ?? null)
                || ($comparison['document_id'] ?? null) !== $id
                || ($comparison['research_id'] ?? null) !== ($result['research_id'] ?? null)
                || ! is_array($comparison['flags'] ?? null) || ! is_array($comparison['human_evaluation'] ?? null)) {
                return [...$response, 'ok' => false, 'data' => [], 'error' => 'Research comparison provenance mismatch'];
            }
            if ($intelligenceId === null || data_get($result, 'document.intelligence_id') === $intelligenceId) {
                $rows[] = $row;
            }
        }

        return [...$response, 'data' => $rows];
    }
}
