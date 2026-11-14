"""Existing hysteresis tracker with durable checkpoint and stable IDs."""
import json, sqlite3
from ..observatory.observations import EpisodeTracker,Episode,Lane
from .tracker import episode_id
class PersistentDetector(EpisodeTracker):
    def __init__(self,path,**kwargs):
        super().__init__(**kwargs)
        self.db=sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS detector (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT)')
        row=self.db.execute('SELECT body FROM detector WHERE id=1').fetchone()
        if row:
            state=json.loads(row[0]); self.counter=state['counter']
            def decode(d):
                d['lane']=Lane(d['lane']); d['key']=tuple(d['key']); d['data_quality_flags']=set(d['data_quality_flags'])
                d.pop('persistence_seconds',None); d.pop('half_life_seconds',None)
                return Episode(**d)
            self.active={e.key:e for e in map(decode,state['active'])}; self.closed=list(map(decode,state['closed']))
    def checkpoint(self):
        data={'counter':self.counter,'active':[e.to_dict() for e in self.active.values()],'closed':[e.to_dict() for e in self.closed]}
        with self.db: self.db.execute('INSERT INTO detector VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',(json.dumps(data),))
    def ingest(self,m):
        current=self.active.get(self._key(m)); ep=super().ingest(m)
        if ep is not None and ep is not current: ep.episode_id=episode_id(ep.lane.value,[ep.buy_venue,ep.sell_venue],ep.birth_ns)
        self.checkpoint(); return ep
    def close_stale(self,now_ns):
        rows=super().close_stale(now_ns); self.checkpoint(); return rows
    def close(self): self.checkpoint(); self.db.close()
