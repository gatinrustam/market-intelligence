import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from app.models.errors import ProcessingError


@dataclass(frozen=True)
class Destination:
    url: str
    hostname: str
    port: int
    ip: str


async def resolve_public_addresses(hostname, port):
    try:
        records = await asyncio.to_thread(socket.getaddrinfo, hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ProcessingError('dns_temporary_failure' if exc.errno == socket.EAI_AGAIN else 'dns_failure',
                              transient=exc.errno == socket.EAI_AGAIN) from None
    return list(dict.fromkeys(record[4][0] for record in records))


def is_public(ip):
    address = ipaddress.ip_address(ip)
    # is_global alone includes multicast in some Python versions.
    return (address.is_global and not address.is_multicast and not address.is_reserved
            and not address.is_unspecified and not address.is_loopback and not address.is_link_local
            and not getattr(address, 'ipv4_mapped', None) and '%' not in ip)


class URLGuard:
    def __init__(self, resolver=resolve_public_addresses):
        self.resolver = resolver

    async def validate(self, url, allowed_hosts):
        try:
            if not isinstance(url, str) or len(url) > 8192 or re.search(r'[\x00-\x20\x7f\\]', url):
                raise ValueError()
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https'):
                raise ProcessingError('unsupported_scheme', rejected=True)
            if parsed.username is not None or parsed.password is not None:
                raise ProcessingError('url_credentials', rejected=True)
            host = parsed.hostname
            if not host or host.endswith('.') or '%' in host:
                raise ValueError()
            host = host.encode('idna').decode('ascii').lower()
            if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')) or '.' not in host:
                raise ProcessingError('internal_host', rejected=True)
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            if port != (443 if parsed.scheme == 'https' else 80):
                raise ProcessingError('port_not_allowed', rejected=True)
            try:
                if not is_public(host):
                    raise ProcessingError('non_public_address', rejected=True)
            except ValueError:
                if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) or '..' in host:
                    raise ValueError()
            if host not in allowed_hosts:
                raise ProcessingError('host_not_allowed', rejected=True)
        except (ValueError, UnicodeError):
            raise ProcessingError('invalid_url', rejected=True) from None
        addresses = await self.resolver(host, port)
        try:
            if not addresses or any(not is_public(ip) for ip in addresses):
                raise ProcessingError('non_public_address', rejected=True)
        except ValueError:
            raise ProcessingError('invalid_dns_answer', rejected=True) from None
        # Prefer IPv4 where public dual-stack exists; never resolve this hostname again in HTTP transport.
        ip = sorted(addresses, key=lambda value: ':' in value)[0]
        clean_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/', parsed.query, ''))
        return Destination(clean_url, host, port, ip)
