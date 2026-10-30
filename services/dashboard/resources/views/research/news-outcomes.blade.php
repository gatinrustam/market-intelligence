<x-filament::section heading="Что произошло после" icon="heroicon-o-clock" icon-color="primary">
<p class="news-caption">Только для оценки прогноза. Эти данные не были доступны модели в момент решения.</p>
@if(!$market['evaluations'])<p class="news-muted">Оценка пока недоступна. Нужны сохранённый прогноз и последующие рыночные наблюдения.</p>
@elseif($compact??false)<p class="news-muted">Есть сохранённая оценка прогноза.</p><x-filament::button outlined color="gray" x-on:click="tab = 'evaluation'">Посмотреть результат</x-filament::button>
@else
@foreach($market['evaluations'] as $evaluation)
<p class="news-caption">Решение: {{ \App\Research\Display::utc(data_get($evaluation,'decision.decision_at')) }} · {{ data_get($evaluation,'decision.historical_simulation') ? 'Историческая симуляция' : 'Live-наблюдение' }}</p>
<div style="overflow-x:auto"><table style="width:100%;text-align:left;border-collapse:collapse"><thead><tr>@foreach(['Горизонт','Прогноз','Факт','Доходность','Результат'] as $heading)<th style="padding:8px">{{ $heading }}</th>@endforeach</tr></thead><tbody>
@foreach($evaluation['results'] as $row)<tr><td style="padding:8px">+{{ $row['horizon_seconds']/60 }} мин</td><td>{{ $label(data_get($row,'forecast.direction')) }}</td><td>{{ $label(data_get($row,'actual.direction')) }}</td><td>{{ data_get($row,'actual.return_pct')===null ? '—' : data_get($row,'actual.return_pct').'%' }}</td><td><x-filament::badge :color="$color(data_get($row,'evaluation.direction_result',$row['status']))">{{ $label(data_get($row,'evaluation.direction_result',$row['status'])) }}</x-filament::badge></td></tr>@endforeach
</tbody></table></div>
@endforeach
@endif
</x-filament::section>
