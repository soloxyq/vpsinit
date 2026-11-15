#!/usr/bin/python3 -I
"""Offline lifecycle regressions: the real controller against a fake kernel.

No root, no network, no process. FakeKernel answers only the exact commands
listed in it and fails the test on any other one; its exit codes, output shapes
and error texts were taken from the real tools in a disposable network
namespace. Sockets and subprocess are replaced, and every path the controller
opens is redirected into a temporary directory.

    python3 -I tests/test_lifecycle.py

To see which of these tests an older controller fails, copy this file into that
package's tests/ directory and add --legacy-queries: the three query forms that
only the controller before 2026-11-15 used are then answered as well.
"""
import contextlib
import errno
import io
import json
import os
import pathlib
import socket
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.dont_write_bytecode = True
LEGACY_QUERIES = '--legacy-queries' in sys.argv
if LEGACY_QUERIES:
    sys.argv.remove('--legacy-queries')

BASE = pathlib.Path(__file__).resolve().parents[1]
CODE = compile((BASE / 'xq-user-proxyctl').read_text(), str(BASE / 'xq-user-proxyctl'), 'exec')
OWNER = SimpleNamespace(name='alice', uid=23456, gid=23457)
UPSTREAM = ('203.0.113.25', 1080)
SERVICE = 'xq-user-proxy.service'
TABLE = 'xq_user_proxy'
RTABLE = '20261'
TUN = 'xq-utun'
ZONE = 20261
DNS_MARK = 0x20000000
OWNER_MARK = 0x10000000
FAMILIES = ('-4', '-6')
TOOLS = {'/usr/sbin/ip': 'ip', '/usr/sbin/nft': 'nft',
         '/usr/sbin/conntrack': 'conntrack', '/usr/bin/systemctl': 'systemctl'}
# The only routes and the only rule the controller may ever write.
TUN_ROUTE = ('default', 'dev', TUN, 'metric', '10')
BLACKHOLE = ('blackhole', 'default', 'metric', '32760')
UNREACHABLE = ('unreachable', 'default', 'metric', '32760')
OWNED_ROUTES = {'-4': (TUN_ROUTE, BLACKHOLE), '-6': (UNREACHABLE,)}
OWN_RULE = ('pref', '18410', 'fwmark', '0x40000000/0x40000000', 'lookup', RTABLE)
OWN_RULE_JSON = {'priority': 18410, 'src': 'all', 'fwmark': '0x40000000',
                 'fwmask': '0x40000000', 'table': RTABLE}
# `ip -N` prints these names as numbers (linux/rtnetlink.h).
NUMBERS = {'type': {'blackhole': '6', 'unreachable': '7', 'local': '2', 'broadcast': '3'},
           'table': {'local': '255', 'main': '254', 'default': '253'},
           'protocol': {'kernel': '2', 'static': '4'},
           'scope': {'host': '254', 'link': '253'}}
HOST_ROUTES = {
    '-4': [{'dst': 'default', 'gateway': '203.0.113.1', 'dev': 'eth0', 'protocol': 'static', 'flags': []},
           {'dst': '203.0.113.0/24', 'dev': 'eth0', 'protocol': 'kernel', 'scope': 'link',
            'prefsrc': '203.0.113.77', 'flags': []},
           {'type': 'local', 'dst': '127.0.0.0/8', 'dev': 'lo', 'table': 'local', 'protocol': 'kernel',
            'scope': 'host', 'prefsrc': '127.0.0.1', 'flags': []},
           {'type': 'broadcast', 'dst': '127.255.255.255', 'dev': 'lo', 'table': 'local',
            'protocol': 'kernel', 'scope': 'link', 'prefsrc': '127.0.0.1', 'flags': []},
           {'type': 'local', 'dst': '203.0.113.77', 'dev': 'eth0', 'table': 'local', 'protocol': 'kernel',
            'scope': 'host', 'prefsrc': '203.0.113.77', 'flags': []}],
    '-6': [{'type': 'local', 'dst': '::1', 'dev': 'lo', 'table': 'local', 'protocol': 'kernel',
            'metric': 0, 'flags': [], 'pref': 'medium'}],
}
DELETE_TABLE = f'delete table inet {TABLE}\n'
METAINFO = {'metainfo': {'version': '1.0.9', 'release_name': 'Old Doc Yak #3', 'json_schema_version': 1}}
JOB_FAILED = (f'Job for {SERVICE} failed because the control process exited with error code.\n'
              f'See "systemctl status {SERVICE}" and "journalctl -xeu {SERVICE}" for details.\n')
# What main() turns into "exit 1"; anything else is a bug in the controller.
REFUSALS = (RuntimeError, OSError, ValueError, KeyError)
LEGACY_PORT = str(1000 + 53)


def numeric(route):
    return {key: NUMBERS.get(key, {}).get(value, value) if isinstance(value, str) else value
            for key, value in route.items()}


def route_of(shape):
    return {'kind': shape[0] if shape[0] in ('blackhole', 'unreachable') else 'unicast', 'dst': 'default',
            'dev': shape[shape.index('dev') + 1] if 'dev' in shape else None,
            'metric': int(shape[shape.index('metric') + 1])}


def changes_host(argv):
    tool, rest = argv[0], argv[1:]
    return (tool == 'ip' and any(word in rest for word in ('replace', 'add', 'del'))
            or tool == 'nft' and ('delete' in rest or rest == ('-f', '-'))
            or tool == 'conntrack' and '-D' in rest
            or tool == 'systemctl' and rest[0] in ('start', 'stop', 'reset-failed'))


def chains(text):
    """Map each chain of a guard text to its stripped, non-empty lines."""
    result, current = {}, None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('chain ') and line.endswith('{'):
            current = result.setdefault(line.split()[1], [])
        elif line == '}':
            current = None
        elif line and current is not None:
            current.append(line)
    return result


class Crash(BaseException):
    """The controller process dies right after a step took effect."""


class Injector:
    """Numbers every step the controller takes and can break exactly one of them.

    A step is a command or a write of the controller's own files. 'fail' makes
    the step fail without effect; 'crash' lets it take effect and then kills
    the controller.
    """

    def __init__(self):
        self.count, self.fired = 0, None
        self._match, self._mode = None, None

    def at(self, offset, mode):
        target = self.count + offset
        self._match, self._mode, self.fired = (lambda index, label: index == target), mode, None

    def when(self, predicate, mode):
        self._match, self._mode, self.fired = (lambda index, label: predicate(label)), mode, None

    def step(self, label):
        index, self.count = self.count, self.count + 1
        if self._match and self.fired is None and self._match(index, label):
            self.fired = label
            return self._mode
        return None


class NoHostAccess:
    """Replaces a host-facing module: any use fails the test instead of escaping."""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attribute):
        raise AssertionError(f'offline test attempted {self._name}.{attribute}')


class Box:
    """A private directory standing in for the root of the file system."""

    def __init__(self, root):
        self.root = str(root)

    def inside(self, path):
        path = os.fspath(path)
        if path == self.root or path.startswith(self.root + '/'):
            return path
        if not path.startswith('/'):
            raise AssertionError('controller used a relative path: ' + path)
        return self.root + path


class BoxPath(type(pathlib.Path())):
    """Path as the controller gets it: its writes and unlinks are injectable steps."""
    step = None

    def write_text(self, data, *args, **kwargs):
        mode = BoxPath.step(('write', self.name))
        if mode == 'fail':
            raise OSError(errno.EIO, 'injected failure', str(self))
        result = super().write_text(data, *args, **kwargs)
        if mode == 'crash':
            raise Crash('after writing ' + self.name)
        return result

    def unlink(self, missing_ok=False):
        mode = BoxPath.step(('unlink', self.name))
        if mode == 'fail':
            raise OSError(errno.EIO, 'injected failure', str(self))
        super().unlink(missing_ok=missing_ok)
        if mode == 'crash':
            raise Crash('after removing ' + self.name)


class BoxOS:
    """os as the controller gets it: the functions it needs, every path inside the box."""
    O_RDWR, O_CREAT, O_NOFOLLOW, O_CLOEXEC, X_OK = os.O_RDWR, os.O_CREAT, os.O_NOFOLLOW, os.O_CLOEXEC, os.X_OK
    close, fdopen, fsync = staticmethod(os.close), staticmethod(os.fdopen), staticmethod(os.fsync)

    def __init__(self, box):
        self._inside = box.inside
        self.path = SimpleNamespace(exists=lambda path: os.path.exists(box.inside(path)),
                                    isfile=lambda path: os.path.isfile(box.inside(path)),
                                    lexists=lambda path: os.path.lexists(box.inside(path)))

    def open(self, path, flags, mode=0o777):
        return os.open(self._inside(path), flags, mode)

    def chmod(self, path, mode):
        return os.chmod(self._inside(path), mode)

    def replace(self, source, target):
        return os.replace(self._inside(source), self._inside(target))

    def unlink(self, path):
        return os.unlink(self._inside(path))

    def access(self, path, mode):
        return os.access(self._inside(path), mode)

    def readlink(self, path):
        return os.readlink(self._inside(path))

    def stat(self, path):
        if path == '/proc/self/ns/net':
            return SimpleNamespace(st_dev=4, st_ino=4026531840)
        return os.stat(self._inside(path))

    def __getattr__(self, attribute):
        raise AssertionError(f'offline test: controller used os.{attribute}')


class FakeSockets:
    """socket as the controller gets it: parsing is real, binding is only recorded."""
    AF_INET, AF_INET6 = socket.AF_INET, socket.AF_INET6
    SOCK_STREAM, SOCK_DGRAM = socket.SOCK_STREAM, socket.SOCK_DGRAM
    inet_aton, inet_pton = staticmethod(socket.inet_aton), staticmethod(socket.inet_pton)
    inet_ntop = staticmethod(socket.inet_ntop)

    def __init__(self):
        self.binds, self.bind_error = [], None

    def socket(self, family, kind):
        return FakeSocket(self, family, kind)

    def __getattr__(self, attribute):
        raise AssertionError(f'offline test attempted socket.{attribute}')


class FakeSocket:
    def __init__(self, owner, family, kind):
        self.owner, self.family, self.kind = owner, family, kind

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def bind(self, address):
        self.owner.binds.append((self.family, self.kind, address))
        if self.owner.bind_error:
            raise self.owner.bind_error


class FakeKernel:
    """The host as the controller sees it through ip, nft, conntrack and systemctl."""

    def __init__(self, box, injector):
        self.box, self.injector = box, injector
        self.calls, self.writes = [], []       # every command; those that change the host
        self.wording = 'real'                  # 'other': error texts only say "failed"
        self.legacy = LEGACY_QUERIES
        self.table, self.handle = None, 0      # text of inet xq_user_proxy; None = absent
        self.foreign_ruleset = ''              # other tables in `nft list ruleset`
        self.rules = {'-4': [], '-6': []}      # policy rules besides the kernel's three
        self.routes = {'-4': [], '-6': []}     # routes in table 20261
        self.fib = {'-4': False, '-6': False}  # the table exists once it has held a route
        self.links = {'lo', 'eth0'}
        self.core = False                      # unit active; the TUN exists exactly as long
        self.flows = []                        # conntrack entries as (mark, zone)
        self.conntrack_error = None            # (exit code, stderr) for every conntrack call
        self.denied = set()                    # 'route' / 'rule': netlink answers EPERM
        self.nscd = False
        self.start_error = False               # ExecStartPre or the core itself fails
        self.before = None                     # called with each command before it is answered
        self.attach = self.marker = None       # the unit's ExecStartPost and ConditionPathExists

    def run(self, args, *, check=True, data=None, timeout=30):
        if args[0] not in TOOLS:
            raise AssertionError('Unexpected program; no process was run: ' + repr(args))
        argv = (TOOLS[args[0]], *args[1:])
        mode = self.injector.step(argv)
        self.calls.append(argv)
        if changes_host(argv):
            self.writes.append(argv)
        if mode == 'fail':
            code, out, err = 1, '', 'injected failure\n'
        else:
            if self.before:
                self.before(argv)
            answer = getattr(self, 'answer_' + argv[0])(argv[1:], data)
            if answer is None:
                raise AssertionError('Unexpected command; no process was run: ' + ' '.join(argv))
            code, out, err = answer
            if mode == 'crash':
                raise Crash('after ' + ' '.join(argv))
        if check and code:
            raise RuntimeError(' '.join(args) + ': ' + err.strip())
        return SimpleNamespace(returncode=code, stdout=out, stderr=err)

    def say(self, text):
        return text if self.wording == 'real' else '操作失败（本地化的消息）\n'

    # ip

    def rule_dump(self, family, as_numbers):
        table = (lambda name: NUMBERS['table'][name]) if as_numbers else (lambda name: name)
        tail = [{'priority': 32767, 'src': 'all', 'table': table('default')}] if family == '-4' else []
        return ([{'priority': 0, 'src': 'all', 'table': table('local')}]
                + [dict(rule) for rule in self.rules[family]]
                + [{'priority': 32766, 'src': 'all', 'table': table('main')}] + tail)

    def route_dump(self, family, as_numbers, own_table_only=False):
        items = []
        for route in self.routes[family]:
            item = {}
            if route['kind'] != 'unicast':
                item['type'] = route['kind']
            item['dst'] = route['dst']
            device = route['dev'] or ('lo' if route['kind'] == 'unreachable' else None)
            if device:
                item['dev'] = device
            if not own_table_only:
                item['table'] = RTABLE
            if route['kind'] == 'unicast':
                item['scope'] = 'link'
            if route['metric'] is not None:
                item['metric'] = route['metric']
            item['flags'] = []
            if family == '-6':
                item['pref'] = 'medium'
            items.append(item)
        if not own_table_only:
            items += HOST_ROUTES[family]
        return [numeric(item) for item in items] if as_numbers else items

    def route_write(self, family, action, shape):
        route = route_of(shape)
        if route['dev'] and route['dev'] not in self.links:
            return 1, '', self.say(f'Cannot find device "{route["dev"]}"\n')
        if 'route' in self.denied:
            return 2, '', self.say('RTNETLINK answers: Operation not permitted\n')
        table = self.routes[family]
        if action == 'replace':
            table[:] = [r for r in table if (r['dst'], r['metric']) != (route['dst'], route['metric'])] + [route]
            self.fib[family] = True
            return 0, '', ''
        if not self.fib[family]:
            return 2, '', self.say('Error: FIB table does not exist.\n')
        if route not in table:
            return 2, '', self.say('RTNETLINK answers: No such process\n')
        table.remove(route)
        return 0, '', ''

    def rule_write(self, family, action):
        if 'rule' in self.denied:
            return 2, '', self.say('RTNETLINK answers: Operation not permitted\n')
        present = OWN_RULE_JSON in self.rules[family]
        if action == 'add':
            if present:
                return 2, '', self.say('RTNETLINK answers: File exists\n')
            self.rules[family].append(dict(OWN_RULE_JSON))
        else:
            if not present:
                return 2, '', self.say('RTNETLINK answers: No such file or directory\n')
            self.rules[family].remove(OWN_RULE_JSON)
        return 0, '', ''

    def answer_ip(self, a, data):
        missing = (1, '', self.say(f'Device "{TUN}" does not exist.\n'))
        if a[:2] == ('-N', '-j') and len(a) > 2 and a[2] in FAMILIES:
            if a[3:] == ('rule', 'show'):
                return 0, json.dumps(self.rule_dump(a[2], True)) + '\n', ''
            if a[3:] == ('route', 'show', 'table', 'all'):
                return 0, json.dumps(self.route_dump(a[2], True)) + '\n', ''
        if a[:1] == ('-j',) and a[1:2] in (('-4',), ('-6',)) and a[2:] == ('route', 'show', 'table', 'all'):
            return 0, json.dumps(self.route_dump(a[1], False)) + '\n', ''
        if a == ('-j', '-4', 'route', 'show', 'table', 'main'):
            return 0, json.dumps(HOST_ROUTES['-4'][:2]) + '\n', ''
        if a == ('-j', '-4', 'route', 'get', UPSTREAM[0]):
            return 0, json.dumps([{'dst': UPSTREAM[0], 'gateway': '203.0.113.1', 'dev': 'eth0',
                                   'prefsrc': '203.0.113.77', 'flags': [], 'uid': 0, 'cache': []}]) + '\n', ''
        if a == ('link', 'show', TUN):
            return (0, f'7: {TUN}: <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> mtu 1280\n', '') if TUN in self.links else missing
        if a == ('-j', '-4', 'address', 'show', 'dev', TUN):
            if TUN not in self.links:
                return missing
            return 0, json.dumps([{'ifname': TUN, 'addr_info': [
                {'family': 'inet', 'local': '172.30.254.1', 'prefixlen': 32}]}]) + '\n', ''
        if (len(a) > 5 and a[0] in FAMILIES and a[1] == 'route' and a[2] in ('replace', 'del')
                and a[-2:] == ('table', RTABLE) and a[3:-2] in OWNED_ROUTES[a[0]]):
            return self.route_write(a[0], a[2], a[3:-2])
        if len(a) == 9 and a[0] in FAMILIES and a[1] == 'rule' and a[2] in ('add', 'del') and a[3:] == OWN_RULE:
            return self.rule_write(a[0], a[2])
        if self.legacy and a[:1] == ('-j',) and a[1:2] in (('-4',), ('-6',)):
            if a[2:] == ('rule', 'show'):
                return 0, json.dumps(self.rule_dump(a[1], False)) + '\n', ''
            if a[2:] == ('route', 'show', 'table', RTABLE):
                if not self.fib[a[1]]:
                    family = 'ipv4' if a[1] == '-4' else 'ipv6'
                    return 2, '[', self.say(f'Error: {family}: FIB table does not exist.\nDump terminated\n')
                return 0, json.dumps(self.route_dump(a[1], False, own_table_only=True)) + '\n', ''
        return None

    # nft

    def load_table(self, text):
        self.table, self.handle = text, self.handle + 1

    def answer_nft(self, a, data):
        absent = (1, '', self.say('Error: No such file or directory\n'
                                  f'list table inet {TABLE}\n                ^^^^^^^^^^^^^\n'))
        if a == ('-j', 'list', 'tables'):
            own = [{'table': {'family': 'inet', 'name': TABLE, 'handle': self.handle}}] if self.table is not None else []
            return 0, json.dumps({'nftables': [METAINFO, *own]}) + '\n', ''
        if a == ('--stateless', 'list', 'table', 'inet', TABLE):
            return (0, self.table, '') if self.table is not None else absent
        if a in (('--check', '-f', '-'), ('-f', '-')):
            text = data or ''
            replacing = text.startswith(DELETE_TABLE)
            body = text[len(DELETE_TABLE):] if replacing else text
            if replacing and self.table is None:
                return 1, '', self.say('/dev/stdin:1:19-31: Error: No such file or directory; '
                                       f'did you mean table ‘{TABLE}’ in family inet?\n')
            if not replacing and self.table is not None:
                raise AssertionError('guard loaded on top of the existing table: its rules would be duplicated')
            if not body.startswith(f'table inet {TABLE} {{') or body.count('{') != body.count('}'):
                return 1, '', self.say('/dev/stdin:1:1-2: Error: syntax error\n')
            if a == ('-f', '-'):
                self.load_table(body)
            return 0, '', ''
        if a == ('delete', 'table', 'inet', TABLE):
            if self.table is None:
                return 1, '', self.say('Error: Could not process rule: No such file or directory\n'
                                       f'delete table inet {TABLE}\n                  ^^^^^^^^^^^^^\n')
            self.table = None
            return 0, '', ''
        if a == ('--stateless', 'list', 'ruleset'):
            return 0, self.foreign_ruleset + (self.table or ''), ''
        if a == ('--stateless', '--json', 'list', 'ruleset'):
            return 0, json.dumps({'nftables': [METAINFO]}) + '\n', ''
        if self.legacy and a == ('list', 'table', 'inet', TABLE):
            return (0, self.table, '') if self.table is not None else absent
        return None

    # conntrack

    def add_flow(self, mark, zone=0):
        self.flows.append((mark, zone))

    def flow_text(self, flow):
        mark, zone = flow
        return ('udp      17 28 src=127.0.0.1 dst=127.0.0.53 sport=42294 dport=53 src=127.0.0.1 '
                f'dst=127.0.0.1 sport=40 dport=42294 mark={mark}' + (f' zone={zone}' if zone else '') + ' use=1\n')

    def answer_conntrack(self, a, data):
        binary = self.box.inside('/usr/sbin/conntrack')
        if not os.path.isfile(binary):
            raise FileNotFoundError(errno.ENOENT, 'No such file or directory', '/usr/sbin/conntrack')
        if not os.access(binary, os.X_OK):
            raise PermissionError(errno.EACCES, 'Permission denied', '/usr/sbin/conntrack')
        if self.conntrack_error:
            return self.conntrack_error[0], '', self.say(self.conntrack_error[1])

        def result(code, flows, verb):
            return code, ''.join(map(self.flow_text, flows)), self.say(
                f'conntrack v1.4.8 (conntrack-tools): {len(flows)} flow entries have been {verb}.\n')
        for bit in (DNS_MARK, OWNER_MARK):
            if a == ('-L', '-f', 'ipv4', '--mark', f'{bit:#x}/{bit:#x}'):
                return result(0, [flow for flow in self.flows if flow[0] & bit], 'shown')
        if a == ('-L', '--zone', str(ZONE)):
            return result(0, [flow for flow in self.flows if flow[1] == ZONE], 'shown')
        if a == ('-D', '-f', 'ipv4', '--mark', f'{DNS_MARK:#x}/{DNS_MARK:#x}'):
            deleted = [flow for flow in self.flows if flow[0] & DNS_MARK]
            self.flows = [flow for flow in self.flows if not flow[0] & DNS_MARK]
            # conntrack-tools exits 1 when nothing matched.
            return result(0 if deleted else 1, deleted, 'deleted')
        return None

    # systemd

    def bring_up(self):
        self.core = True
        self.links.add(TUN)
        for path, value in ((f'/proc/sys/net/ipv4/conf/{TUN}/rp_filter', '0\n'),
                            (f'/proc/sys/net/ipv6/conf/{TUN}/disable_ipv6', '0\n')):
            target = pathlib.Path(self.box.inside(path))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(value)

    def take_down(self):
        self.core = False
        self.links.discard(TUN)
        # The kernel drops the routes of a device that disappears.
        for family in FAMILIES:
            self.routes[family] = [route for route in self.routes[family] if route['dev'] != TUN]
        for path in (f'/proc/sys/net/ipv4/conf/{TUN}/rp_filter', f'/proc/sys/net/ipv6/conf/{TUN}/disable_ipv6'):
            target = pathlib.Path(self.box.inside(path))
            if target.exists():
                target.unlink()
                target.parent.rmdir()

    def answer_systemctl(self, a, data):
        if a == ('is-active', '--quiet', SERVICE):
            return (0 if self.core else 3), '', ''
        if a == ('is-active', SERVICE):
            return (0, 'active\n', '') if self.core else (3, 'inactive\n', '')
        if a == ('is-active', '--quiet', 'nscd.service'):
            return (0 if self.nscd else 4), '', ''
        if a == ('reset-failed', SERVICE):
            return 0, '', ''
        if a == ('start', SERVICE):
            # A failed ConditionPathExists skips the start and still reports success.
            if self.core or not self.marker.exists():
                return 0, '', ''
            if self.start_error:
                return 1, '', self.say(JOB_FAILED)
            self.bring_up()
            try:
                self.attach()               # ExecStartPost=/usr/local/sbin/xq-user-proxyctl attach
            except (Crash, *REFUSALS):
                # systemd stops the unit; attach's own reason goes to the journal.
                self.take_down()
                return 1, '', self.say(JOB_FAILED)
            return 0, '', ''
        if a == ('stop', SERVICE):
            self.take_down()
            return 0, '', ''
        return None


class Offline(unittest.TestCase):
    """A fresh boot of a host with the package installed and never switched on."""

    def setUp(self):
        self.build()

    def build(self):
        temp = tempfile.TemporaryDirectory(prefix='xq-user-tun-lifecycle-')
        self.addCleanup(temp.cleanup)
        self.box = Box(temp.name)
        for directory in ('/run', '/etc/xq-user-proxy', '/usr/sbin', '/proc/sys/kernel/random',
                          '/proc/sys/net/ipv4'):
            os.makedirs(self.box.inside(directory))
        self.write('/proc/sys/kernel/random/boot_id', '6b1f0c9e-0000-4000-8000-000000000001\n')
        self.write('/proc/sys/net/ipv4/ip_unprivileged_port_start', '1024\n')
        self.write('/etc/nsswitch.conf', 'hosts:          files mdns4_minimal [NOTFOUND=return] dns\n')
        self.write('/etc/resolv.conf', 'nameserver 127.0.0.53\noptions edns0 trust-ad\nsearch .\n')
        self.write('/usr/sbin/conntrack', '#!/bin/sh\nexit 99\n', 0o755)   # present; never run
        self.config = json.loads((BASE / 'sing-box.template.json').read_text())
        self.config['outbounds'][0].update(server=UPSTREAM[0], server_port=UPSTREAM[1])
        self.write('/etc/xq-user-proxy/sing-box.json', json.dumps(self.config, indent=2) + '\n', 0o600)
        self.write('/etc/xq-user-proxy/settings.json', json.dumps(dict(
            schema=1, user=OWNER.name, uid=OWNER.uid, gid=OWNER.gid,
            proxy_ip=UPSTREAM[0], proxy_port=UPSTREAM[1])) + '\n', 0o600)
        self.injector = Injector()
        BoxPath.step = self.injector.step
        self.sockets, self.sleeps = FakeSockets(), []
        self.kernel = FakeKernel(self.box, self.injector)
        g = self.g = {'__name__': 'offline_controller', '__file__': str(BASE / 'xq-user-proxyctl')}
        exec(CODE, g)
        for name, value in list(g.items()):
            if isinstance(value, pathlib.PurePath):
                g[name] = BoxPath(self.box.inside(value))
        write = g['atomic']

        def atomic(path, content):
            mode = self.injector.step(('write', pathlib.Path(path).name))
            if mode == 'fail':
                raise OSError(errno.ENOSPC, 'injected failure', str(path))
            write(path, content)
            if mode == 'crash':
                raise Crash('after writing ' + pathlib.Path(path).name)

        def trusted(path, *, directory=False):
            # Ownership cannot be root's here; everything else the real check does is kept.
            mode = pathlib.Path(self.box.inside(path)).stat().st_mode
            if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
                raise RuntimeError(f'管理路径类型异常：{path}')

        def account(name):
            if name != OWNER.name:
                raise KeyError(name)
            return SimpleNamespace(pw_uid=OWNER.uid, pw_gid=OWNER.gid)

        g.update(Path=lambda value: BoxPath(self.box.inside(value)), os=BoxOS(self.box),
                 socket=self.sockets, subprocess=NoHostAccess('subprocess'),
                 time=SimpleNamespace(time=lambda: 1763200000.0, sleep=self.sleeps.append),
                 pwd=SimpleNamespace(getpwnam=account), trusted=trusted,
                 run=self.kernel.run, atomic=atomic)
        self.kernel.attach, self.kernel.marker = g['attach'], g['ENABLED']
        g['load_settings']()

    def write(self, path, text, mode=0o644):
        target = pathlib.Path(self.box.inside(path))
        target.write_text(text)
        target.chmod(mode)

    def call(self, name):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.g[name]()
        return result, output.getvalue()

    def attempt(self, name):
        """Run an operation that may be refused, fail or be killed; return what stopped it."""
        try:
            self.call(name)
        except (Crash, *REFUSALS) as error:
            return error
        return None

    def status(self):
        return self.call('status')

    def state_files(self):
        """The controller's own runtime files; the lock is never state."""
        directory = pathlib.Path(self.box.inside('/run/xq-user-proxy'))
        if not directory.is_dir():
            return {}
        return {item.name: item.read_bytes() for item in directory.iterdir() if item.name != 'lock'}

    def phase(self):
        data = self.state_files().get('state.json')
        return json.loads(data)['phase'] if data else None

    def set_phase(self, phase):
        path = pathlib.Path(self.box.inside('/run/xq-user-proxy/state.json'))
        path.write_text(json.dumps(dict(json.loads(path.read_text()), phase=phase)))

    def host(self):
        kernel = self.kernel
        return (kernel.table, repr(kernel.rules), repr(kernel.routes), kernel.core, sorted(kernel.links),
                sorted(kernel.flows), self.state_files())

    def dns_port(self):
        """The private DNS entry as the installed core configuration states it."""
        return next(item['listen_port'] for item in self.config['inbounds'] if item['tag'] == 'uid-dns')

    def healthy_on(self):
        self.call('on')
        self.call('check')
        # One answered DNS query of the owner, and one of its ordinary connections.
        self.kernel.add_flow(DNS_MARK | OWNER_MARK, ZONE)
        self.kernel.add_flow(OWNER_MARK)

    def dirt(self):
        """What a completed OFF must not leave behind; None when the host is clean."""
        kernel, left = self.kernel, []
        if kernel.table is not None:
            left.append('guard table')
        if kernel.core:
            left.append('running core')
        for family in FAMILIES:
            if kernel.rules[family]:
                left.append(f'policy rule {family}')
            if kernel.routes[family]:
                left.append(f'routes {family}')
        if any(mark & DNS_MARK for mark, _ in kernel.flows):
            left.append('DNS conntrack mappings')
        if 'enabled' in self.state_files():
            left.append('enabled marker')
        if self.phase() not in (None, 'off'):
            left.append('phase ' + self.phase())
        code, text = self.status()
        if code or '开关：OFF' not in text:
            left.append(f'status exit {code}')
        return '; '.join(left) or None

    def assert_clean(self):
        self.assertIsNone(self.dirt())

    def assert_refused_unchanged(self, name, *words):
        """The operation must be refused, saying `words`, before changing anything."""
        before, writes = self.host(), len(self.kernel.writes)
        error = self.attempt(name)
        self.assertIsNotNone(error, f'{name} was not refused')
        self.assertEqual(self.kernel.writes[writes:], [], f'{name} changed the host before stopping with: {error}')
        self.assertEqual(self.host(), before, f'{name} changed its state before stopping with: {error}')
        self.assertIsInstance(error, RuntimeError)
        for word in words:
            self.assertIn(word, str(error))
        return str(error)

    def path_line(self, text, address):
        """The status line that states the path of one default nameserver."""
        lines = [line for line in text.splitlines() if address + ' →' in line]
        self.assertEqual(len(lines), 1, f'status does not state the path of nameserver {address}:\n{text}')
        return lines[0]


class CleanupTests(Offline):
    """A1: cleanup is idempotent and never guesses from error wording."""

    def stop_on_before_any_route(self):
        self.injector.when(lambda step: step == ('nft', '-f', '-'), 'fail')
        self.assertIsInstance(self.attempt('on'), RuntimeError)
        self.assertEqual(self.kernel.fib, {'-4': False, '-6': False})

    def test_off_after_an_on_that_never_created_the_routing_table(self):
        self.stop_on_before_any_route()
        self.assertEqual(self.phase(), 'enabling')
        # A second ON does not paper over the unfinished one; status names the way out.
        self.assert_refused_unchanged('on', 'off')
        code, text = self.status()
        self.assertEqual(code, 1, text)
        self.assertIn('xq_proxyoff', text)
        self.call('off')
        self.assert_clean()
        _, text = self.call('off')
        self.assertIn('已关闭', text)
        self.assertEqual([call for call in self.kernel.calls if call[0] == 'ip' and 'del' in call], [],
                         'nothing of ours existed, so nothing may be deleted')
        self.healthy_on()

    def test_cleanup_is_idempotent_for_missing_partial_and_cleaned_objects(self):
        remove, kernel = self.g['remove_routes'], self.kernel
        remove()
        remove()
        self.assertEqual(kernel.writes, [])
        kernel.routes['-4'].append(route_of(BLACKHOLE))        # ON stopped between its two routes
        kernel.fib['-4'] = True
        kernel.rules['-6'].append(dict(OWN_RULE_JSON))         # and one rule of a later attempt
        remove()
        self.assertEqual((kernel.routes, kernel.rules), ({'-4': [], '-6': []}, {'-4': [], '-6': []}))
        self.assertEqual(kernel.writes, [('ip', '-6', 'rule', 'del', *OWN_RULE),
                                         ('ip', '-4', 'route', 'del', *BLACKHOLE, 'table', RTABLE)])
        del kernel.writes[:]
        remove()                                               # the table now exists and is empty
        self.assertEqual(kernel.writes, [])

    def test_routes_and_rules_of_others_are_never_deleted(self):
        kernel = self.kernel
        foreign = [{'kind': 'unicast', 'dst': '198.51.100.0/24', 'dev': 'eth0', 'metric': None},
                   {'kind': 'blackhole', 'dst': 'default', 'dev': None, 'metric': 5}]
        other_rule = {'priority': 18410, 'src': 'all', 'table': NUMBERS['table']['main']}
        kernel.routes['-4'] = foreign + [route_of(BLACKHOLE)]
        kernel.fib['-4'] = True
        kernel.rules['-4'] = [dict(other_rule)]
        self.g['remove_routes']()
        self.assertEqual(kernel.routes['-4'], foreign)
        self.assertEqual(kernel.rules['-4'], [other_rule])

    def test_a_failed_delete_is_an_error_exactly_while_the_object_remains(self):
        remove, kernel = self.g['remove_routes'], self.kernel
        kernel.routes['-4'].append(route_of(BLACKHOLE))
        kernel.fib['-4'] = True
        kernel.rules['-4'].append(dict(OWN_RULE_JSON))
        kernel.denied = {'rule'}
        with self.assertRaisesRegex(RuntimeError, 'Operation not permitted'):
            remove()
        self.assertEqual(kernel.rules['-4'], [OWN_RULE_JSON])
        kernel.denied = {'route'}
        with self.assertRaisesRegex(RuntimeError, 'Operation not permitted'):
            remove()
        self.assertEqual(kernel.routes['-4'], [route_of(BLACKHOLE)])
        kernel.denied = set()
        # The TUN disappears between the lookup and the delete: the kernel has
        # already removed the route, and ip only says it cannot find the device.
        kernel.bring_up()
        kernel.routes['-4'].append(route_of(TUN_ROUTE))
        kernel.before = lambda argv: argv[:4] == ('ip', '-4', 'route', 'del') and TUN in argv and kernel.take_down()
        remove()
        self.assertEqual((kernel.routes['-4'], kernel.rules['-4']), ([], []))

    def test_cleanup_does_not_depend_on_error_wording(self):
        self.kernel.wording = 'other'
        self.stop_on_before_any_route()
        self.call('off')
        self.assert_clean()
        self.healthy_on()
        self.call('off')
        self.assert_clean()
        self.assertEqual(self.kernel.flows, [(OWNER_MARK, 0)], 'only the DNS mappings are deleted')
        self.call('off')                                       # nothing left: no mapping matches
        self.assert_clean()

    def test_off_proves_the_dns_mappings_are_gone_before_dropping_the_guard(self):
        self.healthy_on()
        deleted = []

        def racing(argv):
            # One mapping is still there when the controller looks again after its delete.
            if argv[:2] == ('conntrack', '-L') and deleted == ['once']:
                self.kernel.add_flow(DNS_MARK | OWNER_MARK, ZONE)
                deleted.append('re-added')
            if argv[:2] == ('conntrack', '-D'):
                deleted.append('once')
        self.kernel.before = racing
        error = self.attempt('off')
        self.assertIsInstance(error, RuntimeError)
        self.assertIn('conntrack', str(error))
        self.assertIsNotNone(self.kernel.table, 'the guard stays while a mapping remains')
        self.assertEqual(self.status()[0], 1)
        self.kernel.before = None
        self.call('off')
        self.assert_clean()

    def test_normal_boot_off_is_a_no_op(self):
        _, text = self.call('off')
        self.assertIn('已关闭', text)
        self.assertEqual(self.kernel.writes, [])
        self.assertEqual(self.state_files(), {})

    def test_off_without_ownership_record_deletes_nothing(self):
        self.kernel.load_table(self.g['firewall']())
        self.kernel.rules['-4'].append(dict(OWN_RULE_JSON))
        self.assert_refused_unchanged('off', '归属记录')


class PrerequisiteTests(Offline):
    """A2: a missing tool is refused before the working state is damaged."""

    def break_conntrack(self, how):
        binary = pathlib.Path(self.box.inside('/usr/sbin/conntrack'))
        if how == 'missing':
            binary.unlink()
        elif how == 'not executable':
            binary.chmod(0o644)
        else:
            self.kernel.conntrack_error = (1, 'conntrack v1.4.8 (conntrack-tools): Operation failed: '
                                              'sorry, you must be root or get CAP_NET_ADMIN capability to do this\n')

    def test_off_without_usable_conntrack_leaves_a_working_on_intact(self):
        for how in ('missing', 'not executable', 'cannot list'):
            with self.subTest(conntrack=how):
                self.build()
                self.healthy_on()
                self.break_conntrack(how)
                self.assert_refused_unchanged('off', 'conntrack', 'apt install conntrack', '保持原状')
                self.assertIn('enabled', self.state_files())
                self.assertEqual(self.phase(), 'on')
                self.assertTrue(self.kernel.core)
                self.assertIn('dnat', self.kernel.table, 'the active guard is still loaded')
                self.write('/usr/sbin/conntrack', '#!/bin/sh\nexit 99\n', 0o755)
                self.kernel.conntrack_error = None
                self.call('check')
                self.call('off')
                self.assert_clean()

    def test_interrupted_off_without_conntrack_is_refused_until_it_is_back(self):
        self.healthy_on()
        self.injector.when(lambda step: step == ('systemctl', 'stop', SERVICE), 'crash')
        self.assertIsInstance(self.attempt('off'), Crash)
        self.break_conntrack('missing')
        self.assert_refused_unchanged('off', 'conntrack', '保持原状')
        self.write('/usr/sbin/conntrack', '#!/bin/sh\nexit 99\n', 0o755)
        self.call('off')
        self.assert_clean()

    def test_fresh_on_without_conntrack_changes_nothing(self):
        for how in ('missing', 'not executable', 'cannot list'):
            with self.subTest(conntrack=how):
                self.build()
                self.break_conntrack(how)
                self.assert_refused_unchanged('on', 'conntrack')
                self.assertEqual(self.state_files(), {})


class StatusTests(Offline):
    """A3 and A5: status tells a clean OFF from residue, and names a flushed guard."""

    def test_normal_boot_is_clean(self):
        code, text = self.status()
        self.assertEqual(code, 0, text)
        self.assertIn('开关：OFF', text)
        with self.assertRaisesRegex(RuntimeError, '未开启'):
            self.call('check')
        self.assertEqual(self.kernel.writes, [])
        self.assertEqual(self.state_files(), {})

    def test_completed_off_is_clean_and_healthy_on_is_zero(self):
        self.healthy_on()
        code, text = self.status()
        self.assertEqual(code, 0, text)
        self.assertIn('开关：ON', text)
        self.call('off')
        code, text = self.status()
        self.assertEqual(code, 0, text)
        self.assertIn('开关：OFF', text)

    def test_off_with_each_kind_of_residue_is_nonzero_and_off_clears_it(self):
        kinds = {
            'unfinished phase': lambda: self.set_phase('disabling'),
            'running core': lambda: self.kernel.bring_up(),
            'guard table': lambda: self.kernel.load_table(self.g['firewall'](False)),
            'IPv4 policy rule': lambda: self.kernel.rules['-4'].append(dict(OWN_RULE_JSON)),
            'IPv6 policy rule': lambda: self.kernel.rules['-6'].append(dict(OWN_RULE_JSON)),
            'IPv4 blackhole route': lambda: self.kernel.routes['-4'].append(route_of(BLACKHOLE)),
            'IPv6 unreachable route': lambda: self.kernel.routes['-6'].append(route_of(UNREACHABLE)),
            'DNS conntrack mapping': lambda: self.kernel.add_flow(DNS_MARK | OWNER_MARK, ZONE),
        }
        for kind, leave in kinds.items():
            with self.subTest(residue=kind):
                self.build()
                self.healthy_on()
                self.call('off')
                self.assert_clean()
                leave()
                before, writes = self.host(), len(self.kernel.writes)
                code, text = self.status()
                self.assertEqual(code, 1, f'{kind} reported as a clean OFF:\n{text}')
                self.assertIn('xq_proxyoff', text)
                self.assertEqual((self.host(), self.kernel.writes[writes:]), (before, []))
                self.call('off')
                self.assert_clean()

    def test_off_interrupted_after_its_first_step_is_not_reported_clean(self):
        # The reviewed case: marker gone, core still running, guard still loaded.
        self.healthy_on()
        self.injector.when(lambda step: step == ('unlink', 'enabled'), 'crash')
        self.assertIsInstance(self.attempt('off'), Crash)
        self.assertNotIn('enabled', self.state_files())
        self.assertTrue(self.kernel.core and self.kernel.table)
        code, text = self.status()
        self.assertEqual(code, 1, text)
        self.assertIn('开关：OFF', text)
        self.assertIn('xq_proxyoff', text)
        self.call('off')
        self.assert_clean()

    def test_residue_without_ownership_record_is_nonzero_and_not_promised_to_off(self):
        self.kernel.load_table(self.g['firewall'](False))
        code, text = self.status()
        self.assertEqual(code, 1, text)
        self.assertIn('归属记录', text)
        self.assert_refused_unchanged('off', '归属记录')

    def test_missing_conntrack_alone_is_no_residue(self):
        pathlib.Path(self.box.inside('/usr/sbin/conntrack')).unlink()
        code, text = self.status()
        self.assertEqual(code, 0, text)
        self.assertIn('conntrack', text)
        self.assertIn('未核验', text)

    def test_flushed_guard_while_on_is_named_plainly_and_on_rebuilds_it(self):
        self.healthy_on()
        self.kernel.table = None                               # nft flush ruleset
        code, text = self.status()
        self.assertEqual(code, 1, text)
        with self.assertRaises(RuntimeError) as caught:
            self.call('check')
        for message in (text, str(caught.exception)):
            for word in ('不存在', '直连', 'xq_proxyon'):
                self.assertIn(word, message)
            self.assertNotIn('Error:', message)
            self.assertNotIn('list table', message)
        # A core restarting by itself must not attach routes to a guard that is gone.
        with self.assertRaisesRegex(RuntimeError, '^guard 不完整'):
            self.call('attach')
        calls = len(self.kernel.calls)
        self.call('on')
        self.assertIn('dnat', self.kernel.table)
        self.assertEqual([call for call in self.kernel.calls[calls:] if call[0] == 'systemctl'
                          and call[1] in ('start', 'stop')], [], 'the running core is kept')
        self.call('check')
        self.assertEqual(self.status()[0], 0)

    def test_flushed_guard_with_stopped_core_does_not_claim_the_guard_is_kept(self):
        self.healthy_on()
        self.kernel.table = None
        self.kernel.take_down()
        code, text = self.status()
        self.assertEqual(code, 1)
        self.assertIn('直连', text)
        self.assertNotIn('guard 和黑洞路由保留', text)

    def test_status_and_check_never_change_the_host(self):
        def observe():
            before, writes = self.host(), len(self.kernel.writes)
            self.status()
            self.attempt('check')
            self.assertEqual((self.host(), self.kernel.writes[writes:]), (before, []))
        observe()
        self.healthy_on()
        observe()
        self.kernel.table = None
        observe()
        self.kernel.take_down()
        observe()


class ResolverTests(Offline):
    """A4: each default nameserver is classified by the path the rules give it."""

    def resolver(self, text):
        self.write('/etc/resolv.conf', text)

    def test_classification_matrix(self):
        four = 'nameserver ::1\nnameserver 2001:db8::1\nnameserver 2606:4700:4700::1111\nnameserver 9.9.9.9\n'
        cases = [
            # resolv.conf, [(address, kind)], warnings, refused
            ('nameserver 127.0.0.53\n', [('127.0.0.53', 'proxied')], 0, False),
            ('nameserver 8.8.8.8\nnameserver 1.1.1.1\n', [('8.8.8.8', 'proxied'), ('1.1.1.1', 'proxied')], 0, False),
            ('nameserver 100.100.100.100\n', [('100.100.100.100', 'proxied')], 0, False),
            ('nameserver 192.168.1.1\n', [('192.168.1.1', 'lan')], 1, False),
            ('nameserver 10.255.255.254\n', [('10.255.255.254', 'lan')], 1, False),
            ('nameserver 172.31.0.2\nnameserver 169.254.169.253\n',
             [('172.31.0.2', 'lan'), ('169.254.169.253', 'lan')], 2, False),
            ('nameserver ::1\n', [('::1', 'blocked')], 0, True),
            ('nameserver 2001:4860:4860::8888\n', [('2001:4860:4860::8888', 'blocked')], 0, True),
            ('nameserver fd00::53\n', [('fd00::53', 'lan')], 1, False),
            ('nameserver fe80::1%eth0\n', [('fe80::1%eth0', 'lan')], 1, False),
            ('nameserver ::1\nnameserver 127.0.0.53\n', [('::1', 'blocked'), ('127.0.0.53', 'proxied')], 1, False),
            ('nameserver 1.1.1.1\nnameserver 2606:4700:4700::1111\n',
             [('1.1.1.1', 'proxied'), ('2606:4700:4700::1111', 'blocked')], 0, False),
            ('options rotate\nnameserver 1.1.1.1\nnameserver 2606:4700:4700::1111\n',
             [('1.1.1.1', 'proxied'), ('2606:4700:4700::1111', 'blocked')], 1, False),
            # glibc asks only the first three: a usable fourth does not help.
            (four, [('::1', 'blocked'), ('2001:db8::1', 'blocked'), ('2606:4700:4700::1111', 'blocked'),
                    ('9.9.9.9', 'unused')], 0, True),
            ('nameserver 9.9.9.9\n' + four, [('9.9.9.9', 'proxied'), ('::1', 'blocked'), ('2001:db8::1', 'blocked'),
                                             ('2606:4700:4700::1111', 'unused'), ('9.9.9.9', 'unused')], 0, False),
            # No usable line at all: glibc falls back to 127.0.0.1.
            ('', [('127.0.0.1', 'proxied')], 0, False),
            ('# nameserver ::1\n; nameserver ::1\nsearch example.test\n', [('127.0.0.1', 'proxied')], 0, False),
            (' nameserver ::1\nnameserver\nnameserver not-an-address\nnameserver 1.2.3.4.5\n',
             [('127.0.0.1', 'proxied')], 0, False),
            (None, [('127.0.0.1', 'proxied')], 0, False),
            # glibc parses IPv4 with inet_aton and ignores the rest of the line.
            ('nameserver 127.1\nnameserver\t9.9.9.9 # trailing text\n',
             [('127.0.0.1', 'proxied'), ('9.9.9.9', 'proxied')], 0, False),
            ('nameserver 0.0.0.0\n', [('0.0.0.0', 'proxied')], 0, False),
            # An IPv4-mapped address is reached with IPv4 packets and meets the IPv4 rules.
            ('nameserver ::ffff:8.8.8.8\nnameserver ::ffff:192.168.1.1\n',
             [('::ffff:8.8.8.8', 'proxied'), ('::ffff:192.168.1.1', 'lan')], 1, False),
            # glibc reads the whole token as IPv4 and what precedes a '%' as IPv6: the CR of a
            # CRLF file makes an entry invalid, except behind a '%', where a bad scope is ignored.
            ('nameserver ::1\r\nnameserver 192.168.1.1\r\n', [('127.0.0.1', 'proxied')], 0, False),
            ('nameserver ::1\r%lo\nnameserver 192.168.1.1%eth0\r\n', [('127.0.0.1', 'proxied')], 0, False),
            ('nameserver ::1%lo\r\n', [('::1%lo\\r', 'blocked')], 0, True),
            ('nameserver ::1%lo\r\nnameserver 192.168.1.1\r\n', [('::1%lo\\r', 'blocked')], 0, True),
            ('nameserver ::1%lo\x0b\nnameserver 2001:db8::1%\x0c\n',
             [('::1%lo\\x0b', 'blocked'), ('2001:db8::1%\\x0c', 'blocked')], 0, True),
            ('nameserver fe80::1%eth0\r\n', [('fe80::1%eth0\\r', 'lan')], 1, False),
            # glibc handles a line as a C string: a NUL ends it, and is no separator.
            ('nameserver ::1\0junk\n', [('::1', 'blocked')], 0, True),
            ('nameserver 192.168.1.1\0junk\n', [('192.168.1.1', 'lan')], 1, False),
            ('nameserver ::1%lo\0junk\nnameserver 9.9.9.9\0\n',
             [('::1%lo', 'blocked'), ('9.9.9.9', 'proxied')], 1, False),
            ('nameserver\0 ::1\noptions\0 rotate\nnameserver 9.9.9.9\nnameserver ::1\n',
             [('9.9.9.9', 'proxied'), ('::1', 'blocked')], 0, False),
            ('nameserver 224.0.0.251\n', [('224.0.0.251', 'lan')], 1, False),
        ]
        for text, expected, warnings, refused in cases:
            with self.subTest(resolver=text):
                if text is None:
                    pathlib.Path(self.box.inside('/etc/resolv.conf')).unlink()
                else:
                    self.resolver(text)
                paths = self.g['resolver_paths']()
                self.assertEqual([(address, kind) for address, kind, _ in paths], expected)
                lines, warned, fault = self.g['resolver_report']()
                self.assertEqual(len(lines), len(expected))
                self.assertEqual(len(warned), warnings, warned)
                self.assertEqual(fault is not None, refused, fault)
                self.assertEqual(self.g['resolver_fault'](), fault)
                for address, kind in expected:
                    if refused and kind == 'blocked':
                        self.assertIn(address, fault)

    def test_classification_uses_the_sets_the_rules_are_generated_from(self):
        rules = self.g['firewall']()
        for network in (*self.g['LAN_V4'], *self.g['LAN_V6']):
            self.assertIn(network, rules)
        self.resolver('nameserver 198.18.0.53\nnameserver fd00::53\n')
        self.assertEqual([kind for _, kind, _ in self.g['resolver_paths']()], ['proxied', 'lan'])
        self.g.update(LAN_V4=(*self.g['LAN_V4'], '198.18.0.0/15'), LAN_V6=('fe80::/10',))
        self.assertEqual([kind for _, kind, _ in self.g['resolver_paths']()], ['lan', 'blocked'])

    def test_fresh_on_refuses_an_unusable_default_resolver_before_any_change(self):
        self.resolver('nameserver ::1\nnameserver 2001:4860:4860::8888\n')
        message = self.assert_refused_unchanged('on', '::1', '2001:4860:4860::8888', '阻断')
        self.assertIn('未改动', message)
        self.assertEqual(self.state_files(), {})
        self.assertEqual(self.sockets.binds, [])

    def test_lan_default_resolver_is_allowed_shown_as_direct_and_warned_about(self):
        self.resolver('nameserver 192.168.1.1\n')
        self.healthy_on()
        code, text = self.status()
        self.assertEqual(code, 0, text)
        line = self.path_line(text, '192.168.1.1')
        self.assertIn('直连', line)
        self.assertIn('不经代理', line)
        self.assertIn('警告', text)
        self.assertNotIn('默认系统 DNS 和公网 DNS 查询经代理解析', text)
        # LAN-direct stays policy: nothing in the rules intercepts it.
        nat = chains(self.kernel.table)['dns_output']
        self.assertEqual(nat[1], 'ip daddr @lan_v4 meta l4proto { tcp, udp } th dport 53 return')

    def test_status_shows_the_path_of_every_default_nameserver(self):
        self.resolver('nameserver 127.0.0.53\nnameserver fd00::53\n'
                      'nameserver 2001:4860:4860::8888\nnameserver 9.9.9.9\n')
        for switch in ('OFF', 'ON'):
            if switch == 'ON':
                self.healthy_on()
            code, text = self.status()
            self.assertEqual(code, 0, text)
            self.assertIn('开关：' + switch, text)
            lines = {address: self.path_line(text, address)
                     for address in ('127.0.0.53', 'fd00::53', '2001:4860:4860::8888', '9.9.9.9')}
            self.assertIn(f'127.0.0.1:{self.dns_port()}', lines['127.0.0.53'])
            self.assertIn('DoH', lines['127.0.0.53'])
            self.assertIn('直连', lines['fd00::53'])
            self.assertIn('阻断', lines['2001:4860:4860::8888'])
            self.assertIn('不会被查询', lines['9.9.9.9'])
            self.assertNotIn('默认系统 DNS 和公网 DNS 查询经代理解析', text)

    def test_resolver_that_becomes_unusable_while_on_is_reported(self):
        self.healthy_on()
        self.resolver('nameserver ::1\n')
        with self.assertRaisesRegex(RuntimeError, '::1'):
            self.call('check')
        code, text = self.status()
        self.assertEqual(code, 1, text)
        self.assertIn('::1', text)
        self.assertTrue(self.kernel.core and self.kernel.table, 'reporting it changes nothing')


class DnsEndpointTests(Offline):
    """Batch B: only the core can own the private DNS entry and answer from it."""

    def test_private_dns_entry_is_one_privileged_port_everywhere(self):
        port = self.dns_port()
        # Below the usual ip_unprivileged_port_start tweaks (80, 53) and bindresvport's 512-1023.
        self.assertTrue(0 < port < 53, f'private DNS entry {port} is not a safely privileged port')
        self.assertEqual(self.g['DNS_PORT'], port)
        self.g['check_config']()
        for active in (True, False):
            text = self.g['firewall'](active)
            self.assertNotIn(LEGACY_PORT, text)
            rules = chains(text)
            self.assertIn(f'meta skuid {OWNER.uid} ip daddr 127.0.0.1 meta l4proto {{ tcp, udp }} '
                          f'th dport {port} ct zone set {ZONE}', rules['dns_zone_output'])
            self.assertIn(f'ip saddr 127.0.0.1 icmp type destination-unreachable @th,240,16 {port} '
                          f'ct zone set {ZONE}', rules['dns_zone_output'])
            self.assertEqual(rules['private_dns_output'][1],
                             f'ip daddr 127.0.0.1 meta l4proto {{ tcp, udp }} th dport {port} jump private_dns_access')
        self.assertIn(f'dnat ip to 127.0.0.1:{port}', chains(self.g['firewall']())['dns_output'][-1])

    def test_only_the_core_identity_may_answer_from_the_private_dns_port(self):
        port = self.dns_port()
        for active in (True, False):
            zone = chains(self.g['firewall'](active))['dns_zone_output']
            identity = (f'ip saddr 127.0.0.1 meta l4proto {{ tcp, udp }} th sport {port} '
                        f'meta skuid != {self.g.get("CORE_UID", 0)} counter drop')
            replies = f'ip saddr 127.0.0.1 meta l4proto {{ tcp, udp }} th sport {port} ct zone set {ZONE}'
            self.assertIn(identity, zone)
            self.assertLess(zone.index(identity), zone.index(replies),
                            'a forged reply must be dropped before it can enter the DNS zone')
            # No verdict for packets without a socket: the kernel's own RST and
            # ICMP errors keep passing, so a stopped core still fails fast.
            self.assertEqual([rule for rule in zone if 'drop' in rule or 'reject' in rule], [identity])
        # The identity is one constant; the unit runs the core as that user.
        self.g['CORE_UID'] = 997
        self.assertIn('meta skuid != 997 counter drop', self.g['firewall']())

    def test_preflight_proves_the_private_dns_port_can_be_bound(self):
        port = self.dns_port()
        self.healthy_on()
        self.assertEqual(self.sockets.binds, [
            (socket.AF_INET, socket.SOCK_STREAM, ('127.0.0.1', port)),
            (socket.AF_INET, socket.SOCK_DGRAM, ('127.0.0.1', port))])
        self.build()
        self.sockets.bind_error = OSError(errno.EADDRINUSE, 'Address already in use')
        self.assert_refused_unchanged('on', f'127.0.0.1:{port}')

    def threshold(self, value):
        path = pathlib.Path(self.box.inside('/proc/sys/net/ipv4/ip_unprivileged_port_start'))
        if value is None:
            path.unlink()
        else:
            path.write_text(f'{value}\n')

    def test_fresh_on_refuses_when_ordinary_users_could_bind_the_dns_port(self):
        port = self.dns_port()
        for value in (0, port - 1, port):
            with self.subTest(ip_unprivileged_port_start=value):
                self.build()
                self.threshold(value)
                message = self.assert_refused_unchanged('on', 'ip_unprivileged_port_start', '普通用户')
                self.assertIn('未改动', message)
                self.assertEqual(self.state_files(), {})
        # A kernel without the sysctl uses the fixed threshold 1024.
        for value in (port + 1, 1024, None):
            with self.subTest(ip_unprivileged_port_start=value):
                self.build()
                self.threshold(value)
                self.assertIsNone(self.g['endpoint_fault']())
                self.healthy_on()

    def test_lowered_port_threshold_while_on_is_a_fault_and_keeps_the_guard(self):
        self.healthy_on()
        self.threshold(0)
        with self.assertRaisesRegex(RuntimeError, '普通用户'):
            self.call('check')
        code, text = self.status()
        self.assertEqual(code, 1, text)
        self.assertIn('ip_unprivileged_port_start', text)
        calls = len(self.kernel.calls)
        error = self.attempt('on')                             # the repair path reports it too
        self.assertIsInstance(error, RuntimeError)
        self.assertIn('普通用户', str(error))
        self.assertIn('dnat', self.kernel.table)
        self.assertTrue(self.kernel.core)
        self.assertNotIn(('systemctl', 'stop', SERVICE), self.kernel.calls[calls:])
        self.threshold(1024)
        self.call('on')
        self.assertEqual(self.status()[0], 0)


class FailureInjectionTests(Offline):
    """Batch A acceptance: whatever step of ON or OFF breaks, repeated OFF ends clean."""

    def survive(self, prepare, operation):
        self.build()
        prepare()
        start = self.injector.count
        self.assertIsNone(self.attempt(operation), 'the undisturbed operation must succeed')
        steps = self.injector.count - start
        self.assertGreater(steps, 10)
        stuck = []
        for offset in range(steps):
            for mode in ('fail', 'crash'):
                self.build()
                prepare()
                self.injector.at(offset, mode)
                self.attempt(operation)
                label = self.injector.fired
                self.assertIsNotNone(label, f'step {offset} of {operation} was never reached')
                problem = self.recover()
                if problem:
                    stuck.append(f'{mode} at step {offset} ({" ".join(label)}): {problem}')
        if stuck:
            self.fail(f'{len(stuck)} of {2 * steps} injected failures in {operation} leave a state '
                      'that repeated OFF does not clean:\n' + '\n'.join(stuck[:12]))
        return steps

    def recover(self):
        """Repeat OFF without further failures; None when it ends clean and ON works again."""
        error = None
        for _ in range(3):
            error = self.attempt('off')
            if error is None:
                break
        if error is not None:
            return f'OFF keeps failing: {error}'
        dirt = self.dirt()
        if dirt:
            return 'OFF returned success but left ' + dirt
        error = self.attempt('on') or self.attempt('check')
        return f'ON after the recovery fails: {error}' if error else None

    def test_failure_at_every_step_of_a_fresh_on(self):
        self.survive(lambda: None, 'on')

    def test_failure_at_every_step_of_an_on_that_repairs_a_stopped_core(self):
        def stopped_core():
            self.healthy_on()
            self.kernel.take_down()
        self.survive(stopped_core, 'on')

    def test_failure_at_every_step_of_an_on_that_rebuilds_a_flushed_ruleset(self):
        def flushed():
            self.healthy_on()
            self.kernel.table = None
            self.kernel.rules['-4'] = []
        self.survive(flushed, 'on')

    def test_failure_at_every_step_of_off(self):
        self.survive(self.healthy_on, 'off')

    def test_failure_at_every_step_of_an_off_that_resumes_an_interrupted_off(self):
        def interrupted():
            self.healthy_on()
            self.injector.when(lambda step: step == ('systemctl', 'stop', SERVICE), 'crash')
            self.assertIsInstance(self.attempt('off'), Crash)
        self.survive(interrupted, 'off')


if __name__ == '__main__':
    unittest.main(verbosity=2)
