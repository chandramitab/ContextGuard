from pathlib import Path
from uuid import uuid4
import os
def create_session():
    sid=str(uuid4()); root=Path(os.getenv("SESSION_ROOT","/tmp/contextguard-agentic"))/sid; orig=root/"original"; rel=root/"released"; orig.mkdir(parents=True); rel.mkdir(parents=True); return sid,orig,rel
