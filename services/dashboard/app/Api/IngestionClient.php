<?php

namespace App\Api;

class IngestionClient extends ApiClient
{
    protected string $service = 'ingestion';

    public function sources(): array
    {
        return $this->get('/sources', list: true);
    }
}
