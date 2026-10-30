<x-filament-panels::page>
<x-research-error :message="$data['event']['error']" />
@if($data['event']['ok'])
@php($e=$data['canonical'])
<x-filament::section :heading="data_get($e,'content.canonical_title','Event')">
<p style="margin-bottom:1rem"><x-research-id :value="$e['event']['id']" /></p>
<x-research-fields :fields="['Event type'=>data_get($e,'taxonomy.event_type'),'Topics'=>data_get($e,'taxonomy.topics'),'Actors'=>array_column($e['actors']??[],'name'),'Jurisdiction'=>$e['jurisdictions']??[],'Revision'=>$e['event']['revision'],'Lifecycle'=>data_get($e,'lifecycle.status'),'Event time'=>data_get($e,'time.event_time'),'Detected at'=>\App\Research\Display::utc(data_get($e,'time.first_detected_at'))]" />
</x-filament::section>
<x-filament::section heading="Evidence · exact canonical revision">
@foreach($data['documents'] as $item)
@php($ref=$item['reference'])
<div style="margin:1rem 0"><x-filament::badge :color="\App\Research\Display::color($ref['document_status'])">{{ $ref['source_id'] }} · {{ $ref['document_status']==='partial'?'partial / RSS fallback':$ref['document_status'] }} · {{ $ref['quality'] }}</x-filament::badge></div>
<p><x-research-id :value="$ref['document_id']" /></p>
<p>Content chars: {{ $ref['content_chars'] }}</p>
@if($item['error'])<p>{{ $item['error'] }}</p>@endif
@if($item['document'])
<p>Fetch: {{ data_get($item,'document.fetch.status') }} · HTTP {{ data_get($item,'document.fetch.http_status','Unavailable') }}</p>
<details style="margin:1rem 0"><summary>Title / body excerpt · first 1,000 characters</summary>
<strong>{{ data_get($item,'document.content.title') }}</strong><p style="white-space:pre-wrap">{{ \Illuminate\Support\Str::limit(data_get($item,'document.content.body',''),1000) }}</p></details>
@endif
@endforeach
</x-filament::section>
<x-filament::section heading="Document Intelligence">
@foreach($data['documents'] as $item)
@include('research.document-intelligence', ['item' => $item])
@endforeach
</x-filament::section>
@foreach($data['documents'] as $item)
@include('research.event-comparison',['comparisonResult'=>$item['comparison']])
@include('research.correlation', ['correlationResult' => $item['correlation']])
@endforeach
<x-filament::section heading="Decision / provenance">
<label for="decision-basis">Decision basis</label>
<x-filament::input.wrapper><x-filament::input.select id="decision-basis" wire:model.live="basis"><option value="live">LIVE</option><option value="research_hypothetical">RESEARCH HYPOTHETICAL</option></x-filament::input.select></x-filament::input.wrapper>
<div style="margin:1rem 0"><x-filament::badge :color="$basis==='live'?'success':'warning'">{{ $basis==='live'?'LIVE':'RESEARCH HYPOTHETICAL' }}</x-filament::badge></div>
@if(!$data['decision']['ok'])<p>{{ $data['decision']['error'] }}</p>@else
@php($d=$data['decision']['data'])
<x-research-fields :fields="['decision_at'=>\App\Research\Display::utc($d['decision_at']),'decision_basis'=>$d['decision_basis'],'historical_simulation'=>$d['historical_simulation'],'evidence_available_at'=>\App\Research\Display::utc($d['evidence_available_at']??null),'evidence_fetched_at'=>\App\Research\Display::utc($d['evidence_fetched_at']??null),'historical_content_verified'=>$d['historical_content_verified']??null,'decision_ready'=>$d['decision_ready'],'complete'=>$d['complete']??null,'market_data_status'=>$d['market_data_status']??null]" />
@endif
</x-filament::section>
<x-filament::section heading="CAUSAL — decision-time information">
@if($data['decision']['ok'])
<x-research-table :headers="['Offset','Price','Resolution','Price at · UTC','Age / max · seconds','Bid','Ask','Spread · bps','Reason']" :rows="array_map(fn($p)=>[match($p['offset_seconds']){-900=>'T-15m',-300=>'T-5m',0=>'T',default=>'Invalid offset'},$p['available']?$p['price']:null,$p['resolution'],\App\Research\Display::utc($p['price_at']),\App\Research\Display::text($p['age_seconds']).' / '.\App\Research\Display::text($p['max_age_seconds']),$p['available']?$p['bid']:null,$p['available']?$p['ask']:null,$p['available']?$p['spread_bps']:null,$p['reason']],$data['decision']['data']['points'])" />
@else<p>market_data_unavailable · {{ $data['decision']['error'] }}</p>@endif
</x-filament::section>
<x-filament::section heading="OUTCOMES — evaluation only">
<x-filament::badge color="warning">Never available to the LLM at decision time</x-filament::badge>
<p style="margin:1rem 0">Stored research context anchor: {{ \App\Research\Display::utc(data_get($data,'context.anchor.at')) }}. These outcomes are event-time anchored, not automatically relative to the selected decision_at.</p>
<x-research-table :headers="['Offset','Target · UTC','Status','Price','Return % from event anchor','Reason']" :rows="array_values(array_map(fn($p)=>['+'.($p['offset_seconds']/60).'m',\App\Research\Display::utc($p['target_at']),$p['status'],$p['available']?$p['price']:null,$p['available']?$p['return_pct_from_anchor']:null,$p['reason']],array_filter($data['context']['points']??[],fn($p)=>in_array($p['offset_seconds'],[60,300,900,3600],true))))" />
</x-filament::section>
<x-filament::section heading="Event Intelligence">
<p>Deterministic research features · information quality is not statistical confidence. Novelty is limited to canonical revision history.</p>
@if(!$data['intelligence']['ok'])
<p>Event Intelligence unavailable · {{ $data['intelligence']['error'] }}</p>
@elseif(!$data['intelligence']['data'])
<p>Not yet processed for this canonical revision.</p>
@else
@foreach($data['intelligence']['data'] as $intelligence)
<div style="margin-top:1rem">
<x-research-fields :fields="['BTC relevance'=>$intelligence['relevance'],'Novelty'=>$intelligence['novelty'],'Surprise availability'=>$intelligence['surprise']['status'],'Information quality'=>$intelligence['information_quality'],'Event specificity'=>$intelligence['event_specificity'],'Expectations availability'=>data_get($intelligence,'expectations.source') ? 'External source recorded' : 'Unavailable — no consensus provider','Ruleset version'=>data_get($intelligence,'basis.ruleset_version'),'Generated at'=>\App\Research\Display::utc($intelligence['generated_at']??null),'Matched rules'=>data_get($intelligence,'basis.matched_rule_ids')]" />
<p>Computed research result. Its presence here does not mean it was available at the selected historical decision time or used by an earlier analysis.</p>
<details><summary>Intelligence JSON / audit</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{{ json_encode($intelligence,JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES) }}</pre></details>
</div>
@endforeach
@endif
</x-filament::section>
<x-filament::section heading="LLM Analysis · stored runs for this revision">
@if($data['llm_error'])<p>LLM Analysis unavailable · {{ $data['llm_error'] }}</p>
@elseif(!$data['analyses'])<x-filament::badge color="gray">Not run</x-filament::badge><p>No analysis has been run. This read-only dashboard cannot start one.</p>
@else @foreach($data['analyses'] as $result)
@if($result['ok'])@include('research.analysis',['analysis'=>$result['data']])@else<p>LLM Analysis unavailable · {{ $result['error'] }}</p>@endif
@endforeach @endif
</x-filament::section>
<x-filament::section heading="Evaluation · observed outcomes">
@if(!$data['evaluations']['ok'])
<p>Evaluation unavailable · {{ $data['evaluations']['error'] }}</p>
@elseif(!$data['evaluations']['data'])
<p>No evaluation yet. A completed analysis is required.</p>
@else
@foreach($data['evaluations']['data'] as $evaluation)
@include('research.evaluation', ['evaluation' => $evaluation])
@endforeach
@endif
</x-filament::section>
<details><summary>Canonical JSON / debug details</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{{ json_encode($e,JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES) }}</pre></details>
@endif
</x-filament-panels::page>
