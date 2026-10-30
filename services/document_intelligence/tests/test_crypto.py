from pathlib import Path
from app.config import Settings
from app.domain import load_configuration
from app.pipeline import Pipeline, validate_spans
from app.schema import Output


def crypto_pipeline():
    return Pipeline(load_configuration(Settings(rules_path=Path('/workspace/config/document_intelligence/rules.crypto.v1.1.json'))))


def test_explicit_treasury_values_and_no_arithmetic(document):
    pipe=crypto_pipeline()
    body='Strategy published its Bitcoin treasury acquisition report. BTC Acquired: 520 Aggregate Purchase Price: $34.9m Average Purchase Price: $67,068.'
    out=pipe.analyze(document(body));validate_spans(out,body);Output.model_validate(out)
    facts=[f for f in out['facts'] if f.get('quantity')]
    assert len(facts)==1
    assert {k:facts[0][k] for k in ('asset','quantity','aggregate_value_usd','average_price_usd')}=={'asset':'BTC','quantity':'520','aggregate_value_usd':'34900000','average_price_usd':'67068'}
    assert len(facts[0]['values'])==3
    missing=pipe.analyze(document(body.replace(' Average Purchase Price: $67,068','')))
    assert not any(f.get('average_price_usd') for f in missing['facts'])
    hypothetical=pipe.analyze(document(body.replace('BTC Acquired:', 'Hypothetical example: BTC Acquired:')))
    assert not any(f.get('quantity') for f in hypothetical['facts'])


def test_crypto_facts_are_versioned_and_exact(document):
    pipe=crypto_pipeline()
    for body,expected in [
        ('Binance delisted the token from spot trading.','crypto.exchange_delisting'),
        ('Kraken suspended deposits for Bitcoin.','crypto.deposit_suspension'),
        ('Kraken suspended withdrawals for Bitcoin.','crypto.withdrawal_suspension'),
        ('Kraken experienced a service outage.','crypto.exchange_outage'),
        ('Circle launched USDC stablecoin infrastructure.','crypto.stablecoin_change'),
        ('Coinbase launched institutional crypto derivatives.','crypto.institutional_product'),
        ('Strategy holds 520 BTC in its corporate treasury.','crypto.treasury_holdings'),
    ]:
        out=pipe.analyze(document(body));validate_spans(out,body)
        assert expected in [f['fact_type'] for f in out['facts']],(body,out['processing'],out['relations'])
    out=pipe.analyze(document('Binance did not delist the token from spot trading.'))
    assert not out['facts']


def test_scheduled_listing_is_an_announcement_not_completed_listing(document):
    pipe=crypto_pipeline()
    out=pipe.analyze(document('Binance will list the new cryptocurrency token for spot trading.'))
    facts=[f for f in out['facts'] if f['fact_type']=='crypto.exchange_listing']
    assert facts and facts[0]['action']=='announced_list'
    assert not pipe.analyze(document('Binance may list the new cryptocurrency token for spot trading.'))['facts']


def test_research_word_is_not_arc_and_announced_mainnet_is_evidenced(document):
    pipe=crypto_pipeline()
    out=pipe.analyze(document('Tether AI Research launches open-weight vision-language models for smartphones.'))
    assert not out['facts']
    out=pipe.analyze(document('Circle today announced the public mainnet launch of Arc, an open blockchain built for financial markets.'))
    assert any(f['fact_type']=='crypto.stablecoin_change' for f in out['facts'])
