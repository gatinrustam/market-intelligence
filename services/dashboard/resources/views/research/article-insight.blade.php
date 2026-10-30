@php($ru = data_get($insightResult, 'data.0.insight.document.language') === 'ru')
@php($t = fn ($en, $russian) => $ru ? $russian : $en)
@php($level = fn ($value) => $ru ? (['none'=>'нет','low'=>'низкая','medium'=>'средняя','high'=>'высокая'][$value] ?? $value) : $value)
<x-filament::section :heading="$t('ARTICLE INSIGHT', 'АНАЛИЗ СТАТЬИ')">
@if(!$insightResult['ok'])
<p>Article Insight unavailable · {{ $insightResult['error'] }}. Deterministic DI and existing routing remain available below.</p>
@elseif(!$insightResult['data'])
<p>Semantic analysis pending for this exact document input. Deterministic DI remains available below.</p>
@else
@foreach($insightResult['data'] as $row)
@php($insight=$row['insight'])
@php($label = fn ($value) => $insight['display_labels'][$value] ?? $value)
@if(!$loop->first)<details style="margin-top:1rem"><summary>{{ $t('Archived analysis', 'Архивный анализ') }} · {{ $insight['provenance']['pipeline_version'] ?? 'Unavailable' }} · {{ $label($insight['status']) }}</summary>@endif
<div style="overflow-wrap:anywhere">
<h3 style="font-size:1.2rem;font-weight:700">{{ $t('Potential importance:', 'Потенциальная важность:') }} {{ strtoupper($level($insight['potential_importance'])) }}</h3>
<p>{{ $t('Analysis version:', 'Версия анализа:') }} {{ $insight['provenance']['pipeline_version'] ?? 'Unavailable' }} · {{ $label($insight['article_type']) }} · {{ $insight['document']['language'] }} · {{ $label($insight['status']) }}</p>
<strong>{{ $t('Why it matters', 'Почему это важно') }}</strong>
<ul>@foreach($insight['why_it_matters'] as $reason)<li>{{ $reason }}</li>@endforeach</ul>
<p><strong>{{ $t('Main topics:', 'Принятые темы:') }}</strong> {{ implode(', ', array_map(fn ($id) => $insight['topic_labels'][$id] ?? $id, $insight['main_topics'])) }}</p>
<p><strong>{{ $t('Affected markets / assets', 'Затронутые рынки и активы') }}</strong> · {{ $t('research candidates, not price forecasts', 'исследовательские связи, не прогноз цены') }}</p>
@forelse($insight['affected_assets'] as $asset)
<details><summary>{{ $label($asset['asset']) }} — {{ $level($asset['relevance']) }}</summary>
@foreach($asset['basis'] as $reason)<p>{{ $reason }}</p>@endforeach
@foreach($asset['evidence'] as $span)<blockquote>{{ $span['text'] }}</blockquote>@endforeach
</details>
@empty<p>{{ $t('No sufficiently supported asset link.', 'Недостаточно оснований для связи с активами.') }}</p>@endforelse
<h4 style="font-weight:700;margin-top:1rem">{{ $t('Key claims · exact source fragments', 'Ключевые утверждения · точные исходные фрагменты') }}</h4>
@forelse($insight['key_claims'] as $claim)
<div style="margin:.75rem 0;padding:.75rem;border-left:3px solid #9ca3af">
<p>{{ $claim['evidence']['text'] }}</p>
<small>{{ $label($claim['extractor']) }} · {{ $label($claim['status']) }} · {{ $t('characters', 'символы') }} {{ $claim['evidence']['start_char'] }}–{{ $claim['evidence']['end_char'] }}</small>
<details><summary>{{ $t('Evidence basis', 'Основание') }}</summary><p>{{ $claim['reason'] }}</p><p>{{ $t('DI facts:', 'DI-факты:') }} {{ implode(', ', $claim['supporting_fact_ids']) }}</p></details>
</div>
@empty<p>{{ $t('No supported claim candidates found.', 'Подтвержденные утверждения не найдены.') }}</p>@endforelse
<details><summary>{{ $t('Important numbers', 'Важные числа') }} · {{ count($insight['important_numbers']) }}</summary>
@foreach($insight['important_numbers'] as $number)<p>{{ $number['evidence']['text'] }} · {{ $label($number['kind']) }} · {{ $number['unit'] }}</p>@endforeach
</details>
<details><summary>{{ $t('Entities', 'Участники и сущности') }} · {{ count($insight['entities']) }}</summary>
@foreach($insight['entities'] as $entity)<p>{{ $entity['name'] }} · {{ $label($entity['type']) }} · {{ $entity['extractor'] }} @if($entity['confidence'] !== null) · {{ $t('model confidence', 'уверенность модели') }} {{ $entity['confidence'] }} @endif</p>@endforeach
</details>
@if(!empty($insight['reranking']))
<h4 style="font-weight:700;margin-top:1rem">{{ $t('Concept evidence decisions', 'Принятие и отклонение тем') }}</h4>
@foreach($insight['reranking']['decisions'] as $decision)
@if($decision['summary']['semantic_evidence_count'] > 0 || $decision['decision'] === 'accepted')
<details><summary>{{ $insight['topic_labels'][$decision['concept_id']] ?? $decision['concept_id'] }} — {{ $ru ? (['accepted'=>'принято','rejected'=>'отклонено','review'=>'кандидат'][$decision['decision']] ?? $decision['decision']) : $decision['decision'] }}</summary>
<p>{{ implode('; ', $decision['reasons']) }}</p>
<p>{{ $t('Independent evidence fragments', 'Независимых фрагментов') }}: {{ $decision['summary']['independent_evidence_count'] }} · {{ $t('Maximum similarity (not probability)', 'Максимальное сходство (не вероятность)') }}: {{ $decision['summary']['max_similarity'] }}</p>
@foreach($decision['summary']['supporting_spans'] as $span)<blockquote>{{ $span['text'] }}</blockquote>@endforeach
@foreach($decision['summary']['negative_evidence'] as $negative)<p>{{ $t('Contrastive evidence: positive / negative / margin', 'Сравнение примеров: положительное / отрицательное / разность') }}: {{ $negative['positive_similarity'] }} / {{ $negative['negative_similarity'] }} / {{ $negative['semantic_margin'] }}</p>@endforeach
</details>
@endif
@endforeach
@endif
@if(!empty($insight['comparison']) && !empty($row['baseline_insight']))
<h4 style="font-weight:700;margin-top:1rem">DI-5 vs DI-5.1</h4>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1rem">
@foreach(['DI-5'=>$row['baseline_insight'],'DI-5.1'=>$insight] as $version=>$side)
<div style="padding:.75rem;border:1px solid #9ca3af;border-radius:.4rem"><strong>{{ $version }}</strong>
<p>{{ $t('Importance', 'Важность') }}: {{ $level($side['potential_importance']) }}</p>
<p>{{ $t('Topics', 'Темы') }}: {{ implode(', ', array_map(fn ($id) => $side['topic_labels'][$id] ?? $id, $side['main_topics'])) }}</p>
<p>{{ $t('Assets', 'Активы') }}: {{ implode(', ', array_map($label, array_column($side['affected_assets'], 'asset'))) }}</p>
<details><summary>{{ $t('Claims', 'Утверждения') }} · {{ count($side['key_claims']) }}</summary>@foreach($side['key_claims'] as $claim)<blockquote style="margin:.6rem 0">{{ $claim['evidence']['text'] }}</blockquote>@endforeach</details>
</div>
@endforeach
</div>
<p>{{ $t('Removed topics', 'Исключенные темы') }}: {{ implode(', ', array_map(fn ($id) => $insight['topic_labels'][$id] ?? $id, $insight['comparison']['concepts_removed'])) }}</p>
<p>{{ $t('Added topics', 'Добавленные темы') }}: {{ implode(', ', array_map(fn ($id) => $insight['topic_labels'][$id] ?? $id, $insight['comparison']['concepts_added'])) }}</p>
<p>{{ $t('Removed / added asset links', 'Удаленные / добавленные связи с активами') }}: {{ implode(', ', $insight['comparison']['assets_removed']) }} / {{ implode(', ', $insight['comparison']['assets_added']) }}</p>
@endif
<p><strong>{{ $t('Routing comparison:', 'Сравнение маршрутизации:') }}</strong> {{ $label($insight['routing']['old_route'] ?? 'Unavailable') }} → {{ $label($insight['routing']['semantic_suggested_route']) }} ({{ $t('research suggestion only', 'только исследовательская рекомендация') }})</p>
<details><summary>{{ $t('Information value · independent features', 'Информационная ценность · независимые признаки') }}</summary>
@foreach($insight['information_value'] as $name=>$feature)<p><strong>{{ $label($name) }}: {{ $level($feature['level']) }}</strong> — {{ implode('; ', $feature['reasons']) }}</p>@endforeach
</details>
<details><summary>{{ $t('Limitations / model provenance', 'Ограничения и версии моделей') }}</summary>
@foreach($insight['limitations'] as $warning)<p>{{ $warning }}</p>@endforeach
<x-research-fields :fields="$insight['provenance']" />
</details>
@foreach($insight['conflicts'] as $conflict)<p><strong>Conflict:</strong> {{ $conflict['reason'] }}</p>@endforeach
@if($showReview ?? true)
@livewire('semantic-review', ['semanticId'=>$insight['semantic_id'],'review'=>$row['review'],'labels'=>$row['labels'],'claims'=>$insight['key_claims'], 'language'=>$insight['document']['language']], key('semantic-'.$insight['semantic_id']))
@endif
</div>
@if(!$loop->first)</details>@endif
@endforeach
@endif
</x-filament::section>
