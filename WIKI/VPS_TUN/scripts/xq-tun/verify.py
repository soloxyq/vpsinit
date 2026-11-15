#!/usr/bin/python3 -I
"""Verify an installed xq-tun without making any host network changes.

The default test temporarily stops only xq-tun.service. It refuses to do so
while other processes already inhabit its namespace, and restores the service
in a finally block. Run as root from the host namespace.
"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time

CTL = "/usr/local/sbin/xq-tunctl"
NS = "xq-tun"
SERVICE = "xq-tun.service"
IP = "/usr/sbin/ip"
NFT = "/usr/sbin/nft"
SYSTEMCTL = "/usr/bin/systemctl"
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}


def run(args, timeout=30):
    result = subprocess.run(args, env=ENV, text=True, capture_output=True,
                            timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): "
                           f"{result.stderr.strip()} {result.stdout.strip()}")
    return result.stdout


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def snapshot():
    result = {}
    for family in ("-4", "-6"):
        for kind, tail in (("route", ["show", "table", "all"]),
                           ("rule", ["show"])):
            values = json.loads(run([IP, "-j", family, kind, *tail]))
            # Order from netlink is not meaningful between separate dumps.
            result[family + kind] = sorted(values, key=canonical)
    resolver = Path("/etc/resolv.conf")
    result["resolver"] = {
        "link": os.readlink(resolver) if resolver.is_symlink() else None,
        "content_sha256": hashlib.sha256(resolver.read_bytes()).hexdigest(),
    }
    rules = json.loads(run([NFT, "--stateless", "--json", "list", "ruleset"]))
    result["nftables"] = [r for r in rules.get("nftables", []) if "metainfo" not in r]
    result["forwarding"] = {
        str(p): p.read_text().strip()
        for p in (Path("/proc/sys/net/ipv4/ip_forward"),
                  Path("/proc/sys/net/ipv6/conf/all/forwarding")) if p.exists()
    }
    return result


# This code runs as the configured ordinary user inside the application netns.
# Keeping the worker alive lets the outage test use an existing isolated process
# instead of a launcher which might restart the service before testing it.
WORKER = r'''
import ipaddress,json,os,socket,struct,subprocess,sys

def exact(s,n):
    buf=b''
    while len(buf)<n:
        part=s.recv(n-len(buf))
        if not part: raise RuntimeError('Unexpected DNS EOF')
        buf+=part
    return buf

def dns(tcp=False):
    tx=os.urandom(2)
    packet=tx+bytes.fromhex('01000001000000000000076578616d706c6503636f6d0000010001')
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as s:
        s.settimeout(3)
        s.connect(('172.30.255.2',53))
        if tcp:
            s.sendall(struct.pack('!H',len(packet))+packet)
            answer=exact(s,struct.unpack('!H',exact(s,2))[0])
        else:
            s.send(packet)
            answer=s.recv(4096)
    if len(answer)<12 or answer[:2]!=tx or not answer[2]&128:
        raise RuntimeError('Invalid DNS response')
    if answer[3]&15 or struct.unpack('!H',answer[6:8])[0]<1:
        raise RuntimeError('DNS returned no successful answer')

def curl(url):
    return subprocess.run(['/usr/bin/curl','--disable','--fail','--silent','--show-error',
        '--proxy','','--noproxy','*','--connect-timeout','3','--max-time','8',url],
        capture_output=True,text=True,timeout=10)

status={}
for line in open('/proc/self/status'):
    key,_,value=line.partition(':')
    if key in ('CapEff','CapPrm','CapInh','CapAmb','NoNewPrivs'): status[key]=value.strip()
print(json.dumps({'uid':os.getuid(),'gid':os.getgid(),'groups':os.getgroups(),
    'netns':os.readlink('/proc/self/ns/net'),'security':status,
    'resolver':open('/etc/resolv.conf').read(),
    'hosts':[' '.join(l.split()) for l in open('/etc/nsswitch.conf') if l.lstrip().startswith('hosts:')]}),flush=True)
for line in sys.stdin:
    op=line.strip()
    if op=='exit': break
    try:
        if op=='check':
            dns(False); dns(True)
            addresses=socket.getaddrinfo('example.com',443,socket.AF_INET,socket.SOCK_STREAM)
            if not addresses: raise RuntimeError('libc DNS returned no addresses')
            result=curl('https://api.ipify.org')
            if result.returncode: result=curl('https://icanhazip.com')
            if result.returncode: raise RuntimeError('HTTPS failed: '+result.stderr.strip())
            public_ip=str(ipaddress.IPv4Address(result.stdout.strip()))
            with socket.socket(socket.AF_INET6,socket.SOCK_STREAM) as s:
                s.settimeout(2)
                try: s.connect(('2606:4700:4700::1111',443))
                except OSError: pass
                else: raise RuntimeError('IPv6 unexpectedly connected')
            print(json.dumps({'ok':True,'dns_udp':True,'dns_tcp':True,
                'libc_dns':True,'ipv6_blocked':True,'public_ip':public_ip}),flush=True)
        elif op=='blocked':
            # Numeric HTTPS target prevents DNS failure alone from satisfying this test.
            result=curl('https://1.1.1.1/')
            if result.returncode not in (7,28):
                raise RuntimeError('Expected unreachable/timed-out TCP; curl code='+str(result.returncode))
            for tcp in (False,True):
                try: dns(tcp)
                except (OSError,RuntimeError): pass
                else: raise RuntimeError('DNS succeeded while core was stopped')
            print(json.dumps({'ok':True,'tcp_blocked':True,'dns_blocked':True}),flush=True)
        else: raise RuntimeError('Unknown worker operation')
    except Exception as exc:
        print(json.dumps({'ok':False,'error':str(exc)}),flush=True)
'''


def response(worker, timeout=40):
    with selectors.DefaultSelector() as sel:
        sel.register(worker.stdout, selectors.EVENT_READ)
        if not sel.select(timeout):
            raise RuntimeError("Isolated test process did not respond in time")
    line = worker.stdout.readline()
    if not line:
        raise RuntimeError("Isolated test process exited before responding")
    value = json.loads(line)
    if value.get("ok") is False:
        raise RuntimeError(value.get("error", "Isolated test failed"))
    return value


def ask(worker, operation):
    worker.stdin.write(operation + "\n")
    worker.stdin.flush()
    return response(worker)


def ready():
    for _ in range(60):
        try:
            run([SYSTEMCTL, "is-active", "--quiet", SERVICE])
            links = json.loads(run([IP, "-j", "-n", NS, "link", "show"]))
            if {x["ifname"] for x in links} == {"lo", "xq-tun0"}:
                return
        except (RuntimeError, json.JSONDecodeError):
            pass
        time.sleep(0.25)
    raise RuntimeError("Core/TUN did not become ready")


def verify():
    if run([IP, "netns", "pids", NS]).strip():
        raise RuntimeError("Namespace contains existing applications; exit them before outage testing")
    backup = Path("/var/lib/xq-tun/latest-backup").read_text().strip()
    before = json.loads((Path(backup) / "host-before.json").read_text())
    settings = json.loads(Path("/etc/xq-tun/settings.json").read_text())
    caller = os.environ.get("SUDO_UID")
    if caller != str(settings["uid"]):
        raise RuntimeError("Run this application test using sudo from the configured owner account")
    ready()
    host_ns = os.readlink("/proc/self/ns/net")
    pid = int(run([SYSTEMCTL, "show", "--property=MainPID", "--value", SERVICE]).strip())
    if os.readlink(f"/proc/{pid}/ns/net") != host_ns:
        raise RuntimeError("Core is not in the host network namespace")
    worker = subprocess.Popen([CTL, "run", "/usr/bin/python3", "-u", "-c", WORKER],
                              env=dict(ENV, SUDO_UID=caller), text=True, stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=None, bufsize=1)
    stopped = False
    try:
        identity = response(worker)
        if (identity["uid"] != settings["uid"] or identity["gid"] != settings["gid"]
                or identity["netns"] == host_ns):
            raise RuntimeError("Application identity/namespace does not match settings")
        security = identity["security"]
        if any(int(security[k], 16) for k in ("CapEff", "CapPrm", "CapInh", "CapAmb")):
            raise RuntimeError("Application retained capabilities")
        if security["NoNewPrivs"] != "1":
            raise RuntimeError("Application missing no_new_privs")
        if set(identity["groups"]) - {settings["gid"]}:
            raise RuntimeError("Application retained supplementary groups")
        expected_resolver = Path("/etc/netns/xq-tun/resolv.conf").read_text()
        if identity["resolver"] != expected_resolver or identity["hosts"] != ["hosts: files dns"]:
            raise RuntimeError("Application DNS files were not isolated correctly")
        online = ask(worker, "check")
        print("PASS: isolated user, capabilities, DNS, IPv6 block, HTTPS: " + canonical(online), flush=True)
        stopped = True  # Also attempt recovery if systemctl stop itself fails.
        run([SYSTEMCTL, "stop", SERVICE])
        offline = ask(worker, "blocked")
        print("PASS: core outage blocks existing application connections: " + canonical(offline), flush=True)
        run([SYSTEMCTL, "start", SERVICE])
        ready()
        stopped = False
        print("PASS: recovery: " + canonical(ask(worker, "check")), flush=True)
    finally:
        try:
            if stopped:
                run([SYSTEMCTL, "start", SERVICE])
                ready()
        finally:
            if worker.poll() is None:
                try:
                    worker.stdin.write("exit\n")
                    worker.stdin.flush()
                    worker.wait(timeout=5)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    worker.terminate()
                    try:
                        worker.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        worker.kill()
                        worker.wait(timeout=5)
    after = snapshot()
    changes = [key for key in before if before[key] != after.get(key)]
    (Path(backup) / "host-after.json").write_text(json.dumps(after, indent=2) + "\n")
    if changes:
        raise RuntimeError("Host baseline differs: " + ", ".join(changes)
                           + "; inspect snapshots (other concurrent changes may also cause this)")
    print("PASS: host routes, rules, DNS, nftables and forwarding unchanged", flush=True)
    print("Verification complete; xq-tun.service is running. Boot enablement is unchanged.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run as root in the host network namespace")
    os.umask(0o077)
    if args.snapshot:
        args.snapshot.write_text(json.dumps(snapshot(), indent=2) + "\n")
        print("Saved host baseline: " + str(args.snapshot))
    else:
        verify()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print("Verification failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
