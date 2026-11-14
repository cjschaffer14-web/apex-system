import urllib.request,urllib.parse,json,time,os
class Store:
 def __init__(self):
  self.bucket=os.environ['BUCKET'];self.project=os.environ['EXPECTED_PROJECT'];self.token=None;self.until=0
  actual=self.metadata('project/project-id').decode()
  if actual!=self.project or not self.bucket.startswith(self.project+'-apex-'):raise ValueError('cloud identity mismatch')
 def metadata(self,path):
  req=urllib.request.Request('http://169.254.169.254/computeMetadata/v1/'+path,headers={'Metadata-Flavor':'Google'})
  with urllib.request.urlopen(req,timeout=5) as r:return r.read(100000)
 def put_bytes(self,name,payload,content_type='application/json',generation=0):
  if time.time()>self.until:
   t=json.loads(self.metadata('instance/service-accounts/default/token'));self.token=t['access_token'];self.until=time.time()+min(t['expires_in']-60,2700)
  q={'uploadType':'media','name':name}
  if generation is not None:q['ifGenerationMatch']=generation
  req=urllib.request.Request('https://storage.googleapis.com/upload/storage/v1/b/'+self.bucket+'/o?'+urllib.parse.urlencode(q),data=payload,headers={'Authorization':'Bearer '+self.token,'Content-Type':content_type},method='POST')
  with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)['generation']
 def put(self,name,doc,generation=0):return self.put_bytes(name,json.dumps(doc,separators=(',',':'),allow_nan=False).encode(),generation=generation)
