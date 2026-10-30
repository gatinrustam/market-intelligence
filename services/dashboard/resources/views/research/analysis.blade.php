@php($status=$analysis['analysis_status']??'not_run')
<div style="margin-bottom:1rem"><x-filament::badge :color="\App\Research\Display::color($status)">{{ $status==='not_run'?'Not run':$status }}</x-filament::badge></div>
@if(isset($analysis['analysis_id']))<p><x-research-id :value="$analysis['analysis_id']" /></p>@endif
<x-research-fields :fields="['Model'=>data_get($analysis,'configuration.model'),'Prompt version'=>data_get($analysis,'configuration.prompt_version'),'Reasoning effort'=>data_get($analysis,'configuration.reasoning_effort'),'Mode'=>($analysis['basis']??'')==='live'?'LIVE':'RESEARCH HYPOTHETICAL','Reason'=>$analysis['error']??null,'Input hash'=>$analysis['input_hash']??null]" />
@if($status==='completed' && is_array($analysis['analysis']??null))
@php($a=$analysis['analysis'])
<div style="margin-top:1rem"><x-research-fields :fields="['Relevance'=>data_get($a,'asset.relevance'),'Summary'=>data_get($a,'interpretation.summary'),'Market mechanism'=>data_get($a,'interpretation.market_mechanism')]" /></div>
<x-research-table :headers="['Horizon','Direction','Impact','Confidence · model-reported']" :rows="array_map(fn($f)=>[($f['horizon_seconds']/60).'m',$f['direction'],$f['impact'],$f['confidence']],$a['forecast']??[])" />
<p>Confidence is not a calibrated probability.</p>
<ul style="margin:1rem 0;list-style:disc;padding-left:1.5rem">@foreach($a['uncertainties']??[] as $uncertainty)<li>{{ $uncertainty }}</li>@endforeach</ul>
@endif
@foreach($analysis['runs']??[] as $run)
<x-research-fields :fields="['Attempt'=>$run['attempt'],'Status'=>$run['status'],'Latency · ms'=>data_get($run,'response_audit.latency_ms'),'Token usage'=>data_get($run,'response_audit.usage'),'Error'=>$run['error']??null]" />
@endforeach
<details style="margin-top:1rem"><summary>JSON / audit details</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{{ json_encode(['analysis'=>$analysis['analysis']??null,'configuration'=>$analysis['configuration']??[],'input_hash'=>$analysis['input_hash']??null,'prompt_hash'=>$analysis['prompt_hash']??null],JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES) }}</pre></details>
