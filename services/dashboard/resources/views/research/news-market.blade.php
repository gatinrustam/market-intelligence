<x-filament::section heading="Рынок на момент решения" icon="heroicon-o-chart-bar" icon-color="primary">
<p class="news-caption">Только данные до решения · live-наблюдение</p>
@if(!$points)<p class="news-empty">Рыночные данные для этого момента недоступны.</p>
@elseif(!collect($points)->contains(fn($point)=>$point['offset_seconds']===0))<p class="news-empty">Точка T недоступна или устарела. Рыночный пакет неполный.</p>@endif
@if($points)
@php($atT=collect($points)->firstWhere('offset_seconds',0))
@if($atT)<p class="news-caption">BTCUSDT</p><p class="news-mini-price">{{ number_format((float)$atT['price'],2,'.',' ') }} <small>USDT</small></p>@endif
<p class="news-caption">Решение: {{ \App\Research\Display::utc(data_get($market,'decision.data.decision_at')) }}</p>
@if($expanded)<x-research-table :headers="['Время','Цена · USDT','Наблюдение · UTC']" :rows="array_map(fn($point)=>[match($point['offset_seconds']){-900=>'T−15m',-300=>'T−5m',default=>'T'},$point['price'],\App\Research\Display::utc($point['price_at'])],$points)" />
<p class="news-caption">Только доступные causal points в пределах допустимого возраста. Решение может быть позже публикации.</p>
@else<x-filament::button outlined color="gray" x-on:click="tab = 'market'">Посмотреть контекст</x-filament::button>@endif
@endif
</x-filament::section>
