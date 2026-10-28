"""Low-frequency NVIDIA telemetry for benchmarks, separate from inference processes."""
import json
import shutil
import subprocess
import threading
import time
from collections import defaultdict
from pathlib import Path

from studio.core import atomic_text,read_json_file


class GpuTelemetry:
    def __init__(self,manifest,output,capture_processes=False):
        self.manifest=Path(manifest);self.output=Path(output)
        self.stop_event=threading.Event();self.samples=[];self.errors=[]
        self.capture_processes=capture_processes;self.compute_processes=[]
        self.thread=threading.Thread(target=self.run,daemon=True)

    def start(self): self.thread.start()

    def run(self):
        executable=shutil.which('nvidia-smi')
        if not executable:
            self.errors.append('nvidia-smi not found');return
        while not self.stop_event.is_set():
            try:
                state=read_json_file(self.manifest)
                stage=next((s['id'] for s in state['stages'] if s['status']=='running'),state['status'])
                result=subprocess.run([executable,'--query-gpu=name,driver_version,memory.used,memory.total,utilization.gpu',
                                       '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=5,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode: raise ValueError(result.stderr.strip())
                for line in result.stdout.strip().splitlines():
                    name,driver,used,total,util=(x.strip() for x in line.split(','))
                    self.samples.append({'unix_time':time.time(),'stage':stage,'name':name,'driver':driver,
                                         'memory_used_mib':int(used),'memory_total_mib':int(total),'utilization_percent':int(util)})
                if self.capture_processes:
                    processes=subprocess.run([executable,'--query-compute-apps=pid,process_name,gpu_uuid','--format=csv,noheader'],
                        capture_output=True,text=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
                    if processes.returncode:raise ValueError(processes.stderr.strip())
                    for line in processes.stdout.strip().splitlines():
                        pid,name,gpu=(v.strip() for v in line.split(',',2))
                        self.compute_processes.append({'unix_time':time.time(),'stage':stage,'pid':int(pid),'name':name,'gpu_uuid':gpu})
            except Exception as exc: self.errors.append(str(exc))
            self.stop_event.wait(2)

    def close(self):
        self.stop_event.set();self.thread.join(timeout=7)
        groups=defaultdict(list)
        for sample in self.samples: groups[sample['stage']].append(sample)
        summary={stage:{'samples':len(values),'peak_memory_mib':max(v['memory_used_mib'] for v in values),
                        'peak_utilization_percent':max(v['utilization_percent'] for v in values),
                        'mean_utilization_percent':round(sum(v['utilization_percent'] for v in values)/len(values),1)}
                 for stage,values in groups.items()}
        result={'sampling_interval_seconds':2,'scope':'Whole GPU, including desktop and other processes; confirm backend using engine logs',
                'manifest':str(self.manifest),'summary':summary,'errors':self.errors,'samples':self.samples}
        if self.capture_processes:result['compute_processes']=self.compute_processes
        atomic_text(self.output,json.dumps(result,indent=2))
        return result
