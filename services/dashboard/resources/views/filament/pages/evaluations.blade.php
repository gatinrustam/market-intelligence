<x-filament-panels::page>
<x-filament::section heading="Direction accuracy · research evaluation">
<label for="evaluation-origin">Analysis origin</label>
<x-filament::input.wrapper><x-filament::input.select id="evaluation-origin" wire:model.live="origin">
<option value="model">Model analyses</option><option value="fixture">LABELLED FIXTURES — not model performance</option>
</x-filament::input.select></x-filament::input.wrapper>
<p style="margin-top:1rem">Accuracy uses scored horizons only. n = hits + misses. Unclear forecasts are not scored. Confidence is model-reported, not calibrated.</p>
@if($origin==='fixture')<div style="margin-top:1rem"><x-filament::badge color="warning">FIXTURE DATA · not actual Astra results</x-filament::badge></div>@endif
</x-filament::section>
@foreach($data as $group => $response)
<x-filament::section :heading="'Accuracy by '.str_replace('_',' ',$group)">
@if(!$response['ok'])<p>Evaluation unavailable · {{ $response['error'] }}</p>
@elseif(!$response['data']['rows'])<p>No scored samples yet. n = 0.</p>
@else
<x-research-table :headers="['Group','Basis','n · scored','Hits','Misses','Not scored','Unavailable','Pending','Accuracy %','Policy hash']" :rows="array_map(fn($row)=>[$row['group'][$group]??'Unknown',$row['group']['decision_basis']??null,$row['n']??0,$row['hits']??0,$row['misses']??0,$row['not_scored']??0,$row['unavailable']??0,$row['pending']??0,$row['direction_accuracy_pct']??null,substr($row['group']['policy_hash']??'',0,12)],$response['data']['rows'])" />
@endif
</x-filament::section>
@endforeach
</x-filament-panels::page>
