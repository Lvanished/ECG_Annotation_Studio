import argparse,hashlib,json
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser();p.add_argument('file');p.add_argument('--sha256');a=p.parse_args();path=Path(a.file)
if a.sha256:
 actual=hashlib.sha256(path.read_bytes()).hexdigest();assert actual==a.sha256,(actual,a.sha256)
with np.load(path,allow_pickle=False) as d:
 x=d['signal'];fs=float(d['fs']);leads=d['leads'].tolist();assert x.ndim==2 and x.shape[1]==len(leads) and fs>0 and np.isfinite(x).all()
 print(json.dumps({'valid':True,'samples':x.shape[0],'leads':leads,'fs':fs,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}))
