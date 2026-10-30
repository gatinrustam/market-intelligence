<x-filament-panels::page>
<x-filament::section heading="Pipeline · read-only research">
@foreach(app(\App\Research\Health::class)->all() as $service)
<div style="display:flex;justify-content:space-between;margin:0.6rem 0"><span>{{ $service['service'] }}</span><x-filament::badge :color="\App\Research\Display::color($service['status'])">{{ $service['status'] }}</x-filament::badge></div>
@endforeach
</x-filament::section>
<x-filament::section heading="Counters"><x-research-fields :fields="$data['counters']" /><p style="margin-top:1rem">News total is unavailable: Ingestion exposes poll counters, not a cumulative total.</p></x-filament::section>
@foreach($data['errors'] as $error)<x-research-error :message="$error" />@endforeach
@include('research.market',['data'=>$data['market']])
</x-filament-panels::page>
