<?php

namespace App\Api;

use Illuminate\Support\Facades\Http;

class ArticleRouterClient extends ApiClient
{
    protected string $service = 'article-router';

    public function articles(): array
    {
        return $this->catalogue('/articles');
    }

    public function article(string $id): array
    {
        return $this->get('/articles/'.rawurlencode($id), [], ['machine', 'snapshot', 'configuration', 'review', 'labels']);
    }

    public function saveLabel(string $id, array $payload): array
    {
        $start = microtime(true);
        $token = config('upstreams.article_review_token');
        if (! is_string($token) || $token === '') {
            return self::failure('Review writes are not configured', $start);
        }
        try {
            $response = Http::acceptJson()->withToken($token)->connectTimeout(1)->timeout(config('upstreams.timeout'))->withoutRedirecting()
                ->post(rtrim(config('upstreams.services.article-router'), '/').'/reviews/'.rawurlencode($id).'/labels', $payload);

            $result = self::decode($response, [], false, $start);
            if ($result['ok'] && (! is_int($result['data']['revision'] ?? null) || ! is_string($result['data']['request_id'] ?? null))) {
                return self::failure('Uncertain review response; retry the same review', $start);
            }

            return $result;
        } catch (\Throwable $e) {
            return self::failure('Review service unavailable; retry the same review', $start);
        }
    }
}
