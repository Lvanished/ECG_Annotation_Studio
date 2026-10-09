"""Fetch original public PhysioNet WFDB record files; check license before redistribution."""
import argparse,hashlib,json,urllib.request
from pathlib import Path
FILES={'mitdb_100':['https://physionet.org/files/mitdb/1.0.0/100.hea','https://physionet.org/files/mitdb/1.0.0/100.dat','https://physionet.org/files/mitdb/1.0.0/100.atr']}
p=argparse.ArgumentParser();p.add_argument('--out',default='data/samples');args=p.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
manifest=[]
for dataset,urls in FILES.items():
 for url in urls:
  target=out/Path(url).name
  print('Downloading',url)
  try:
   urllib.request.urlretrieve(url,target)
   manifest.append({'dataset':dataset,'url':url,'file':target.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
  except Exception as e:print('FAILED',url,str(e));target.unlink(missing_ok=True)
(out/'download_manifest.json').write_text(json.dumps(manifest,indent=2))
print('Files downloaded:',len(manifest),'/',sum(map(len,FILES.values())))
