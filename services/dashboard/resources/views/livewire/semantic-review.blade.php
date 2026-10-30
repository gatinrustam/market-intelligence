@php($ru = $language === 'ru')
@php($t = fn ($en, $russian) => $ru ? $russian : $en)
<div style="margin-top:1rem">
<details wire:ignore.self><summary>{{ $t('Review Article Insight · revision', 'Оценка анализа · версия оценки') }} {{ $revision }}</summary>
<p>{{ $t('Independent labels only. No model retraining, routing change or LLM request.', 'Оценки хранятся отдельно. Обучение моделей, изменение маршрутизации и LLM-запросы не выполняются.') }}</p>
<form wire:submit="save" style="display:grid;gap:0.75rem">
@foreach(['concepts_correct'=>$t('Concepts correct?', 'Темы определены правильно?'),'semantic_correct'=>$t('Semantic analysis correct?', 'Анализ корректен?'),'claims_correct'=>$t('Important claims correct?', 'Ключевые утверждения корректны?'),'assets_correct'=>$t('Affected assets correct?', 'Активы определены правильно?'),'importance_correct'=>$t('Importance correct?', 'Важность определена правильно?'),'missing_context'=>$t('Missing important context?', 'Упущен важный контекст?'),'gold_important'=>$t('Gold: important article?', 'Эталон: статья важна?')] as $field=>$label)
<label for="semantic-{{ $field }}-{{ $semanticId }}">{{ $label }}</label>
<select wire:model="{{ $field }}" id="semantic-{{ $field }}-{{ $semanticId }}" style="background:var(--fi-body-bg);color:inherit;border:1px solid #9ca3af;padding:.35rem">
<option value="">{{ $t('Not assessed', 'Не оценено') }}</option><option value="yes">{{ $t('Yes', 'Да') }}</option><option value="no">{{ $t('No', 'Нет') }}</option>
</select>
@endforeach
<fieldset><legend>{{ $t('Gold: relevant assets / markets', 'Эталон: рынки и активы') }}</legend>
@foreach(['BTC','ETH','crypto_market','USD','EUR','US_equities','specific_company','rates','gold','RUB','RU_equities','fx_market'] as $asset)
<label style="margin-right:.75rem"><input type="checkbox" wire:model="gold_assets" value="{{ $asset }}"> {{ $asset }}</label>
@endforeach
</fieldset>
<details><summary>{{ $t('Gold: correct claims · select individually', 'Эталон: отметьте корректные утверждения') }}</summary>
@foreach($claims as $claim)
<label style="display:block;margin:.5rem 0"><input type="checkbox" wire:model="correct_claim_ids" value="{{ $claim['claim_id'] }}"> {{ $claim['evidence']['text'] }}</label>
@endforeach
</details>
<label for="semantic-fp-{{ $semanticId }}">{{ $t('False positives (one per line)', 'Ложные срабатывания (по одному на строку)') }}</label>
<textarea wire:model="false_positives_text" id="semantic-fp-{{ $semanticId }}" rows="2" style="border:1px solid #9ca3af;padding:.5rem"></textarea>
<label for="semantic-gold-concepts-{{ $semanticId }}">{{ $t('Gold concept IDs (comma-separated)', 'Эталонные коды тем (через запятую)') }}</label>
<input wire:model="gold_concepts_text" id="semantic-gold-concepts-{{ $semanticId }}" style="border:1px solid #9ca3af;padding:.5rem">
<label for="semantic-comment-{{ $semanticId }}">{{ $t('Semantic review comment', 'Комментарий к оценке') }}</label>
<textarea wire:model="comment" id="semantic-comment-{{ $semanticId }}" rows="3" style="border:1px solid #9ca3af;padding:.5rem"></textarea>
@foreach($errors->all() as $error)<p>{{ $error }}</p>@endforeach
<button type="submit" style="background:#2563eb;color:white;padding:.6rem 1rem;border-radius:.4rem">{{ $t('Save semantic review', 'Сохранить оценку') }}</button>
<p role="status">{{ $feedback }}</p>
</form>
</details>
</div>
