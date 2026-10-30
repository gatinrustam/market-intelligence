from unittest.mock import AsyncMock

import pytest

from app.fetching.security import URLGuard
from app.models.errors import ProcessingError


@pytest.mark.parametrize('scheme', ['http', 'https'])
async def test_public_destination_and_pinning(scheme):
    resolver = AsyncMock(return_value=['93.184.216.34'])
    result = await URLGuard(resolver).validate(scheme+'://example.org/article', ['example.org'])
    assert result.ip == '93.184.216.34' and result.hostname == 'example.org'
    resolver.assert_awaited_once()


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'ftp://example.org/a', 'data:text/plain,hello',
    'javascript:alert(1)', 'gopher://example.org', 'http://localhost/a', 'http://db/a', 'http://127.0.0.1/a',
    'http://10.0.0.1/a', 'http://172.16.0.1/a', 'http://192.168.1.1/a', 'http://169.254.169.254/a',
    'http://0.0.0.0/a', 'http://224.0.0.1/a', 'http://[::1]/a', 'http://[::ffff:127.0.0.1]/a',
    'https://example.org@evil.org/a', 'https://user:password@example.org/a', 'https://evil.org/a',
    'https://example.org.evil.org/a', 'https://example.org:8443/a', 'https://example.org./a',
    'https://example.org\\@127.0.0.1/a', 'http://2130706433/', 'http://example.org/%0a', 'http://bad host/'])
async def test_unsafe_urls(url):
    resolver = AsyncMock(return_value=['127.0.0.1'])
    with pytest.raises(ProcessingError) as error:
        await URLGuard(resolver).validate(url, ['example.org'])
    assert error.value.rejected


@pytest.mark.parametrize('answers', [['127.0.0.1'], ['10.10.0.1'], ['169.254.0.1'], ['::1'], ['fc00::1'],
    ['fe80::1'], ['224.1.1.1'], ['0.0.0.0'], ['192.0.2.1'], ['93.184.216.34','127.0.0.1']])
async def test_dns_and_mixed_public_private_rejected(answers):
    resolver = AsyncMock(return_value=answers)
    with pytest.raises(ProcessingError):
        await URLGuard(resolver).validate('https://example.org/a', ['example.org'])


async def test_rebinding_checked_each_time():
    guard = URLGuard(AsyncMock(side_effect=[['93.184.216.34'], ['10.0.0.1']]))
    assert (await guard.validate('https://example.org/a', ['example.org'])).ip == '93.184.216.34'
    with pytest.raises(ProcessingError):
        await guard.validate('https://example.org/a', ['example.org'])
