<?php

namespace App\Api;

class CorrelationClient extends ApiClient
{
    protected string $service = 'event-research';

    public function forDocument(string $documentId, string $messageId, ?string $intelligenceId = null): array
    {
        $response = $this->get('/documents/'.rawurlencode($documentId).'/correlation', list: true);
        if (! $response['ok']) {
            return $response;
        }
        $rows = [];
        foreach ($response['data'] as $row) {
            $event = $row['event'] ?? [];
            if (data_get($row, 'document.document_id') !== $documentId
                || data_get($row, 'document.input_message_id') !== $messageId
                || ($event['mode'] ?? null) !== 'research'
                || ($event['production_canonical'] ?? null) !== false
                || ! is_array($row['fingerprint'] ?? null)
                || ! is_array($row['decisions'] ?? null)
                || ! is_array($row['suggestions'] ?? null)
                || ! is_array($event['documents'] ?? null)
                || ! is_int($event['document_count'] ?? null)
                || ! is_int($event['independent_source_count'] ?? null)
                || ! in_array($row['candidate_id'] ?? null, $event['candidate_ids'] ?? [], true)
                || ! in_array($documentId, array_column($event['documents'], 'document_id'), true)) {
                return [...$response, 'ok' => false, 'data' => [], 'error' => 'Correlation provenance mismatch'];
            }
            if ($intelligenceId === null || data_get($row, 'document.intelligence_id') === $intelligenceId) {
                $rows[] = $row;
            }
        }

        return [...$response, 'data' => $rows];
    }
}
