"""Convert local WFDB record to importable NPZ. Keep original annotations separately."""
import argparse,json
from pathlib import Path
import numpy as np
import wfdb
p=argparse.ArgumentParser();p.add_argument('record',help='WFDB record basename, e.g. data/samples/100');p.add_argument('--out');a=p.parse_args()
r=wfdb.rdrecord(a.record);signal=r.p_signal
if signal is None:raise RuntimeError('Physical calibrated signal unavailable')
units=r.units or []
if any(x not in ('mV','uV','µV') for x in units):raise RuntimeError(f'Unrecognized units: {units}')
for i,u in enumerate(units):
 if u in ('uV','µV'):signal[:,i]/=1000
out=Path(a.out or a.record+'.npz');np.savez_compressed(out,signal=signal.astype('float32'),fs=float(r.fs),leads=np.asarray(r.sig_name));print(json.dumps({'file':str(out),'fs':r.fs,'leads':r.sig_name,'samples':len(signal),'source_record':a.record}))
