#!/usr/bin/env python3
"""Check one IPv4 UDP STUN endpoint without changing proxy or network settings.

Uses ordinary sockets, so ON/OFF and the existing routing rules determine the
path. A failed probe only means this endpoint did not complete this check;
it does not establish that all UDP is unavailable. No geographic lookup occurs.

Wire format: https://datatracker.ietf.org/doc/html/rfc5389 (sections 6 and 15).
This is an unauthenticated diagnostic, not a complete STUN client.
"""
import argparse
import ipaddress
import math
import queue
import secrets
import socket
import struct
import sys
import threading
import time
import zlib

COOKIE = 0x2112A442
MAPPED = 0x0001
XOR_MAPPED = 0x0020
FINGERPRINT = 0x8028


def mapped_ipv4(value, *, xor):
    if len(value) < 4:
        raise ValueError('STUN address attribute is too short')
    family = value[1]
    if family not in (1, 2):
        return None  # Unknown address families are ignored (RFC 5389).
    if len(value) != (8 if family == 1 else 20):
        raise ValueError('STUN address attribute has an invalid length')
    if family != 1:
        return None  # This diagnostic deliberately reports IPv4 only.
    port = struct.unpack('!H', value[2:4])[0]
    address = int.from_bytes(value[4:8], 'big')
    if xor:
        port ^= COOKIE >> 16
        address ^= COOKIE
    ip = ipaddress.IPv4Address(address)
    if not port or ip.is_unspecified or ip.is_multicast:
        raise ValueError('STUN returned an unusable mapped address')
    return str(ip), port


def parse_response(packet, transaction_id):
    """Return (IPv4, port), rejecting malformed, unrelated or error replies."""
    if len(transaction_id) != 12 or len(packet) < 20:
        raise ValueError('Invalid STUN transaction or truncated header')
    message_type, length, cookie, received_id = struct.unpack('!HHI12s', packet[:20])
    if cookie != COOKIE or received_id != transaction_id:
        raise ValueError('STUN cookie or transaction ID mismatch')
    if message_type not in (0x0101, 0x0111):
        raise ValueError('Not a STUN Binding response')
    if length % 4 or len(packet) != 20 + length:
        raise ValueError('STUN message length does not match the datagram')

    mapped = {}
    error_code = None
    offset = 20
    while offset < len(packet):
        if len(packet) - offset < 4:
            raise ValueError('Truncated STUN attribute header')
        attr_type, size = struct.unpack('!HH', packet[offset:offset + 4])
        value_start = offset + 4
        next_offset = value_start + ((size + 3) & ~3)
        if next_offset > len(packet):
            raise ValueError('STUN attribute value or padding exceeds the message')
        value = packet[value_start:value_start + size]
        if attr_type in (MAPPED, XOR_MAPPED):
            result = mapped_ipv4(value, xor=attr_type == XOR_MAPPED)
            if result is not None and attr_type not in mapped:
                mapped[attr_type] = result
        elif attr_type == 0x0009:  # ERROR-CODE; do not print server-supplied text.
            if size < 4 or not 3 <= (value[2] & 7) <= 6 or value[3] > 99:
                raise ValueError('Malformed STUN error attribute')
            if error_code is None:
                error_code = (value[2] & 7) * 100 + value[3]
        elif attr_type == FINGERPRINT:
            if size != 4 or next_offset != len(packet):
                raise ValueError('Invalid STUN FINGERPRINT position or length')
            actual = zlib.crc32(packet[:offset]) ^ 0x5354554E
            if struct.unpack('!I', value)[0] != actual:
                raise ValueError('STUN FINGERPRINT mismatch')
        elif attr_type < 0x8000:
            # No credentials or negotiated extensions are sent by this probe.
            raise ValueError(f'Unsupported required STUN attribute: 0x{attr_type:04x}')
        offset = next_offset

    if message_type == 0x0111:
        raise ValueError(f'STUN server returned error {error_code or "without a code"}')
    if error_code is not None:
        raise ValueError('STUN success response unexpectedly contains an error')
    result = mapped.get(XOR_MAPPED) or mapped.get(MAPPED)
    if result is None:
        raise ValueError('STUN response contains no usable IPv4 mapped address')
    return result


def resolve_ipv4(host, port, timeout):
    """Bound DNS waiting too; a daemon resolver thread cannot hold up exit."""
    result = queue.Queue(maxsize=1)

    def resolve():
        try:
            addresses = socket.getaddrinfo(host, port, socket.AF_INET,
                                           socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            result.put((True, addresses[0][4]))
        except (OSError, IndexError) as exc:
            result.put((False, exc))

    threading.Thread(target=resolve, daemon=True).start()
    try:
        ok, value = result.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError('DNS lookup exceeded the probe deadline') from None
    if not ok:
        raise OSError(f'IPv4 DNS lookup failed: {value}')
    return value


def probe(host, port, timeout):
    deadline = time.monotonic() + timeout
    endpoint = resolve_ipv4(host, port, timeout)
    transaction_id = secrets.token_bytes(12)
    request = struct.pack('!HHI12s', 0x0001, 0, COOKIE, transaction_id)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Probe deadline reached during DNS lookup')
        client.settimeout(remaining)
        # A connected UDP socket accepts replies only from the selected endpoint.
        client.connect(endpoint)
        client.send(request)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Probe deadline reached before a reply')
        client.settimeout(remaining)
        return parse_response(client.recv(65535), transaction_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--server', default='stun.l.google.com', help='STUN hostname or IPv4 address')
    parser.add_argument('--port', type=int, default=19302, help='STUN UDP port (default: 19302)')
    parser.add_argument('--timeout', type=float, default=8, help='Total DNS/UDP timeout, 1–30 seconds (default: 8)')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    if not math.isfinite(args.timeout) or not 1 <= args.timeout <= 30:
        parser.error('--timeout must be between 1 and 30 seconds')
    try:
        address, port = probe(args.server, args.port, args.timeout)
    except (OSError, ValueError) as exc:
        print(f'UDP STUN 检查未成功：{exc}', file=sys.stderr)
        print('这仅表示所选 STUN 的本次检查失败，不能单凭此结果断定所有 UDP 不可用。', file=sys.stderr)
        return 1
    print('UDP STUN：成功（收到所选服务器的匹配响应）')
    print(f'UDP 出口 IPv4（STUN 服务端观察）：{address}')
    print(f'UDP 映射端口：{port}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
