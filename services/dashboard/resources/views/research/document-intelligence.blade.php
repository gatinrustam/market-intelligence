<div style="margin:1rem 0">
<p><x-research-id :value="$item['reference']['document_id']" /></p>
@if(!$item['intelligence']['ok'])
<p>Document Intelligence unavailable · {{ $item['intelligence']['error'] }}</p>
@elseif(!$item['intelligence']['data'])
<p>Document not yet processed.</p>
@else
@foreach($item['intelligence']['data'] as $di)
<x-research-fields :fields="['Language'=>$di['language'],'Processing'=>data_get($di,'processing.status'),'Pipeline version'=>data_get($di,'extraction.pipeline_version'),'Entity registry'=>data_get($di,'extraction.entity_registry_version'),'Fact ruleset'=>data_get($di,'extraction.fact_ruleset_version'),'Warnings'=>data_get($di,'processing.warnings')]" />
<p>Extracted claims from the observed document. Click an item to see its exact source fragment. These are not trading signals or independently verified facts.</p>
@foreach(['facts'=>'Facts','entities'=>'Entities','measurements'=>'Measurements','relations'=>'Relations','topics'=>'Topics','dates'=>'Dates'] as $field=>$label)
<details style="margin:0.75rem 0" @if($field==='facts') open @endif><summary>{{ $label }} · {{ count($di[$field]) }}</summary>
@forelse($di[$field] as $value)
@php
$evidence=$value['evidence'];
$body=$item['document']['content']['body'];
$start=$evidence['start_char']; $end=$evidence['end_char'];
$title=match($field) {
'facts'=>($value['fact_type']??'Fact').' · '.($value['action']??''),
'entities'=>($value['canonical_name']??'Entity').' · '.($value['type']??''),
'measurements'=>($value['kind']??'Measurement').' · '.($value['value']??(($value['min']??'').'–'.($value['max']??''))).' '.($value['unit']??''),
'relations'=>data_get($value,'subject.entity_id').' → '.($value['action']??'').' → '.data_get($value,'object.text'),
 'topics'=>$value['topic']??'Topic', default=>$value['raw']??'Date'};
@endphp
<details style="margin:0.5rem 0;padding:0.5rem;border:1px solid #6b7280;border-radius:0.4rem"><summary>{{ $title }}</summary>
<p style="white-space:pre-wrap;margin:0.75rem 0">{{ mb_substr($body,max(0,$start-80),min(80,$start)) }}<mark style="background:#fde68a;color:#111827">{{ $evidence['text'] }}</mark>{{ mb_substr($body,$end,80) }}</p>
<p>Sentence {{ $evidence['sentence_id'] }} · characters {{ $start }}–{{ $end }} · {{ data_get($value,'extraction.extractor') }} · {{ data_get($value,'extraction.rule_id') }} · version {{ data_get($value,'extraction.extractor_version') }}</p>
@if($field==='facts')<p>Values: {{ \App\Research\Display::text(array_map(fn($m)=>($m['value']??(($m['min']??'').'–'.($m['max']??''))).' '.($m['unit']??''),$value['values']??[])) }}</p>@endif
@if($field==='relations')<p>{{ $value['modality']??'' }}</p>@endif
</details>
@empty<p>No {{ strtolower($label) }} extracted.</p>@endforelse
</details>
@endforeach
@endforeach
@endif
</div>
