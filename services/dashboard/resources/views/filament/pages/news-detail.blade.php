<x-filament-panels::page>
@include('research.news-style')
@if(!$result['ok'])
<x-filament::section heading="Статья недоступна"><p>Article Router unavailable · {{ $result['error'] }}</p></x-filament::section>
@else
@php
    $data=$result['data']; $p=$presentation; $document=$p['document']; $insight=$p['insight'];
    $label=fn($value)=>\App\Research\NewsPresentation::label($value);
    $color=fn($value)=>\App\Research\NewsPresentation::color($value);
    $source=\App\Research\NewsPresentation::source($document['source']['id']);
    $points=\App\Research\NewsPresentation::causalPoints($market['decision']);
@endphp
<div class="news-detail" x-data="{ tab: 'overview', audit: 'routing' }">
<a class="news-back" href="{{ \App\Filament\Pages\NewsFeed::getUrl() }}"><x-filament::icon icon="heroicon-o-arrow-left" class="news-icon" /> News Feed <span>/</span> Новость</a>
<header class="news-heading">
<div><p class="news-eyebrow">{{ $source }} · {{ $label($insight['article_type'] ?? null) }}</p>
<h1>{{ $document['content']['title'] }}</h1>
<p class="news-muted">{{ $source }} <span class="news-dot">·</span> {{ \App\Research\Display::utc($document['timestamps']['published_at']) }}</p></div>
@if($p['url'])<x-filament::button tag="a" :href="$p['url']" target="_blank" rel="noopener noreferrer" outlined icon="heroicon-o-arrow-top-right-on-square">Открыть источник</x-filament::button>@endif
</header>
<div class="news-badges">
<x-filament::badge :color="$color($p['priority'])">{{ $label($p['priority']) }}</x-filament::badge>
@foreach(array_slice($p['topics'],0,4) as $topic)<x-filament::badge color="info">{{ $label($topic) }}</x-filament::badge>@endforeach
@foreach(array_slice($p['assets'],0,3) as $asset)<x-filament::badge color="gray">{{ $label($asset['asset']) }}</x-filament::badge>@endforeach
<x-filament::badge color="gray">{{ strtoupper($document['content']['language']) }}</x-filament::badge>
</div>
@if($p['suggested'] && $p['suggested'] !== $p['route'])<p class="news-caption">Показан приоритет семантического анализа. Текущая очередь: {{ $label($p['route']) }}. Автоматически не изменена.</p>@endif
<div class="news-navigation">
<x-filament::tabs label="Разделы статьи">
@foreach(['overview'=>'Обзор','analysis'=>'Анализ','source'=>'Исходная статья','market'=>'Рынок и контекст','evaluation'=>'Оценка'] as $key=>$name)
<x-filament::tabs.item :alpine-active="'tab === '.json_encode($key)" x-on:click="tab = '{{ $key }}'">{{ $name }}</x-filament::tabs.item>
@endforeach
</x-filament::tabs>
</div>
<div class="news-layout">
<main class="news-main">
<div x-show="tab === 'overview'">
<x-filament::section heading="Что произошло" icon="heroicon-o-document-text" icon-color="primary">
<p class="news-summary">{{ $p['summary'] ?: 'Текст статьи пока недоступен.' }}</p>
<p class="news-caption">{{ $p['event'] ? 'Заголовок связанного события' : ($insight ? 'Извлечённый фрагмент источника · не AI-резюме' : 'Фрагмент исходной статьи') }}</p>
<div class="news-why"><h3><x-filament::icon icon="heroicon-o-light-bulb" class="news-icon" /> Почему это важно</h3>
<ul>@foreach(array_slice($p['reasons'],0,3) as $reason)<li>{{ $reason }}</li>@endforeach</ul>
@if(data_get($document,'enrichment.status')!=='ready')<p>Доступен неполный текст. Выводы ограничены содержимым RSS.</p>@endif
</div>
</x-filament::section>
</div>
<div x-show="tab === 'overview' || tab === 'analysis'">
<x-filament::section heading="Ключевые факты и утверждения" icon="heroicon-o-clipboard-document-check" icon-color="primary">
<x-slot name="afterHeader"><x-filament::badge color="gray">{{ count($p['facts']) }}</x-filament::badge></x-slot>
@if(!$p['facts'])<p class="news-muted">Подтверждённые факты пока не извлечены. Исходная статья доступна ниже.</p>@else
<div x-data="{ allFacts: false }">
<div class="news-fact-grid">
@foreach($p['facts'] as $fact)
<article class="news-fact" @if($loop->index>=4) x-show="allFacts" x-cloak @endif>
<div class="news-fact-title"><x-filament::icon icon="heroicon-o-check-badge" class="news-icon" /><h3>{{ $fact['title'] }}</h3></div>
@if($fact['value'])<p class="news-fact-value">{{ $fact['value'] }}</p>@endif
@if($fact['state'] && $fact['state']!=='Не определено')<x-filament::badge color="info">{{ $fact['state'] }}</x-filament::badge>@endif
<p class="news-fact-text">{{ \Illuminate\Support\Str::limit($fact['text'],235) }}</p>
<p class="news-caption">{{ $fact['basis'] }}</p>
<details class="news-evidence"><summary>Показать фрагмент</summary><p class="news-caption">Источник в статье</p><blockquote><mark>{{ $fact['text'] }}</mark></blockquote></details>
</article>
@endforeach
</div>
@if(count($p['facts'])>4)<x-filament::button color="gray" outlined x-on:click="allFacts = !allFacts" class="news-more"><span x-text="allFacts ? 'Свернуть' : 'Показать все ({{ count($p['facts']) }})'"></span></x-filament::button>@endif
</div>
@endif
</x-filament::section>
</div>
<div x-show="tab === 'overview' || tab === 'analysis'">
<x-filament::section heading="Что нашла система" icon="heroicon-o-square-3-stack-3d" icon-color="primary">
<div class="news-intelligence">
<div><h3>Темы</h3><div class="news-badges">@forelse($p['topics'] as $topic)<x-filament::badge color="info">{{ $label($topic) }}</x-filament::badge>@empty<p class="news-muted">Пока не определены</p>@endforelse</div></div>
<div><h3>Сущности</h3><div class="news-badges">@forelse(array_slice($p['entities'],0,8) as $entity)<x-filament::badge color="gray">{{ $entity }}</x-filament::badge>@empty<p class="news-muted">Пока не определены</p>@endforelse</div>
@if(count($p['entities'])>8)<details><summary>Ещё {{ count($p['entities'])-8 }}</summary><p>{{ implode(', ',array_slice($p['entities'],8)) }}</p></details>@endif<p class="news-caption">Извлечены из текста; требуют проверки.</p></div>
<div><h3>Рынки и активы</h3>@forelse($p['assets'] as $asset)<details class="news-asset"><summary>{{ $label($asset['asset']) }} <x-filament::badge color="gray">{{ $label($asset['relevance']) }}</x-filament::badge></summary>@foreach($asset['evidence'] as $evidence)<blockquote><mark>{{ $evidence['text'] }}</mark></blockquote>@endforeach</details>@empty<p class="news-muted">Достаточных оснований для связи с активами нет.</p>@endforelse<p class="news-caption">Релевантность, не прогноз цены.</p></div>
</div>
</x-filament::section>
</div>
<div x-show="tab === 'analysis'" x-cloak>
<x-filament::section heading="Семантический анализ" icon="heroicon-o-sparkles" icon-color="primary">
@if($insight)
<dl class="news-properties"><dt>Основная тема</dt><dd>{{ $label($p['topics'][0]??null) }}</dd><dt>Тип материала</dt><dd>{{ $label($insight['article_type']) }}</dd><dt>Информационная ценность</dt><dd>{{ $label($insight['potential_importance']) }}</dd></dl>
<p class="news-muted">В основных карточках показаны только принятые темы. Кандидаты, отклонения и сравнение с DI-5 доступны в Audit.</p>
@else<p class="news-muted">{{ $insightResult['ok'] ? 'Семантический анализ ожидается.' : 'Сервис семантического анализа сейчас недоступен.' }}</p>@endif
</x-filament::section>
</div>
<div x-show="tab === 'overview' || tab === 'source'">
<x-filament::section heading="Исходная статья" icon="heroicon-o-document" icon-color="primary">
<div x-data="{ full: false }">
<p class="news-article news-excerpt" x-show="!full">{{ \Illuminate\Support\Str::limit($p['body'],700) }}</p>
<div class="news-article" x-show="full" x-cloak>@foreach(preg_split('/\n\s*\n|\n/u',$p['body']) as $paragraph)@if(trim($paragraph)!=='')<p>{{ $paragraph }}</p>@endif@endforeach</div>
<div class="news-source-actions"><x-filament::button outlined color="gray" x-on:click="full = !full"><span x-text="full ? 'Свернуть текст' : 'Показать полностью'"></span></x-filament::button>
@if($p['url'])<x-filament::button tag="a" :href="$p['url']" target="_blank" rel="noopener noreferrer" outlined icon="heroicon-o-arrow-top-right-on-square">Открыть источник</x-filament::button>@endif</div>
<p class="news-caption">{{ data_get($document,'enrichment.status')==='ready' ? 'Сохранённый текст статьи' : 'Неполный текст / RSS' }}. Поздняя загрузка не подтверждает историческую идентичность страницы.</p>
</div>
</x-filament::section>
</div>
<div x-show="tab === 'market'" x-cloak>@include('research.news-market', ['expanded'=>true])</div>
<div x-show="tab === 'analysis'" x-cloak>@include('research.news-ai')</div>
<div x-show="tab === 'evaluation'" x-cloak>@include('research.news-outcomes')</div>
<div x-show="tab === 'evaluation'" x-cloak><x-filament::section heading="Оценка статьи" icon="heroicon-o-user-circle"><p class="news-muted">Оценка редактора сохраняется отдельно от результатов системы.</p>{{ $this->reviewAction }}</x-filament::section></div>
</main>
<aside class="news-aside">
<x-filament::section heading="Основная информация" icon="heroicon-o-information-circle" icon-color="primary">
<dl class="news-properties"><dt>Источник</dt><dd>{{ $source }}</dd><dt>Опубликовано</dt><dd>{{ \App\Research\Display::utc($document['timestamps']['published_at']) }}</dd><dt>Язык</dt><dd><x-filament::badge color="gray">{{ strtoupper($document['content']['language']) }}</x-filament::badge></dd><dt>Тип материала</dt><dd>{{ $label($insight['article_type']??null) }}</dd><dt>Качество источника</dt><dd>Официальный первоисточник</dd><dt>Статус анализа</dt><dd><x-filament::badge :color="$color($insight['status']??'pending')">{{ $label($insight['status']??'pending') }}</x-filament::badge></dd><dt>Проверка статьи</dt><dd>{{ $label($data['review']['status']) }}</dd></dl>
</x-filament::section>
<div x-show="tab !== 'market'">@include('research.news-market', ['expanded'=>false])</div>
<div x-show="tab !== 'analysis'">@include('research.news-ai', ['compact'=>true])</div>
<div x-show="tab !== 'evaluation'">@include('research.news-outcomes', ['compact'=>true])</div>
<x-filament::section heading="Human Review" icon="heroicon-o-user-circle" icon-color="success">
<x-filament::badge :color="$color($data['review']['status'])">{{ $label($data['review']['status']) }}</x-filament::badge>
<p class="news-muted">{{ $data['labels'] ? 'Оценка статьи сохранена. История доступна в Audit.' : 'Редакторская оценка статьи ещё не добавлена.' }}</p>
@if(data_get($insightResult,'data.0.labels'))<p class="news-caption">Для семантического анализа есть отдельные оценки; pilot-разметка не равна независимой проверке.</p>@endif
@if($data['labels'])
@php($reviewLabel=end($data['labels']))
<dl class="news-properties" style="margin:12px 0"><dt>Полезная статья</dt><dd>{{ ['useful'=>'Да','not_useful'=>'Нет'][$reviewLabel['usefulness']??'']??'Не оценено' }}</dd><dt>Приоритет редактора</dt><dd>{{ ($reviewLabel['priority_override']??null) ? $label($reviewLabel['priority_override']) : 'Без изменения' }}</dd><dt>Факты корректны</dt><dd>{{ ($reviewLabel['facts_correct']??null)===null ? 'Не оценено' : ($reviewLabel['facts_correct'] ? 'Да' : 'Нет') }}</dd><dt>Тип события</dt><dd>{{ ($reviewLabel['event_type_correct']??null)===null ? 'Не оценено' : ($reviewLabel['event_type_correct'] ? 'Верный' : 'Неверный') }}</dd><dt>Передать в LLM</dt><dd>{{ ($reviewLabel['send_to_llm']??false) ? 'Да · отметка' : 'Нет' }}</dd></dl>
@endif
{{ $this->reviewAction }}
</x-filament::section>
</aside>
</div>
<x-filament::section heading="Advanced / Audit" icon="heroicon-o-cog-6-tooth" collapsible collapsed id="news-audit" description="Технические основания, сравнение версий и неизменённая история">
<div class="news-navigation"><x-filament::tabs label="Разделы аудита">
@foreach(['routing'=>'Routing','di'=>'Document Intelligence','semantic'=>'Semantic Intelligence','events'=>'Event Engine','correlation'=>'Correlation','provenance'=>'Provenance','json'=>'Raw JSON'] as $key=>$name)<x-filament::tabs.item :alpine-active="'audit === '.json_encode($key)" x-on:click="audit = '{{ $key }}'">{{ $name }}</x-filament::tabs.item>@endforeach
</x-filament::tabs></div>
<div x-show="audit === 'routing'"><h3>Routing features and reasons</h3><x-research-fields :fields="['Machine route'=>$p['route'],'Suggested route'=>$p['suggested'],'Ruleset'=>data_get($data,'machine.basis.ruleset_version')]" />
@foreach($data['machine']['features'] as $key=>$value)<p>{{ $key }}: {{ \App\Research\Display::text($value) }} — {{ data_get($data,'machine.basis.feature_basis.'.$key.'.reason') }}</p>@endforeach
@foreach(data_get($data,'machine.basis.reasons',[]) as $reason)<p>{{ $reason }}</p>@endforeach
</div>
<div x-show="audit === 'di'" x-cloak><h3>Document Intelligence and evidence</h3>@include('research.document-intelligence',['item'=>['reference'=>['document_id'=>$document['document_id']],'document'=>$document,'intelligence'=>['ok'=>true,'data'=>[$data['snapshot']['intelligence']]]]])</div>
<div x-show="audit === 'semantic'" x-cloak>@include('research.article-insight',['insightResult'=>$insightResult,'showReview'=>false])</div>
<div x-show="audit === 'events'" x-cloak>@include('research.event-comparison')@foreach($data['snapshot']['events'] as $event)<x-research-fields :fields="['Event ID'=>data_get($event,'event.id'),'Revision'=>data_get($event,'event.revision'),'Event type'=>data_get($event,'taxonomy.event_type')]" />@endforeach</div>
<div x-show="audit === 'correlation'" x-cloak>@include('research.correlation',['correlationResult'=>$correlationResult])</div>
<div x-show="audit === 'provenance'" x-cloak><x-research-fields :fields="['Document ID'=>$document['document_id'],'Input message'=>$document['message_id'],'Timestamps'=>$document['timestamps'],'Semantic provenance'=>$insight['provenance']??[], 'Review revision'=>$data['review']['revision']]" />@foreach($market['errors'] as $error)<p>{{ $error }}</p>@endforeach</div>
<div x-show="audit === 'json'" x-cloak><h3>Raw JSON · immutable snapshots / review history</h3><pre>{{ json_encode(['article'=>$data,'semantic'=>$insightResult,'event_research'=>$comparisonResult,'correlation'=>$correlationResult,'market_analysis_evaluation'=>$market],JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES) }}</pre></div>
</x-filament::section>
</div>
@endif
</x-filament-panels::page>
