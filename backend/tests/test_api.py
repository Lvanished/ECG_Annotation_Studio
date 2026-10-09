import os,sys,tempfile,io
from pathlib import Path
import numpy as np
from fastapi.testclient import TestClient
os.environ['DATA_DIR']=tempfile.mkdtemp()
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.main import app
c=TestClient(app)
def test_health():assert c.get('/health').json()['status']=='ok'
def test_roundtrip():
 buf=io.BytesIO();fs=250;t=np.arange(2500)/fs;y=np.sin(t*2*np.pi)*.1
 np.savez_compressed(buf,signal=y[:,None].astype('float32'),fs=fs,leads=np.array(['II']))
 r=c.post('/recordings/upload',files={'file':('test.npz',buf.getvalue(),'application/octet-stream')});assert r.status_code==200,r.text;id=r.json()['id']
 assert c.get(f'/recordings/{id}/waveform',params={'lead':'II'}).json()['values']
 payload={'tier':'Fiducial Points','label':'R_peak','lead':'II','start':500}
 a=c.post(f'/recordings/{id}/annotations',json=payload).json();assert a['revision']==1
 a2=c.put('/annotations/'+a['id'],json={**payload,'start':501,'revision':1}).json();assert a2['revision']==2
 assert c.put('/annotations/'+a['id'],json={**payload,'revision':1}).status_code==409
 assert c.get(f'/recordings/{id}/annotations').json()[0]['start']==501
 assert c.get(f'/recordings/{id}/export').json()['annotations'][0]['start']==501
 assert c.get(f'/recordings/{id}/export?format=csv').status_code==200
 assert c.get('/annotations/'+a['id']+'/history').status_code==200
 assert c.post(f'/recordings/{id}/detect-r').status_code==200
 assert c.delete('/annotations/'+a['id']+'?revision=2').status_code==200
 assert c.get(f'/recordings/{id}/annotations').json()==[]
