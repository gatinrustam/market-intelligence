<?php

namespace App\Research;

use App\Api\EvaluationClient;
use App\Api\LlmAnalysisClient;
use App\Api\MarketContextClient;
use Carbon\CarbonImmutable;
use Illuminate\Support\Str;

class NewsPresentation
{
    public static function label(?string $value): string
    {
        return [
            'regulation.enforcement' => 'Обвинение / правоприменение', 'regulation.rule_adoption' => 'Принятие правил', 'regulation.rule_proposal' => 'Предложение правил', 'regulatory_action' => 'Действие регулятора', 'personnel_announcement' => 'Кадровое сообщение', 'administrative_notice' => 'Информационное сообщение', 'incident' => 'Инцидент', 'withdrawal_suspension' => 'Ограничение вывода средств',
            'critical' => 'Критично', 'important' => 'Важно', 'review' => 'На проверку', 'low' => 'Низкая', 'archive' => 'Архив',
            'high' => 'Высокая', 'medium' => 'Средняя', 'none' => 'Нет', 'new' => 'Не проверено', 'reviewed' => 'Проверено', 'dismissed' => 'Отклонено', 'escalated' => 'Требует внимания',
            'official_primary' => 'Официальный первоисточник', 'primary_announcement' => 'Официальное сообщение', 'official_announcement' => 'Официальное сообщение', 'speech' => 'Выступление', 'interview' => 'Интервью', 'commentary' => 'Комментарий', 'data_release' => 'Публикация данных', 'administrative' => 'Информационное сообщение',
            'monetary_policy' => 'Денежно-кредитная политика', 'interest_rates' => 'Процентные ставки', 'inflation' => 'Инфляция', 'employment' => 'Занятость', 'economic_growth' => 'Экономический рост', 'financial_regulation' => 'Финансовое регулирование', 'crypto_regulation' => 'Регулирование криптоактивов', 'enforcement' => 'Правоприменение', 'crypto_exchange' => 'Криптобиржи', 'exchange_outage' => 'Сбой торгов', 'withdrawal_restriction' => 'Ограничения вывода', 'security_incident' => 'Инцидент безопасности', 'hack' => 'Взлом', 'stablecoin' => 'Стейблкоины', 'depeg' => 'Потеря привязки', 'etf' => 'Биржевые фонды', 'institutional_crypto' => 'Институциональные криптоинвестиции', 'treasury_purchase' => 'Покупка активов на баланс', 'equities' => 'Акции', 'earnings' => 'Отчётность', 'merger_acquisition' => 'Слияния и поглощения', 'personnel' => 'Кадровые изменения', 'general_commentary' => 'Общий комментарий', 'trading_suspension' => 'Приостановка торгов', 'listing' => 'Листинг', 'risk_parameters' => 'Риск-параметры', 'fx_market' => 'Валютный рынок', 'cash_policy' => 'Наличные деньги и цифровая валюта ЦБ',
            'rates' => 'Процентные ставки', 'crypto_market' => 'Крипторынок', 'US_equities' => 'Акции США', 'RU_equities' => 'Российские акции', 'specific_company' => 'Отдельная компания', 'gold' => 'Золото',
            'monetary_policy.rate_decision' => 'Решение по ставке', 'economic_data.inflation' => 'Инфляция', 'economic_data.inflation_expectations' => 'Инфляционные ожидания', 'regulatory.enforcement' => 'Правоприменение', 'generic_claim' => 'Утверждение из статьи',
            'hold' => 'Сохранена', 'increase' => 'Повышение', 'decrease' => 'Снижение', 'cut' => 'Снижение', 'hike' => 'Повышение',
            'completed' => 'Завершён', 'complete' => 'Завершён', 'partial' => 'Частичные данные', 'pending' => 'Ожидается', 'blocked' => 'Заблокирован', 'failed' => 'Ошибка', 'not_linked' => 'Нет связанного события', 'not_run' => 'Не запускался', 'unavailable' => 'Недоступен',
            'up' => '↑ Рост', 'down' => '↓ Снижение', 'flat' => 'Без изменений', 'unclear' => 'Неясно', 'small' => 'Небольшое', 'moderate' => 'Умеренное', 'large' => 'Сильное', 'hit' => 'Совпадение', 'miss' => 'Не совпало', 'not_scored' => 'Не оценено',
            'market_decision_not_ready' => 'Не готов рыночный контекст на момент решения', 'stale_market_data' => 'Рыночные данные устарели', 'market_data_unavailable' => 'Рыночные данные недоступны',
        ][$value ?? ''] ?? (preg_match('/^[A-Z0-9\/]+$/', $value ?? '') ? $value : 'Не определено');
    }

    public static function source(string $id): string
    {
        return ['fed_monetary_policy' => 'Федеральная резервная система', 'ecb_press' => 'Европейский центральный банк', 'sec_press_releases' => 'Комиссия по ценным бумагам США', 'cbr_events_ru' => 'Банк России', 'cbr_press_ru' => 'Банк России', 'moex_news_ru' => 'Московская биржа', 'binance_listings' => 'Binance', 'binance_delistings' => 'Binance', 'binance_maintenance' => 'Binance', 'binance_news' => 'Binance', 'kraken_status_incidents' => 'Kraken', 'kraken_status_maintenance' => 'Kraken', 'coinbase_blog' => 'Coinbase', 'tether_news' => 'Tether', 'circle_pressroom' => 'Circle', 'sec_strategy_8k' => 'Strategy / SEC'][$id] ?? $id;
    }

    public static function color(string $value): string
    {
        return match ($value) {
            'critical', 'failed', 'miss' => 'danger', 'important', 'high', 'blocked', 'partial' => 'warning', 'review', 'pending' => 'info', 'reviewed', 'completed', 'complete', 'hit' => 'success', default => 'gray',
        };
    }

    public static function present(array $data, array $insightResult): array
    {
        $document = $data['snapshot']['document'];
        $di = $data['snapshot']['intelligence'];
        $insight = $insightResult['ok'] ? data_get($insightResult, 'data.0.insight', []) : [];
        $topics = $insight ? ($insight['main_topics'] ?? []) : array_column($di['topics'] ?? [], 'topic');
        $assets = $insight['affected_assets'] ?? [];
        $claims = $insight['key_claims'] ?? [];
        $body = data_get($document, 'content.body', '');
        $facts = [];
        foreach ($di['facts'] ?? [] as $fact) {
            $facts[] = ['title' => self::label($fact['fact_type']), 'text' => data_get($fact, 'evidence.text', ''), 'value' => implode(' · ', array_filter(array_map(fn ($v) => data_get($v, 'evidence.text'), $fact['values'] ?? []))), 'state' => self::label($fact['action'] ?? null), 'basis' => 'Извлечённый факт', 'span' => $fact['evidence'] ?? []];
        }
        foreach ($claims as $claim) {
            $text = data_get($claim, 'evidence.text', '');
            if ($text && ! in_array($text, array_column($facts, 'text'), true)) {
                $facts[] = ['title' => 'Утверждение из статьи', 'text' => $text, 'value' => null, 'state' => null, 'basis' => 'Точный фрагмент · требует проверки', 'span' => $claim['evidence']];
            }
        }
        $event = collect($data['snapshot']['events'] ?? [])->first(function ($event) use ($document) {
            return collect(data_get($event, 'evidence.documents', []))->contains(fn ($ref) => ($ref['document_id'] ?? null) === $document['document_id'] && ($ref['input_message_id'] ?? null) === $document['message_id']);
        });
        $titleWords = preg_split('/[^\p{L}\p{N}]+/u', mb_strtolower(data_get($document, 'content.title', '')));
        $titleWords = array_values(array_filter($titleWords, fn ($word) => mb_strlen($word) > 3));
        $leadClaim = collect($claims)->sortByDesc(fn ($claim) => count(array_filter($titleWords, fn ($word) => str_contains(mb_strtolower(data_get($claim, 'evidence.text', '')), $word))))->first();
        $summary = data_get($event, 'content.canonical_title') ?: data_get($leadClaim, 'evidence.text') ?: Str::limit($body, 550);
        $reasons = [];
        if (data_get($data, 'machine.features.source_quality') === 'official_primary' || in_array(data_get($document, 'source.id'), ['fed_monetary_policy', 'ecb_press', 'sec_press_releases', 'cbr_events_ru', 'cbr_press_ru', 'moex_news_ru'], true)) {
            $reasons[] = 'Опубликовано официальным первоисточником';
        }
        if (count($di['facts'] ?? [])) {
            $reasons[] = 'В тексте найдены конкретные факты с подтверждающими фрагментами';
        }
        if ($topics) {
            $reasons[] = 'Подтверждённые темы: '.implode(', ', array_map(self::label(...), array_slice($topics, 0, 3)));
        }
        if ($assets) {
            $reasons[] = 'Есть текстовые основания для связи с рынками: '.implode(', ', array_map(fn ($a) => self::label($a['asset']), $assets));
        }
        $route = data_get($data, 'machine.classification.route', 'review');
        $suggested = data_get($insight, 'routing.semantic_suggested_route');
        $priority = $suggested ?: $route;
        if (in_array($priority, ['low', 'archive'], true)) {
            $reasons[] = 'По текущей оценке приоритет статьи низкий';
        }
        $entities = collect($insight['entities'] ?? $di['entities'] ?? [])->map(fn ($e) => $e['name'] ?? $e['canonical_name'] ?? data_get($e, 'evidence.text'))->filter()->unique()->values()->all();
        $url = data_get($document, 'source.url');
        $url = is_string($url) && in_array(strtolower(parse_url($url, PHP_URL_SCHEME) ?? ''), ['https', 'http'], true) ? $url : null;

        return compact('document', 'di', 'insight', 'topics', 'assets', 'facts', 'summary', 'reasons', 'event', 'priority', 'route', 'suggested', 'entities', 'url', 'body');
    }

    public function context(?array $event): array
    {
        $empty = ['ok' => false, 'data' => [], 'error' => null];
        $result = ['decision' => $empty, 'analyses' => [], 'analysis_state' => 'not_run', 'evaluations' => [], 'errors' => []];
        if (! $event) {
            return [...$result, 'analysis_state' => 'not_linked', 'event_linked' => false];
        }
        $id = data_get($event, 'event.id');
        $revision = data_get($event, 'event.revision');
        $contexts = app(MarketContextClient::class)->contexts($id);
        $context = collect($contexts['data'])->first(fn ($c) => data_get($c, 'event.event_revision') === $revision);
        if ($context) {
            $result['decision'] = app(MarketContextClient::class)->decision($context['context_id'], 'live');
        }
        $all = app(LlmAnalysisClient::class)->all();
        $result['analysis_state'] = $all['ok'] ? 'not_run' : 'unavailable';
        foreach ($all['data'] as $analysis) {
            if (($analysis['event_id'] ?? null) === $id && ($analysis['event_revision'] ?? null) === $revision) {
                $detail = app(LlmAnalysisClient::class)->analysis($analysis['analysis_id']);
                if ($detail['ok'] && ($detail['data']['event_id'] ?? null) === $id && ($detail['data']['event_revision'] ?? null) === $revision && ($detail['data']['analysis_id'] ?? null) === $analysis['analysis_id']) {
                    $result['analyses'][] = $detail['data'];
                } elseif (! $detail['ok']) {
                    $result['analysis_state'] = 'unavailable';
                }
            }
        }
        $evaluations = app(EvaluationClient::class)->forEvent($id);
        $ids = array_column($result['analyses'], 'analysis_id');
        $result['evaluations'] = array_values(array_filter($evaluations['data'], fn ($e) => data_get($e, 'analysis.event_revision') === $revision && in_array(data_get($e, 'analysis.analysis_id'), $ids, true) && data_get($e, 'provenance.origin') !== 'fixture'));
        $result['errors'] = array_filter([$contexts['error'], $all['error'], $evaluations['error']]);

        return $result + ['event_linked' => true];
    }

    public static function causalPoints(array $decision): array
    {
        if (! ($decision['ok'] ?? false)) {
            return [];
        }

        return array_values(array_filter(data_get($decision, 'data.points', []), function ($p) use ($decision) {
            try {
                return in_array($p['offset_seconds'], [-900, -300, 0], true) && ($p['available'] ?? false) && is_numeric($p['price'] ?? null) && ! empty($p['price_at']) && ! empty($p['target_at']) && CarbonImmutable::parse($p['price_at'])->lte(CarbonImmutable::parse($p['target_at'])) && CarbonImmutable::parse($p['target_at'])->lte(CarbonImmutable::parse($decision['data']['decision_at'])) && is_numeric($p['age_seconds'] ?? null) && is_numeric($p['max_age_seconds'] ?? null) && CarbonImmutable::parse($p['price_at'])->diffInSeconds(CarbonImmutable::parse($p['target_at'])) <= $p['max_age_seconds'] && $p['age_seconds'] >= 0 && $p['age_seconds'] <= $p['max_age_seconds'];
            } catch (\Throwable) {
                return false;
            }
        }));
    }
}
