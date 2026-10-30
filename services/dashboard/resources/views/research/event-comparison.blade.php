<x-filament::section heading="Event Engine Comparison">
<p>Parallel research only · v1 remains the production canonical source · DI-3 candidates remain immutable.</p>
@if(!$comparisonResult['ok'])
<p>Event Engine Comparison unavailable · {{ $comparisonResult['error'] }}</p>
@elseif(!$comparisonResult['data'])
<p>No v2 research result for this exact document input.</p>
@else
@foreach($comparisonResult['data'] as $row)
@php($r=$row['result'])
@php($c=$row['comparison'])
<x-research-fields :fields="['Research ID'=>$r['research_id'],'Ruleset'=>$r['basis']['ruleset_version'],'v1 classification'=>$c['v1_event_types'],'v2 classification'=>$c['v2_event_types'],'v1 basis'=>$c['v1_basis'],'v2 basis'=>$c['v2_basis'],'Fallback used'=>$c['flags']['fallback_used'],'Classification conflict'=>$c['flags']['conflict'],'Multiple candidates'=>$c['flags']['multiple_candidates'],'No event'=>$c['flags']['no_event']]" />
@foreach($r['candidates'] as $candidate)
<details open style="margin:1rem 0"><summary>{{ $candidate['event_type'] }} · {{ $candidate['classification_basis'] }}</summary>
<p>Event time: {{ $candidate['event_time'] ?? 'Unknown — not inferred from publication' }}</p>
<p>Actors: {{ \App\Research\Display::text($candidate['actors']) }}</p>
<p>Topics: {{ \App\Research\Display::text($candidate['topics']) }}</p>
<p>Fact-linked measurements: {{ \App\Research\Display::text($candidate['measurements']) }}</p>
@forelse($candidate['fact_references'] as $fact)
<details style="margin:0.75rem 0"><summary>{{ $fact['fact_type'] }} · {{ $fact['fact_id'] }}</summary>
<p><mark style="background:#fde68a;color:#111827">{{ $fact['evidence']['text'] }}</mark></p>
<p>Document {{ $fact['document_id'] }} · characters {{ $fact['evidence']['start_char'] }}–{{ $fact['evidence']['end_char'] }} · {{ $fact['extraction']['rule_id'] }} · extractor version {{ $fact['extraction']['extractor_version'] }}</p>
</details>
@empty<p>No primary facts; metadata fallback is explicit.</p>@endforelse
<details><summary>Supporting / fallback signals</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{{ json_encode($candidate['signals'],JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE) }}</pre></details>
</details>
@endforeach
@foreach($r['conflicts'] as $conflict)
<p><strong>classification_conflict</strong> — {{ $conflict['reason'] }}</p>
<x-research-fields :fields="['Selected'=>$conflict['selected_event_types'],'Alternatives and basis'=>$conflict['alternatives']]" />
@endforeach
<details><summary>Human labels · frozen evaluation signals · {{ count($c['human_evaluation']) }}</summary>
<p>Labels did not select or change the v2 classification. A changed classification is not automatically a verified correction.</p>
@forelse($c['human_evaluation'] as $label)
<x-research-fields :fields="$label" />
@empty<p>No applicable human labels at research time.</p>@endforelse
</details>
@foreach($c['warnings'] as $warning)<p>{{ $warning }}</p>@endforeach
@endforeach
@endif
</x-filament::section>
