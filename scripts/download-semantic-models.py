"""Download only pinned public model artifacts; no remote inference or credentials."""
import hashlib,json,os
from pathlib import Path
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'config/article_semantic/models.lock.json').read_text())
destination=root/'.models/article_semantic'
lock_path=root/'config/article_semantic/model-artifacts.lock.json'
expected=json.loads(lock_path.read_text()) if lock_path.exists() else {}
def download(entry):
    key,model,rev,name=entry
    path=destination/key/name;path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        with urlopen('https://huggingface.co/'+model+'/resolve/'+rev+'/'+name,timeout=120) as r, path.with_suffix(path.suffix+'.partial').open('wb') as f:
            while block:=r.read(1024*1024):f.write(block)
        path.with_suffix(path.suffix+'.partial').replace(path)
    h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(1024*1024):h.update(block)
    print(key+'/'+name+' '+str(path.stat().st_size),flush=True)
    artifact={'sha256':h.hexdigest(),'bytes':path.stat().st_size}
    if key+'/'+name in expected and artifact!=expected[key+'/'+name]:raise ValueError('Pinned artifact mismatch: '+key+'/'+name)
    return key+'/'+name,artifact
entries=[(k,m['model'],m['revision'],f) for k,m in manifest.items() for f in m['files']]
with ThreadPoolExecutor(max_workers=3) as pool:hashes=dict(pool.map(download,entries))
(root/'config/article_semantic/model-artifacts.lock.json').write_text(json.dumps({**expected,**hashes},indent=2)+'\n')
