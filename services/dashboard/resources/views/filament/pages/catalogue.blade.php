<x-filament-panels::page>
@php($catalogue=$this->catalogue())
<x-research-error :message="$catalogue['error']" />
<x-research-error :message="isset($catalogue['llm_error']) ? 'LLM Analysis: '.$catalogue['llm_error'] : null" />
@if($catalogue['truncated'])<x-research-error message="Catalogue capped at 1,000 records. Filters and search apply to loaded records only." />@endif
{{ $this->table }}
</x-filament-panels::page>
