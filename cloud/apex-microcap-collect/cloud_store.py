import os,json,urllib.request,urllib.parse,urllib.error
MAX_BYTES=1024*1024
def http_json(url, method='GET', data=None, headers=None, timeout=4):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError('response size limit')
        return json.loads(body)

class Store:
    def __init__(self):
        expected = os.environ['EXPECTED_PROJECT']
        headers = {'Metadata-Flavor': 'Google'}
        base = 'http://metadata.google.internal/computeMetadata/v1/'
        req = urllib.request.Request(base + 'project/project-id', headers=headers)
        with urllib.request.urlopen(req, timeout=3) as r: actual = r.read(200).decode()
        if actual != expected: raise ValueError('cloud project identity mismatch')
        token = http_json(base + 'instance/service-accounts/default/token', headers=headers)['access_token']
        self.headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
        self.bucket = os.environ['BUCKET']
        if not self.bucket.startswith(expected + '-apex-public-'): raise ValueError('bucket identity mismatch')
    def put(self, name, document, generation):
        query = urllib.parse.urlencode({'uploadType': 'media', 'name': name, 'ifGenerationMatch': generation})
        url = 'https://storage.googleapis.com/upload/storage/v1/b/' + self.bucket + '/o?' + query
        payload = json.dumps(document, separators=(',', ':'), allow_nan=False).encode()
        if len(payload) > MAX_BYTES: raise ValueError('receipt size limit')
        return http_json(url, 'POST', payload, self.headers)['generation']
    def get(self, name):
        url = 'https://storage.googleapis.com/storage/v1/b/' + self.bucket + '/o/' + urllib.parse.quote(name, safe='') + '?alt=media'
        return http_json(url, headers=self.headers)
