<?php

return [
    'timeout' => 3, 'cache_seconds' => 5, 'catalogue_limit' => 1000,
    'article_review_token' => env('ARTICLE_ROUTER_REVIEW_TOKEN', ''),
    'semantic_review_token' => env('ARTICLE_SEMANTIC_REVIEW_TOKEN', ''),
    'services' => [
        'article-semantic' => env('ARTICLE_SEMANTIC_URL', 'http://article-semantic:8012'),
        'event-research' => env('EVENT_RESEARCH_URL', 'http://event-research:8011'),
        'article-router' => env('ARTICLE_ROUTER_URL', 'http://article-router:8010'),
        'ingestion' => env('INGESTION_URL', 'http://ingestion:8000'),
        'enrichment' => env('ENRICHMENT_URL', 'http://enrichment:8001'),
        'events' => env('EVENTS_URL', 'http://events:8002'),
        'market-data' => env('MARKET_DATA_URL', 'http://market-data:8003'),
        'market-context' => env('MARKET_CONTEXT_URL', 'http://market-context:8004'),
        'llm-analysis' => env('LLM_ANALYSIS_URL', 'http://llm-analysis:8005'),
        'evaluation' => env('EVALUATION_URL', 'http://evaluation:8007'),
        'document-intelligence' => env('DOCUMENT_INTELLIGENCE_URL', 'http://document-intelligence:8009'),
        'event-intelligence' => env('EVENT_INTELLIGENCE_URL', 'http://event-intelligence:8008'),
    ],
];
