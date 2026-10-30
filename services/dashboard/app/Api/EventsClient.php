<?php

namespace App\Api;

class EventsClient extends ApiClient
{
    protected string $service = 'events';

    private function validEvent(mixed $p): bool
    {
        if (! is_array($p)) {
            return false;
        }
        foreach (['event', 'content', 'evidence', 'time', 'taxonomy', 'lifecycle', 'actors', 'jurisdictions'] as $key) {
            if (! is_array($p[$key] ?? null)) {
                return false;
            }
        }
        if (! is_string(data_get($p, 'event.id')) || ! is_int(data_get($p, 'event.revision')) || ! is_string(data_get($p, 'content.canonical_title')) || ! is_array(data_get($p, 'evidence.documents'))) {
            return false;
        }
        foreach ($p['evidence']['documents'] as $r) {
            if (! is_array($r)) {
                return false;
            }foreach (['source_id', 'document_id', 'input_message_id', 'document_status', 'quality', 'content_chars'] as $key) {
                if (! array_key_exists($key, $r)) {
                    return false;
                }
            }
        }

        return true;
    }

    public function all(): array
    {
        $r = $this->catalogue('/events');
        if ($r['ok'] && ! collect($r['data'])->every(fn ($p) => $this->validEvent($p))) {
            return [...$r, 'ok' => false, 'data' => [], 'error' => 'Malformed events response'];
        }

        return $r;
    }

    public function event(string $id): array
    {
        $r = $this->get('/events/'.rawurlencode($id), required: ['event', 'content', 'evidence', 'time']);
        if ($r['ok'] && ! $this->validEvent($r['data'])) {
            return [...$r, 'ok' => false, 'data' => [], 'error' => 'Malformed event response'];
        }

        return $r;
    }

    public function input(string $id): array
    {
        return $this->get('/documents/'.rawurlencode($id).'/input', required: ['document']);
    }
}
