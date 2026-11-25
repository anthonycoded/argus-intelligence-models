"""Bounded transactional append-only metadata journal; no article/token storage."""
import json
from pathlib import Path
import sqlite3
from .global_io import document_hash,encoded,now,parse_json

class Audit:
    def __init__(self,path,max_events=10000):
        self.path=Path(path);self.max_events=max_events
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connection() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS events (n INTEGER PRIMARY KEY, previous TEXT, digest TEXT NOT NULL UNIQUE, payload TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS no_event_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append only'); END;
            CREATE TRIGGER IF NOT EXISTS no_event_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append only'); END;''')
        self.read()

    def connection(self):return sqlite3.connect(self.path,timeout=.5)

    def append(self,payload):
        # Callers supply only explicit metadata, never generic request dictionaries.
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            last=db.execute('SELECT n,digest FROM events ORDER BY n DESC LIMIT 1').fetchone()
            count=last[0] if last else 0
            if count>=self.max_events:raise ValueError('Audit capacity requires operator review')
            document={'schema_version':'aic-inference-audit-v1','at':now(),'previous':last[1] if last else None,'data':payload}
            digest=document_hash(document)
            db.execute('INSERT INTO events VALUES (?,?,?,?)',(count+1,document['previous'],digest,encoded(document).decode()))
            return digest

    def read(self):
        previous=None;output=[]
        with self.connection() as db:
            for expected,(n,parent,digest,payload) in enumerate(db.execute('SELECT n,previous,digest,payload FROM events ORDER BY n'),1):
                doc=parse_json(payload)
                if n!=expected or parent!=previous or doc['previous']!=previous or digest!=document_hash(doc):raise ValueError('Audit chain mismatch')
                output.append(doc);previous=digest
        return output
