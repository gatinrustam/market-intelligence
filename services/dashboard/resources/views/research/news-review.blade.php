<div class="news-review">
<p>Оценки сохраняются отдельно от анализа. Отметка «Передать в LLM» не запускает модель.</p>
<form wire:submit="saveReview" style="display:grid;gap:1rem;max-width:42rem">
@foreach(['status'=>['new'=>'Не проверено','reviewed'=>'Проверено','dismissed'=>'Отклонено','escalated'=>'Требует внимания'],'usefulness'=>[''=>'Не оценено','useful'=>'Полезна','not_useful'=>'Не полезна'],'priority_override'=>[''=>'Без изменения','critical'=>'Критично','important'=>'Важно','review'=>'На проверку','low'=>'Низкая','archive'=>'Архив'],'facts_correct'=>[''=>'Не оценено','yes'=>'Да','no'=>'Нет'],'event_type_correct'=>[''=>'Не оценено','yes'=>'Да','no'=>'Нет'],'duplicate'=>[''=>'Не оценено','yes'=>'Да','no'=>'Нет']] as $field=>$options)
<label for="review-{{ $field }}">{{ ['status'=>'Статус','usefulness'=>'Полезная статья?','priority_override'=>'Изменить приоритет','facts_correct'=>'Факты корректны?','event_type_correct'=>'Тип события корректен?','duplicate'=>'Дубликат?'][$field] }}</label>
<select id="review-{{ $field }}" wire:model="{{ $field }}" style="background:transparent;border:1px solid #6b7280;border-radius:0.4rem;padding:0.5rem">
@foreach($options as $value=>$label)<option value="{{ $value }}">{{ $label }}</option>@endforeach
</select>
@error($field)<p>{{ $message }}</p>@enderror
@endforeach
<label><input type="checkbox" wire:model="send_to_llm"> Передать в LLM — только отметка</label>
<label for="review-comment">Комментарий</label><textarea id="review-comment" wire:model="comment" maxlength="2000" rows="3" style="background:transparent;border:1px solid #6b7280;padding:0.5rem"></textarea>
@error('comment')<p>{{ $message }}</p>@enderror
<x-filament::button type="submit" wire:loading.attr="disabled">Сохранить оценку статьи</x-filament::button>
</form>

@if(!empty($insightResult["data"][0]))
@php($row=$insightResult["data"][0])
@livewire("semantic-review", ["semanticId"=>$row["insight"]["semantic_id"],"review"=>$row["review"],"labels"=>$row["labels"],"claims"=>$row["insight"]["key_claims"],"language"=>"ru"], key("modal-semantic-".$row["insight"]["semantic_id"]))
@endif
</div>
