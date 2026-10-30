<?php

namespace App\Api;

use Illuminate\Support\Facades\Http;

class ArticleSemanticClient extends ApiClient
{
    protected string $service = 'article-semantic';

    public function forDocument(string $documentId, string $inputMessageId, string $intelligenceId): array
    {
        $response = $this->get('/documents/'.rawurlencode($documentId).'/insight', list: true);
        if (! $response['ok']) {
            return $response;
        }
        $rows = [];
        foreach ($response['data'] as $row) {
            $insight = $row['insight'] ?? [];
            if (data_get($insight, 'document.document_id') !== $documentId
                || data_get($insight, 'document.input_message_id') !== $inputMessageId
                || ! is_array($insight['key_claims'] ?? null) || ! is_array($insight['affected_assets'] ?? null)
                || ! is_array($insight['provenance'] ?? null) || ! is_array($row['review'] ?? null)) {
                return [...$response, 'ok' => false, 'data' => [], 'error' => 'Article Insight provenance mismatch'];
            }
            if (data_get($insight, 'document.intelligence_id') === $intelligenceId) {
                $rows[] = $row;
            }
        }

        return [...$response, 'data' => $rows];
    }

    public function saveLabel(string $id, array $payload): array
    {
        $start = microtime(true);
        try {
            $response = Http::acceptJson()->withToken(config('upstreams.semantic_review_token'))
                ->connectTimeout(1)->timeout(config('upstreams.timeout'))->withoutRedirecting()
                ->post(rtrim(config('upstreams.services.article-semantic'), '/').'/reviews/'.rawurlencode($id).'/labels', $payload);

            return self::decode($response, [], false, $start);
        } catch (\Throwable $e) {
            return self::failure('Semantic review save uncertain; retry unchanged or reload.', $start);
        }
    }
}
