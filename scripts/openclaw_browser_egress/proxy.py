"""HTTPS CONNECT proxy which pins public IPv4 destinations before upstream routing."""
import argparse
import asyncio
import ipaddress
import re
import socket

_DENIED_V4 = tuple(map(ipaddress.ip_network, (
    '0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8', '169.254.0.0/16',
    '172.16.0.0/12', '192.0.0.0/24', '192.0.2.0/24', '192.88.99.0/24', '192.168.0.0/16',
    '198.18.0.0/15', '198.51.100.0/24', '203.0.113.0/24', '224.0.0.0/4', '240.0.0.0/4',
)))


def public_ipv4(value):
    address = ipaddress.ip_address(value)
    return (address.version == 4 and address.is_global
            and not any(address in network for network in _DENIED_V4))


def destination(request):
    line = request.decode('ascii').split('\r\n', 1)[0]
    method, authority, version = line.split(' ')
    if method != 'CONNECT' or version not in {'HTTP/1.0', 'HTTP/1.1'}:
        raise ValueError('HTTPS CONNECT required')
    host, port = authority.rsplit(':', 1)
    if port != '443' or len(host) > 253 or not re.fullmatch(r'[a-zA-Z0-9.-]+', host):
        raise ValueError('Invalid destination')
    return host


async def resolve_public(host):
    rows = await asyncio.get_running_loop().getaddrinfo(
        host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM)
    addresses = sorted({row[4][0] for row in rows})
    if not addresses or not all(public_ipv4(address) for address in addresses):
        raise ValueError('Non-public destination')
    return addresses[0]


class PublicProxy:
    def __init__(self, upstream_port, *, resolver=resolve_public):
        self.upstream_port, self.resolver = upstream_port, resolver
        self.active = 0

    @staticmethod
    async def reply(writer, status):
        writer.write(f'HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'.encode())
        await writer.drain()

    @staticmethod
    async def pump(reader, writer):
        while data := await asyncio.wait_for(reader.read(65536), 60):
            writer.write(data)
            await writer.drain()

    async def connect(self, reader, writer):
        upstream_writer = None
        pumps = []
        if self.active >= 64:
            writer.close()
            return
        self.active += 1
        established = False
        try:
            request = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
            host = destination(request)
            address = await asyncio.wait_for(self.resolver(host), 10)
            if not public_ipv4(address):
                raise ValueError('Non-public destination')
            upstream_reader, upstream_writer = await asyncio.wait_for(
                asyncio.open_connection('127.0.0.1', self.upstream_port, limit=8192), 10)
            # The upstream receives only the checked IP, never a hostname to resolve again.
            upstream_writer.write(f'CONNECT {address}:443 HTTP/1.1\r\nHost: {address}:443\r\n\r\n'.encode())
            await upstream_writer.drain()
            response = await asyncio.wait_for(upstream_reader.readuntil(b'\r\n\r\n'), 15)
            if response.split(b'\r\n', 1)[0].split(b' ')[1:2] != [b'200']:
                raise OSError('Upstream refused tunnel')
            writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            await writer.drain()
            established = True
            pumps = [asyncio.create_task(self.pump(reader, upstream_writer)),
                     asyncio.create_task(self.pump(upstream_reader, writer))]
            await asyncio.wait(pumps, timeout=300, return_when=asyncio.FIRST_COMPLETED)
        except (ValueError, UnicodeError):
            if not established:
                await self.reply(writer, '403 Forbidden')
        except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            if not established:
                try:
                    await self.reply(writer, '502 Bad Gateway')
                except OSError:
                    pass
        finally:
            for task in pumps:
                task.cancel()
            if pumps:
                await asyncio.gather(*pumps, return_exceptions=True)
            if upstream_writer:
                upstream_writer.close()
            writer.close()
            self.active -= 1


async def serve(port, upstream_port):
    proxy = PublicProxy(upstream_port)
    server = await asyncio.start_server(proxy.connect, '127.0.0.1', port, limit=8192)
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--upstream-port', type=int, required=True)
    args = parser.parse_args()
    asyncio.run(serve(args.port, args.upstream_port))
