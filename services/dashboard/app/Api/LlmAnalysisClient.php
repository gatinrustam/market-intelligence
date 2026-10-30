<?php

namespace App\Api;

class LlmAnalysisClient extends ApiClient
{
    protected string $service = 'llm-analysis';

    public function all(): array
    {
        return $this->catalogue('/analyses');
    }

    public function analysis(string $id): array
    {
        return $this->get('/analyses/'.rawurlencode($id), required: ['analysis_id', 'analysis_status', 'configuration', 'runs']);
    }
}
