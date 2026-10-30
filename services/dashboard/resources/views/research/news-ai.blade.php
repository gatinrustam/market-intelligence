<x-filament::section heading="AI-анализ" icon="heroicon-o-sparkles" icon-color="primary">
@if(!$market['analyses'])
<x-filament::badge :color="$color($market['analysis_state'])">{{ $label($market['analysis_state']) }}</x-filament::badge>
<p class="news-muted">{{ $market['analysis_state']==='unavailable' ? 'Сервис анализа сейчас недоступен. Состояние запусков не удалось проверить.' : ($market['event_linked'] ? 'AI-анализ этой ревизии события ещё не запускался.' : 'Нет связанного канонического события для проверки AI-анализа.') }}</p>
@else
@foreach(($compact??false) ? array_slice($market['analyses'],0,1) : $market['analyses'] as $analysis)
<div class="news-analysis-run"><x-filament::badge :color="$color($analysis['analysis_status'])">{{ $label($analysis['analysis_status']) }}</x-filament::badge>
<p class="news-caption">{{ ($analysis['basis']??'')==='live' ? 'Фактическое live-наблюдение' : 'Историческая симуляция · не live-решение' }}</p>
@if(in_array($analysis['analysis_status'],['blocked','failed']))<p>{{ $label(is_string($analysis['error']??null) ? $analysis['error'] : null) }}</p>
@elseif($analysis['analysis_status']==='completed')
<p class="news-muted">{{ data_get($analysis,'configuration.model') }} · BTC: {{ $label(data_get($analysis,'analysis.asset.relevance')) }}</p><p>{{ data_get($analysis,'analysis.interpretation.summary') }}</p>
@if(!($compact??false))<p class="news-muted">{{ data_get($analysis,'analysis.interpretation.market_mechanism') }}</p>
<x-research-table :headers="['Горизонт','Направление','Влияние','Уверенность']" :rows="array_map(fn($f)=>[($f['horizon_seconds']/60).' мин',$label($f['direction']),$label($f['impact']),$label($f['confidence'])],data_get($analysis,'analysis.forecast',[]))" />
<p class="news-caption">Уверенность сообщена моделью, это не калиброванная вероятность. Prompt: {{ data_get($analysis,'configuration.prompt_version') }}</p>@endif
@endif</div>
@endforeach
@if($compact??false)<x-filament::button outlined color="gray" x-on:click="tab = 'analysis'">Открыть анализ</x-filament::button>@endif
@endif
<p class="news-caption">Сохранённые результаты. Просмотр не запускает модель.</p>
</x-filament::section>
