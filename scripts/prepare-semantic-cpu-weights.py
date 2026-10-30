"""Derive hash-recorded FP16 BGE safetensors from pinned original weights.
Run before workers, as root in the semantic image with writable /models.
Avoids retaining the full FP32 pickle state alongside GLiNER during startup.
"""
import gc,hashlib,json,os,time
from pathlib import Path
import torch
from safetensors.torch import save_file
root=Path('/cpu-weights/bge');start=time.monotonic();torch.set_num_threads(2)
lock=json.loads(Path('/workspace/config/article_semantic/model-artifacts.lock.json').read_text())
def fingerprint(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  while block:=f.read(1024*1024):h.update(block)
 return {'bytes':path.stat().st_size,'sha256':h.hexdigest()}
existing=root/'model.safetensors'
if existing.exists():
 actual=fingerprint(existing)
 if actual!=lock.get('bge/model.safetensors'):raise ValueError('Existing derived artifact differs from pin; do not overwrite immutable model history')
 print(json.dumps({'bge/model.safetensors':actual,'already_prepared':True}),flush=True);raise SystemExit(0)
if fingerprint(root/'pytorch_model.bin')!=lock['bge/pytorch_model.bin']:raise ValueError('Original BGE checkpoint hash mismatch')
print('Loading mmap source',flush=True)
state=torch.load(root/'pytorch_model.bin',map_location='cpu',weights_only=True,mmap=True)
for key in list(state):
 state[key]=state[key].to(dtype=torch.float16).contiguous()
gc.collect();print('Writing derived safetensors',flush=True)
part=root/'model.safetensors.partial'
save_file(state,str(part),metadata={'format':'pt','source':'BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181','conversion':'torch_float16_v1'})
part.replace(root/'model.safetensors');(root/'model.safetensors').chmod(0o644);del state;gc.collect()
path=root/'model.safetensors';h=hashlib.sha256()
with path.open('rb') as f:
 while block:=f.read(1024*1024):h.update(block)
print(json.dumps({'bge/model.safetensors':{'bytes':path.stat().st_size,'sha256':h.hexdigest()},'conversion_seconds':time.monotonic()-start}),flush=True)
