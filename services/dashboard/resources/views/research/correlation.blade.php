<x-filament::section heading="Correlation">
<div style="min-width:0;overflow-wrap:anywhere">
<p>Research only · automatic merging requires exact fact identity. Source count means distinct source IDs, not verified independent publishers.</p>
@if(!$correlationResult['ok'])
<p>Correlation unavailable · {{ $correlationResult['error'] }}</p>
@elseif(!$correlationResult['data'])
<p>No correlation result for this exact document input.</p>
@else
@foreach($correlationResult['data'] as $row)
@php($event=$row['event'])
<x-research-fields :fields="['Research event'=>$event['event_id'],'Revision'=>$event['revision'],'Correlation mode'=>$event['correlation_mode'],'Ruleset'=>$event['ruleset_version'],'Fingerprint version'=>$event['fingerprint_version'],'Linked documents'=>$event['document_count'],'Independent sources (technical count)'=>$event['independent_source_count']]" />
<details><summary>Fact fingerprint · {{ $row['fingerprint']['hash'] }}</summary>
<x-research-fields :fields="$row['fingerprint']" />
</details>
<details><summary>Linked documents · {{ $event['document_count'] }}</summary>
@foreach($event['documents'] as $document)
<p>{{ $document['title'] }} · {{ $document['document_id'] }} · {{ implode(', ', $document['sources']) }}</p>
@endforeach
</details>
<p>Suggestions: {{ count($row['suggestions']) }} · require review; never merged automatically.</p>
@foreach($row['suggestions'] as $suggestion)
<details><summary>suggestion · {{ $suggestion['candidate_a'] }} ↔ {{ $suggestion['candidate_b'] }}</summary>
<x-research-fields :fields="['Reason'=>$suggestion['reason'],'Matched fields'=>$suggestion['matched_fields'],'Conflicting fields'=>$suggestion['conflicting_fields'],'Features'=>$suggestion['features']]" />
</details>
@endforeach
<details><summary>All pair decisions · {{ count($row['decisions']) }}</summary>
@foreach($row['decisions'] as $decision)
<p><strong>{{ $decision['mode'] }}</strong> · {{ $decision['candidate_a'] }} ↔ {{ $decision['candidate_b'] }}</p>
<x-research-fields :fields="['Matched fields'=>$decision['matched_fields'],'Conflicting fields'=>$decision['conflicting_fields'],'Reason'=>$decision['reason'],'Features'=>$decision['features'],'Same event in v1'=>$decision['v1_same_event']]" />
@endforeach
</details>
@endforeach
@endif
</div>
</x-filament::section>
