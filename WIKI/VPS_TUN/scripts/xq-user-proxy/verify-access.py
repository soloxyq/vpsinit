#!/usr/bin/python3 -I
"""Non-disruptive owner/private-entry ACL checks. Does not change any rules."""
import json
import os
import runpy
import socket
import subprocess
from pathlib import Path

ENV={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8'}
PROBE=r'''
import json,os,socket,struct,sys
q=json.loads(sys.argv[1]); result={'uid':os.getuid()}
def exact(s,n):
    b=b''
    while len(b)<n:
        c=s.recv(n-len(b))
        if not c: raise OSError('EOF')
        b+=c
    return b
def dns(tcp):
    tx=os.urandom(2)
    packet=tx+bytes.fromhex('01000001000000000000076578616d706c6503636f6d0000010001')
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as s:
        s.settimeout(2); s.connect((q['host'],q['port']))
        if tcp:
            s.sendall(struct.pack('!H',len(packet))+packet)
            answer=exact(s,struct.unpack('!H',exact(s,2))[0])
        else:
            s.send(packet); answer=s.recv(4096)
    if q['allow']:
        assert answer[:2]==tx and len(answer)>=12 and answer[2]&128 and not(answer[3]&15),'Bad DNS reply'
    return True
if q['kind']=='dns':
    for tcp in (False,True):
        try: answered=dns(tcp)
        except OSError:
            if q['allow']: raise
            answered=False
        assert answered==q['allow'],'Private DNS was accessible to unauthorized UID'
    result['dns']='allowed' if q['allow'] else 'denied'
elif q['kind']=='tcp-deny':
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
        s.settimeout(2)
        try: s.connect((q['host'],q['port']))
        except OSError: result['tcp']='denied'
        else: raise RuntimeError('Unauthorized namespace TCP connected')
print(json.dumps(result),flush=True)
'''


def run(args,env=ENV):
    return subprocess.run(args,env=env,text=True,capture_output=True,check=True,timeout=35).stdout


def command_as(uid,args):
    return ['/usr/bin/setpriv','--reuid',str(uid),'--regid',str(uid),'--clear-groups',
            '--bounding-set=-all','--inh-caps=-all','--ambient-caps=-all','--no-new-privs','--',*args]


def probe(uid,kind,host,port,allow=False,namespace=False):
    args=command_as(uid,['/usr/bin/python3','-I','-c',PROBE,json.dumps(dict(kind=kind,host=host,port=port,allow=allow))])
    if namespace: args=['/usr/sbin/ip','netns','exec','xq-tun',*args]
    return run(args).strip()


def reuse_source_port():
    # New tests only: reuse a known owner's just-closed UDP five-tuple as
    # another UID without deleting its OWNER conntrack entry.
    code=r'''
import os,socket,struct,sys
uid,port=map(int,sys.argv[1:]); os.setgroups([]); os.setgid(uid); os.setuid(uid)
tx=os.urandom(2); packet=tx+bytes.fromhex('01000001000000000000076578616d706c6503636f6d0000010001')
with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
    s.bind(('127.0.0.1',port)); s.settimeout(2); port=s.getsockname()[1]
    try:
        s.connect(('127.0.0.1',1053)); s.send(packet); answer=s.recv(4096)
    except OSError:
        assert uid!=1006,'Owner DNS unexpectedly blocked'
        print('denied')
    else:
        assert uid==1006,'Reused OWNER mapping granted access to another UID'
        assert len(answer)>=12 and answer[:2]==tx and not(answer[3]&15),'Invalid DNS answer'
        print(port)
'''
    port=int(run(['/usr/bin/python3','-I','-c',code,'1006','0']).strip())
    if run(['/usr/bin/python3','-I','-c',code,'65534',str(port)]).strip()!='denied':
        raise RuntimeError('Source-port reuse bypassed the private DNS ACL')
    print('PASS: another UID cannot reuse an owner UDP five-tuple to access private DNS.',flush=True)


def resolver_source_port_reuse(resolver):
    # All users share the host conntrack table. Reuse a just-closed UDP source
    # port across UIDs in both orders: neither UID may inherit the other's DNS
    # translation, and the owner's entry must sit in the dedicated zone.
    code=r'''
import os,socket,sys
uid,host,port=int(sys.argv[1]),sys.argv[2],int(sys.argv[3]); os.setgroups([]); os.setgid(uid); os.setuid(uid)
tx=os.urandom(2); packet=tx+bytes.fromhex('01000001000000000000076578616d706c6503636f6d0000010001')
with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
    s.bind(('',port)); s.settimeout(4); port=s.getsockname()[1]
    s.connect((host,53)); s.send(packet); answer=s.recv(4096)
assert len(answer)>=12 and answer[:2]==tx and answer[2]&128 and not(answer[3]&15),'Invalid DNS answer'
print(port)
'''
    def query(uid,port=0):
        return int(run(['/usr/bin/python3','-I','-c',code,str(uid),resolver,str(port)]).strip())
    owner_port=query(1006)
    zoned=run(['/usr/sbin/conntrack','-L','-p','udp','--sport',str(owner_port),'--zone','20261'])
    if 'zone=20261' not in zoned:
        raise RuntimeError('Owner DNS translation is not in the dedicated conntrack zone')
    query(65534,owner_port)
    query(1006,query(65534))
    print('PASS: a reused UDP source port never carries DNS translation between UIDs (both orders).',flush=True)


def hits(chain,action,namespace=False):
    args=['/usr/sbin/nft','--json','list','chain','inet',
          'xq_tun_guard' if namespace else 'xq_user_proxy',chain]
    if namespace: args=['/usr/sbin/ip','netns','exec','xq-tun',*args]
    data=json.loads(run(args))
    total=0
    for entry in data.get('nftables',[]):
        expressions=entry.get('rule',{}).get('expr',[])
        if any(action in e for e in expressions):
            total+=sum(e['counter']['packets'] for e in expressions if 'counter' in e)
    return total


def main():
    if os.geteuid()!=0: raise SystemExit('Run as an administrator; tests explicitly create the tested UIDs')
    run(['/usr/local/sbin/xq-user-proxyctl','check'])
    run(['/usr/local/sbin/xq-tunctl','check'])
    service_args=['/usr/bin/systemctl','show','xq-user-proxy.service','xq-tun.service','-p','MainPID','-p','ActiveState']
    pids=run(service_args)
    verifier=runpy.run_path('/usr/local/lib/xq-user-proxy/verify.py')
    host,interface,resolver,upstream,port=verifier['discover_network']()
    before=hits('private_dns_access','reject')
    print('Owner private DNS: '+probe(1006,'dns','127.0.0.1',1053,True),flush=True)
    for uid in (0,65534):
        print('Private DNS: '+probe(uid,'dns','127.0.0.1',1053),flush=True)
        print('Original resolver: '+probe(uid,'dns',resolver,53,True),flush=True)
        result=subprocess.run(command_as(uid,['/usr/local/bin/xq_tun','run','/usr/bin/true']),env=ENV,text=True,capture_output=True,timeout=5)
        if result.returncode==0 or '仅允许 xuqian' not in result.stderr:
            raise RuntimeError('Public wrapper did not reject UID '+str(uid))
    if hits('private_dns_access','reject')<before+4:
        raise RuntimeError('Private DNS denial did not hit the dedicated ACL')
    reuse_source_port()
    resolver_source_port_reuse(resolver)
    for caller in (None,'0','65534'):
        env=dict(ENV)
        if caller is not None: env['SUDO_UID']=caller
        result=subprocess.run(['/usr/local/sbin/xq-tunctl','run','/usr/bin/true'],env=env,text=True,capture_output=True,timeout=5)
        if result.returncode==0: raise RuntimeError('Backend accepted an unauthorized caller')
    print('PASS: root/other-user public and backend application entries rejected; management remains available.',flush=True)
    mark=0x40000000
    route=json.loads(run(['/usr/sbin/ip','-j','-4','route','get','1.1.1.1','mark',hex(mark)]))
    if not route or route[0].get('dev')!='xq-utun':
        raise RuntimeError('Marked probe is not guaranteed to enter the dedicated TUN')
    before=hits('private_tun_access','drop')
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
        s.settimeout(2)
        s.setsockopt(socket.SOL_SOCKET,socket.SO_MARK,mark)
        try: s.connect(('1.1.1.1',443))
        except OSError: pass
        else: raise RuntimeError('Root marked socket used the private host TUN')
    if hits('private_tun_access','drop')<=before:
        raise RuntimeError('Root marked socket did not hit the dedicated TUN ACL')
    print('PASS: a deliberately marked root socket is blocked by the host TUN ACL.',flush=True)
    before=hits('output','reject',True)
    for uid in (0,65534):
        print('Namespace unauthorized use: '+probe(uid,'tcp-deny','1.1.1.1',443,namespace=True),flush=True)
    if hits('output','reject',True)<before+2:
        raise RuntimeError('Namespace denials did not hit its guard')
    # The administrator creates an owner process solely to validate its namespace path.
    print('Owner namespace DNS: '+probe(1006,'dns','172.30.255.2',53,True,True),flush=True)
    if pids!=run(service_args): raise RuntimeError('Core PID/state changed during ACL tests')
    print('PASS: both core PIDs unchanged. No services stopped, routes/rules changed, or conntrack entries explicitly removed.',flush=True)


if __name__=='__main__': main()
