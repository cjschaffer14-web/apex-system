"""Persistent episode/evidence store. No gap or decay is a capture label."""
import json, sqlite3, hashlib
class EpisodeStore:
    def __init__(self,path):
        self.db=sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS packets (id TEXT PRIMARY KEY, ts INTEGER NOT NULL, body TEXT NOT NULL)')
    def save(self,packet):
        from ..reporting.episode_packet import validate_packet
        validate_packet(packet)
        with self.db:
            self.db.execute('INSERT INTO packets VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET ts=excluded.ts,body=excluded.body',(packet['episode_id'],packet['timestamp_ns'],json.dumps(packet,allow_nan=False)))
    def packets(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT body FROM packets ORDER BY ts,id')]
    def close(self): self.db.close()
def episode_id(mechanism,venues,birth_ns):
    return hashlib.sha256(json.dumps([mechanism,sorted(venues),birth_ns]).encode()).hexdigest()[:24]
