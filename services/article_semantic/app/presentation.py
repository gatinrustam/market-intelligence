"""Read-only localized labels. Source titles and evidence are never translated."""
import copy
TOPICS_RU={'monetary_policy':'Денежно-кредитная политика','interest_rates':'Процентные ставки','inflation':'Инфляция','employment':'Занятость','economic_growth':'Экономический рост','financial_regulation':'Финансовое регулирование','crypto_regulation':'Регулирование криптоактивов','enforcement':'Правоприменение','crypto_exchange':'Криптобиржи','exchange_outage':'Сбой торгов','withdrawal_suspension':'Ограничение вывода средств','security_incident':'Инцидент безопасности','hack':'Взлом','stablecoin':'Стейблкоины','depeg':'Потеря привязки','etf':'Биржевые фонды','institutional_crypto':'Институциональные криптоинвестиции','treasury_purchase':'Покупка криптоактивов на баланс','equities':'Акции','earnings':'Корпоративная отчетность','merger_acquisition':'Слияния и поглощения','general_commentary':'Общий комментарий','personnel':'Кадровые изменения','administrative':'Административное сообщение','trading_suspension':'Приостановка или возобновление торгов','listing':'Листинг','risk_parameters':'Риск-параметры','fx_market':'Валютный рынок','cash_policy':'Наличные деньги и цифровая валюта ЦБ'}
REASONS_RU={'No sentence-level topic support; a chunk similarity alone is insufficient':'Нет подтверждения темы в предложениях; сходства одного фрагмента недостаточно','Positive evidence does not exceed negative examples by the configured margin':'Сходство с положительными примерами недостаточно превосходит отрицательные','A: exact DI fact support':'A: поддержка точным DI-фактом','B: explicit sentence topic with canonical/entity-action or measurement support':'B: тема подтверждается сущностью и действием либо измерением в предложении','C: at least two non-overlapping sentence groups in independent topic-supported chunks':'C: минимум два независимых фрагмента с подтвержденной темой','D: very strong contrastive semantic chunk plus extracted entity evidence':'D: очень сильное смысловое совпадение и извлеченная сущность','Candidate only: insufficient independent or relational evidence':'Только кандидат: недостаточно независимых фрагментов или связей'}
REASONS_RU.update({'Educational or test-environment context; not market-event evidence':'Образовательное мероприятие или тестовый контур; это не рыночное событие','B: explicit administrative document event and matching body evidence':'B: административное событие в заголовке подтверждается текстом'})
def _project_insight(result):
    ru=result['document']['language']=='ru';topics=[x['concept_id'] for x in result['semantic_concepts']]
    if ru:
        why=['Есть конкретное событие, подтвержденное исходными фрагментами.' if result['information_value']['market_relevance']['level']=='high' else 'Исследовательский контекст; оснований для высокой важности недостаточно.']
        why.append('Темы: '+', '.join(TOPICS_RU.get(x,x) for x in topics)+'.' if topics else 'Подтвержденные темы не найдены.')
        why.append('Официальный первичный источник.' if result['information_value']['source_quality']['level']=='high' else 'Качество источника указано отдельно.')
        limits=['Исследовательский результат, не торговый сигнал.','Смысловое сходство не является вероятностью. Цитаты не подтверждают истинность заявления независимо от источника.']
        if result['document']['document_status']!='ready':limits.append('Доступен только неполный текст или RSS; недостающие части не восстановлены.')
        if any('failed' in w or 'unavailable' in w for w in result['warnings']):limits.append('Часть обработки недоступна; исходный DI-5 сохранен.')
    else:
        why=['Specific financial developments supported by exact rule-backed evidence.'] if result['facts'] else ['Relevant context: '+', '.join(x.replace('_',' ') for x in topics)+'. Statements remain candidates.'] if topics else ['No sufficiently supported financial concept was found.']
        for fact in result['facts'][:2]:
            rates=[v['evidence']['text'] for v in fact['values'] if v['kind']=='rate']
            if rates:why.append('Explicit rate evidence: '+', '.join(rates))
        why+=result['information_value']['source_quality']['reasons'];limits=result['warnings']
    reranking=copy.deepcopy(result.get('reranking'))
    if ru and reranking:
        for decision in reranking['decisions']:decision['reasons']=[REASONS_RU.get(r,r) for r in decision['reasons']]
    return {'semantic_id':result['semantic_id'],'document':result['document'],'status':result['status'],'potential_importance':result['information_value']['market_relevance']['level'],'why_it_matters':why,'main_topics':topics,'topic_labels':TOPICS_RU if ru else {},'article_type':result['article_type'],'affected_assets':result['affected_assets'],'key_claims':result['claims'],'important_numbers':result['important_numbers'],'entities':result['entities'],'information_value':result['information_value'],'routing':result['routing'],'limitations':limits,'conflicts':result['conflicts'],'provenance':result['provenance'],'reranking':reranking,'comparison':result.get('comparison')}

# Display labels only; immutable machine results and source quotes stay untouched.
LABELS_RU={**TOPICS_RU,'primary_announcement':'Первичное сообщение','regulatory_action':'Регуляторное действие','data_release':'Публикация данных','incident':'Инцидент','commentary':'Комментарий','interview':'Интервью','speech':'Выступление','unknown':'Не определено','complete':'Завершено','partial':'Неполный результат','failed':'Ошибка','important':'Важное','review':'На проверку','low':'Низкая','semantic_candidate':'Смысловой кандидат','supported_candidate':'Кандидат с подтверждающей связью','deterministic':'Правило DI','semantic':'Смысловой анализ','gliner':'GLiNER','di':'DI','market_relevance':'Рыночная значимость','crypto_relevance':'Криптоактивы','macro_relevance':'Макроэкономика','event_specificity':'Конкретность события','information_density':'Плотность информации','actionability':'Пригодность для исследования','source_quality':'Качество источника','document_quality':'Полнота документа','semantic_strength':'Смысловое сходство','fact_support':'Поддержка фактами','specific_event_support':'Поддержка конкретного события','high_value_fact_support':'Значимые факты','semantic_centrality':'Центральные темы','asset_relevance':'Связи с активами','rates':'Процентные ставки','crypto_market':'Рынок криптоактивов','US_equities':'Акции США','RU_equities':'Российские акции','specific_company':'Отдельная компания','gold':'Золото'}
LABELS_RU.update({'organization':'Организация','company':'Компания','person':'Человек','location':'Место','country':'Страна','economic_indicator':'Экономический показатель','instrument':'Инструмент','cryptocurrency':'Криптовалюта','date':'Дата','percentage':'Процент','money':'Денежная сумма','rate':'Ставка','quantity':'Количество'})
DISPLAY_REASONS_RU={
'Configured official primary source':'Официальный первичный источник из реестра',
'Source not in official-primary registry':'Источник отсутствует в реестре официальных первичных источников',
'Full body of the stored enriched document processed':'Обработан весь сохранённый обогащённый текст',
'Partial/RSS observed content; full original article may be unavailable':'Доступен фрагмент или RSS; полный оригинал может быть недоступен',
'Rule-backed financial facts':'Финансовые факты, извлечённые правилами DI',
'Thematic market context only; unverified event candidates':'Тематический рыночный контекст; события требуют проверки',
'Digital asset concepts present':'Присутствуют темы цифровых активов',
'No supported digital asset context':'Подтверждённый контекст цифровых активов отсутствует',
'Macro concepts with DI fact support':'Макроэкономические темы с поддержкой DI-фактами',
'Macro concept evidence':'Фрагменты с макроэкономическими темами',
'No supported macro context':'Подтверждённый макроэкономический контекст отсутствует',
'DI facts / entity-predicate candidates / topic-only evidence hierarchy':'Приоритет: DI-факты → связь сущности с действием → тематические фрагменты',
'Distinct retained claims and rule-backed facts; not a length-only score':'Количество отдельных утверждений и DI-фактов, а не длина текста',
'Research triage only; no investment or trading action is inferred':'Оценка для исследования; инвестиционное или торговое действие не предлагается',
'Thresholded cosine similarity, not a probability':'Косинусное сходство с порогом, не вероятность',
'Exact DI fact IDs retained':'Сохранены точные идентификаторы DI-фактов',
'No deterministic facts; semantic claims remain candidates':'DI-факты отсутствуют; смысловые утверждения остаются кандидатами',
'Exact DI rule-backed fact; takes precedence over semantic candidates':'Точный DI-факт имеет приоритет над смысловыми кандидатами',
'Exact text selected from a concept-supported chunk; thematic similarity is not verification of this assertion':'Точный текст из тематического фрагмента; сходство не подтверждает истинность утверждения',
'Supported digital-asset concept; broad market candidate':'Тема цифровых активов; кандидат на связь с широким рынком',
'Supported macro/monetary concepts':'Макроэкономические темы и денежно-кредитная политика',
'Extracted company with supported equity/earnings/M&A context':'Извлечённая компания в контексте акций, отчётности или сделки',
}
def present_insight(result):
    output=copy.deepcopy(_project_insight(result))
    if result.get('reranking',{}).get('status')=='complete':
        output['information_value']=copy.deepcopy(result['reranking']['importance_components'])
    if result['document']['language']!='ru':return output
    output['display_labels']=LABELS_RU
    for feature in output['information_value'].values():feature['reasons']=[DISPLAY_REASONS_RU.get(x,x) for x in feature['reasons']]
    for asset in output['affected_assets']:asset['basis']=[DISPLAY_REASONS_RU.get(x,x) for x in asset['basis']]
    for claim in output['key_claims']:claim['reason']=DISPLAY_REASONS_RU.get(claim['reason'],claim['reason'])
    return output
