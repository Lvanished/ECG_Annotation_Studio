import os, io, json, csv, uuid, datetime
from pathlib import Path
from typing import Optional
import numpy as np
from scipy.signal import find_peaks, butter, sosfiltfilt
from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, Integer, Float, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker

ROOT=Path(os.getenv('DATA_DIR',Path(__file__).resolve().parents[2]/'data'))
ROOT.mkdir(parents=True,exist_ok=True)
DB=os.getenv('DATABASE_URL',f'sqlite:///{ROOT / "annotations.db"}')
engine=create_engine(DB,connect_args={'check_same_thread':False} if DB.startswith('sqlite') else {},pool_pre_ping=True)
Session=sessionmaker(bind=engine)
Base=declarative_base()
class Recording(Base):
 __tablename__='recordings'
 id=Column(String,primary_key=True); name=Column(String); fs=Column(Float); leads=Column(Text); count=Column(Integer); source=Column(String); path=Column(String)
class Annotation(Base):
 __tablename__='annotations'
 id=Column(String,primary_key=True); recording_id=Column(String,ForeignKey('recordings.id'),index=True); tier=Column(String); label=Column(String); lead=Column(String); start=Column(Integer); end=Column(Integer,nullable=True); attrs=Column(Text,default='{}'); source=Column(String,default='manual'); status=Column(String,default='draft'); revision=Column(Integer,default=1); beat_id=Column(String,nullable=True)
class History(Base):
 __tablename__='annotation_history'
 id=Column(String,primary_key=True); annotation_id=Column(String,index=True); operation=Column(String); snapshot=Column(Text); timestamp=Column(String)
Base.metadata.create_all(engine)
app=FastAPI(title='ECG Annotation Studio',version='0.1.0')
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'])
TIERS=['Rhythm','Beat','P Wave','QRS Complex','ST Segment','T Wave','Fiducial Points','Morphology','Signal Quality']
class AnnIn(BaseModel):
 tier:str; label:str; lead:str; start:int=Field(ge=0); end:Optional[int]=None; attrs:dict=Field(default_factory=dict); source:str='manual'; status:str='draft'; beat_id:Optional[str]=None
class AnnUpdate(AnnIn):
 revision:int=Field(ge=1)
def adict(a):
 return dict(id=a.id,recording_id=a.recording_id,tier=a.tier,label=a.label,lead=a.lead,start=a.start,end=a.end,attrs=json.loads(a.attrs or '{}'),source=a.source,status=a.status,revision=a.revision,beat_id=a.beat_id)
def rd(r):return dict(id=r.id,name=r.name,fs=r.fs,leads=json.loads(r.leads),count=r.count,source=r.source)
def check(a,r):
 if a.lead not in json.loads(r.leads):raise HTTPException(422,'Unknown lead')
 if a.start>=r.count or (a.end is not None and (a.end<=a.start or a.end>r.count)):raise HTTPException(422,'Invalid sample interval')
def history(s,a,operation):s.add(History(id=str(uuid.uuid4()),annotation_id=a.id,operation=operation,snapshot=json.dumps(adict(a)),timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()))
def getrec(s,id):
 r=s.get(Recording,id)
 if not r:raise HTTPException(404,'Recording not found')
 return r
@app.get('/health')
def health():return {'status':'ok'}
@app.get('/tiers')
def tiers():return TIERS
@app.get('/recordings')
def recordings():
 with Session() as s:return [rd(x) for x in s.query(Recording).all()]
@app.post('/recordings/upload')
async def upload(file:UploadFile=File(...)):
 if not file.filename.lower().endswith('.npz'):raise HTTPException(415,'Upload .npz containing signal [samples, leads], fs, leads')
 raw=await file.read()
 if len(raw)>150_000_000:raise HTTPException(413,'File too large')
 try:
  with np.load(io.BytesIO(raw),allow_pickle=False) as d:
   signal=np.asarray(d['signal'],dtype=np.float32);fs=float(d['fs']);leads=[str(v) for v in d['leads']]
 except Exception as e:raise HTTPException(422,f'Invalid NPZ: {e}')
 if signal.ndim!=2 or signal.shape[0]<2 or signal.shape[1]!=len(leads) or not 0<fs<=10000 or not np.isfinite(signal).all():raise HTTPException(422,'Invalid signal, sampling frequency or leads')
 id=str(uuid.uuid4());path=ROOT/'samples';path.mkdir(exist_ok=True)
 np.savez_compressed(path/f'{id}.npz',signal=signal,fs=fs,leads=np.asarray(leads))
 with Session.begin() as s:s.add(Recording(id=id,name=Path(file.filename).stem,fs=fs,leads=json.dumps(leads),count=signal.shape[0],source='user_upload',path=str(path/f'{id}.npz')))
 return {'id':id,'count':signal.shape[0],'leads':leads,'fs':fs}
@app.get('/recordings/{id}/waveform')
def waveform(id:str,start:int=Query(0,ge=0),end:Optional[int]=None,lead:str='II',max_points:int=Query(6000,ge=100,le=100000)):
 with Session() as s:
  r=getrec(s,id);leads=json.loads(r.leads)
  if lead not in leads:raise HTTPException(422,'Unknown lead')
  stop=min(end if end is not None else start+int(r.fs*10),r.count)
  if stop<=start:raise HTTPException(422,'Invalid window')
  with np.load(r.path,allow_pickle=False) as data:values=data['signal'][start:stop,leads.index(lead)]
  step=max(1,int(np.ceil(len(values)/max_points)));indices=np.arange(start,stop,step)
  return {'start':start,'end':stop,'step':step,'fs':r.fs,'lead':lead,'indices':indices.tolist(),'values':values[::step].astype(float).tolist(),'decimated':step>1}
@app.get('/recordings/{id}/annotations')
def list_annotations(id:str):
 with Session() as s:
  getrec(s,id);return [adict(a) for a in s.query(Annotation).filter_by(recording_id=id).order_by(Annotation.start).all()]
@app.post('/recordings/{id}/annotations')
def add_annotation(id:str,body:AnnIn):
 with Session.begin() as s:
  r=getrec(s,id);check(body,r);a=Annotation(id=str(uuid.uuid4()),recording_id=id,**body.model_dump(exclude={'attrs'}),attrs=json.dumps(body.attrs));s.add(a);s.flush();history(s,a,'create');result=adict(a)
 return result
@app.put('/annotations/{id}')
def edit_annotation(id:str,body:AnnUpdate):
 with Session.begin() as s:
  a=s.get(Annotation,id)
  if not a:raise HTTPException(404,'Annotation not found')
  if a.revision!=body.revision:raise HTTPException(409,'Revision conflict; reload')
  check(body,getrec(s,a.recording_id));history(s,a,'before_update')
  for k,v in body.model_dump(exclude={'revision','attrs'}).items():setattr(a,k,v)
  a.attrs=json.dumps(body.attrs);a.revision+=1;s.flush();history(s,a,'update');result=adict(a)
 return result
@app.delete('/annotations/{id}')
def delete_annotation(id:str,revision:int):
 with Session.begin() as s:
  a=s.get(Annotation,id)
  if not a:raise HTTPException(404,'Annotation not found')
  if a.revision!=revision:raise HTTPException(409,'Revision conflict')
  history(s,a,'delete');s.delete(a)
 return {'deleted':id}
@app.get('/annotations/{id}/history')
def get_history(id:str):
 with Session() as s:return [dict(operation=h.operation,timestamp=h.timestamp,snapshot=json.loads(h.snapshot)) for h in s.query(History).filter_by(annotation_id=id).order_by(History.timestamp).all()]
@app.post('/recordings/{id}/detect-r')
def detect_r(id:str,lead:str='II',start:int=0,end:Optional[int]=None):
 with Session() as s:
  r=getrec(s,id);leads=json.loads(r.leads)
  if lead not in leads:raise HTTPException(422,'Unknown lead')
  stop=min(end if end is not None else r.count,r.count)
  if start<0 or stop-start<max(10,int(r.fs)):raise HTTPException(422,'Window too short')
  with np.load(r.path,allow_pickle=False) as d:y=np.asarray(d['signal'][start:stop,leads.index(lead)],dtype=float)
 fs=r.fs;sos=butter(2,[5,min(18,fs*.4)],btype='bandpass',fs=fs,output='sos');filtered=sosfiltfilt(sos,y)
 envelope=np.convolve(filtered**2,np.ones(max(1,int(fs*.08)))/max(1,int(fs*.08)),mode='same')
 peaks,_=find_peaks(envelope,distance=max(1,int(.28*fs)),prominence=max(np.percentile(envelope,75)*.45,1e-9))
 result=[]
 for p in peaks:
  lo=max(0,p-int(.07*fs));hi=min(len(y),p+int(.07*fs)+1);q=lo+int(np.argmax(np.abs(filtered[lo:hi])));result.append({'sample_index':int(start+q),'amplitude_mv':float(y[q])})
 result=list({x['sample_index']:x for x in result}.values())
 return {'lead':lead,'algorithm':'scipy_bandpass_energy_peaks','version':'0.1.0','status':'candidate_unreviewed','parameters':{'bandpass_hz':[5,min(18,fs*.4)],'refractory_seconds':.28},'peaks':result}
@app.get('/recordings/{id}/export')
def export(id:str,format:str='json'):
 with Session() as s:
  r=getrec(s,id);annotations=[adict(a) for a in s.query(Annotation).filter_by(recording_id=id).all()];metadata=rd(r)
 if format=='json':
  content=json.dumps({'recording':metadata,'annotations':annotations,'interval_convention':'[start,end)','ontology_version':'0.1.0'},indent=2)
  return StreamingResponse(iter([content]),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="{id}.json"'})
 if format=='csv':
  buf=io.StringIO();w=csv.DictWriter(buf,fieldnames=['id','tier','label','lead','start','end','source','status','revision']);w.writeheader();[w.writerow({k:a.get(k) for k in w.fieldnames}) for a in annotations]
  return StreamingResponse(iter([buf.getvalue()]),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{id}.csv"'})
 raise HTTPException(422,'Supported formats: json, csv')
