"""Authenticated, bounded resource snapshots; never inspect environment variables or credential files."""
import os,platform,shutil,threading,time
from pathlib import Path
import psutil
from .settings import ROOT
_LOCK=threading.Lock();_LAST=None;_CACHE=None;_CACHE_AT=0.0

def _read(path):
    try:return Path(path).read_text().strip()
    except OSError:return None

def _number(path):
    raw=_read(path)
    try:return int(raw) if raw and raw!='max' else None
    except ValueError:return None

def _cpu():
    visible=os.cpu_count() or 1;raw=_read('/sys/fs/cgroup/cpu.max');quota=None
    if raw:
        try:
            limit,period=raw.split()
            if limit!='max':quota=int(limit)/int(period)
        except (ValueError,ZeroDivisionError):pass
    usage=None;raw=_read('/sys/fs/cgroup/cpu.stat') or ''
    for line in raw.splitlines():
        if line.startswith('usage_usec '):
            try:usage=int(line.split()[1])
            except (IndexError,ValueError):pass
    return visible,quota,usage

def snapshot(model,started_at):
    global _LAST,_CACHE,_CACHE_AT
    now=time.monotonic()
    with _LOCK:
        if _CACHE is None or now-_CACHE_AT>=1:
            visible,quota,usage=_cpu();percent=None
            if _LAST and usage is not None and _LAST[1] is not None:
                elapsed=now-_LAST[0]
                if elapsed>0:percent=round(max(0,usage-_LAST[1])/1_000_000/elapsed/(quota or visible)*100,2)
            _LAST=(now,usage)
            host=psutil.virtual_memory();limit=_number('/sys/fs/cgroup/memory.max');current=_number('/sys/fs/cgroup/memory.current')
            if limit is None:limit=host.total;current=host.used
            disk=shutil.disk_usage(ROOT)
            _CACHE={'sampled_at':time.time(),'scope':'VM cgroup where available',
              'cpu':{'visible_cores':visible,'quota_cores':quota,'quota_usage_percent':percent,'first_sample_needs_next_poll':percent is None},
              'memory':{'limit_bytes':limit,'used_bytes':current,'quota_headroom_bytes':max(0,limit-current) if current is not None else None},
              'disk':{'total_bytes':disk.total,'used_bytes':disk.used,'free_bytes':disk.free},
              'system':{'os':platform.system(),'arch':platform.machine(),'kernel':platform.release()},
              'capabilities':{'vm_create':False,'vm_wake':False,'inference_device':'cpu'}}
            _CACHE_AT=now
        result={**_CACHE,'model':{'state':model.get('state'),'rss_bytes':model.get('current_rss_bytes'),'observed_at':model.get('observed_at')},
            'api':{'uptime_seconds':max(0,int(time.time()-started_at)),'lease_remaining_seconds':None}}
        return result
