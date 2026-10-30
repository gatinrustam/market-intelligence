<?php

namespace App\Api;

class EnrichmentClient extends ApiClient
{
    protected string $service = 'enrichment';

    public function sources(): array
    {
        return $this->get('/sources', list: true);
    }

    public function document(string $id): array
    {
        return $this->get('/documents/'.rawurlencode($id), required: ['document_id', 'content', 'enrichment', 'fetch']);
    }
}
