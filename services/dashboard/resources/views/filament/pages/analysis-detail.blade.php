<x-filament-panels::page>
<x-research-error :message="$result['error']" />
@if($result['ok'])<x-filament::section heading="LLM analysis · audit only">@include('research.analysis',['analysis'=>$result['data']])</x-filament::section>@endif
</x-filament-panels::page>
