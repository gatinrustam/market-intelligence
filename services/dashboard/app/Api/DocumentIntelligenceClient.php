<?php

namespace App\Api;

class DocumentIntelligenceClient extends ApiClient
{
    protected string $service = 'document-intelligence';

    public function forDocument(string $id, string $messageId, string $body): array
    {
        $result = $this->get('/documents/'.rawurlencode($id).'/intelligence', ['limit' => 100], list: true);
        if (! $result['ok']) {
            return $result;
        }
        foreach ($result['data'] as $item) {
            $valid = data_get($item, 'document.document_id') === $id
                && data_get($item, 'document.input_message_id') === $messageId
                && data_get($item, 'document.body_hash') === hash('sha256', $body)
                && in_array($item['language'] ?? null, ['en', 'ru', 'unsupported'], true)
                && in_array(data_get($item, 'processing.status'), ['complete', 'partial', 'unsupported'], true)
                && is_array($item['extraction'] ?? null);
            foreach (['entities', 'measurements', 'dates', 'relations', 'facts', 'topics'] as $field) {
                if (! is_array($item[$field] ?? null)) {
                    $valid = false;
                    break;
                }
                foreach ($item[$field] as $value) {
                    $evidence = $value['evidence'] ?? [];
                    $start = $evidence['start_char'] ?? null;
                    $end = $evidence['end_char'] ?? null;
                    if (! is_int($start) || ! is_int($end) || $start < 0 || $end <= $start || $end > mb_strlen($body)
                        || ($evidence['document_id'] ?? null) !== $id || ! is_int($evidence['sentence_id'] ?? null)
                        || mb_substr($body, $start, $end - $start) !== ($evidence['text'] ?? null)
                        || ! is_string(data_get($value, 'extraction.rule_id')) || ! is_string(data_get($value, 'extraction.extractor'))
                        || ! is_string(data_get($value, 'extraction.extractor_version'))) {
                        $valid = false;
                        break;
                    }
                }
            }
            if (! $valid) {
                return [...$result, 'ok' => false, 'data' => [], 'error' => 'Document intelligence evidence mismatch'];
            }
        }

        return $result;
    }
}
