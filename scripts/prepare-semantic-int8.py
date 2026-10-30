"""Build a trusted, hash-pinned local CPU checkpoint before GLiNER is loaded.
No network/training. Run in the pinned image with writable /cpu-weights.
The resulting pickle is generated locally, never downloaded; runtime verifies
its SHA-256 before deserializing it with these exact pinned libraries/classes.
"""
import hashlib,json,time
from pathlib import Path
import torch
from sentence_transformers import SentenceTransformer
from app.cpu import optimize_cpu,release_unused_memory
root=Path('/cpu-weights/bge');start=time.monotonic();torch.set_num_threads(2);torch.set_num_interop_threads(1)
lock=json.loads(Path('/workspace/config/article_semantic/model-artifacts.lock.json').read_text())
def fingerprint(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  while block:=f.read(1024*1024):h.update(block)
 return {'bytes':path.stat().st_size,'sha256':h.hexdigest()}
assert fingerprint(root/'model.safetensors')==lock['bge/model.safetensors']
output=root/'cpu_int8_per_channel.pt'
if output.exists():raise RuntimeError('Do not overwrite a prepared immutable artifact')
model=SentenceTransformer('/models/bge',device='cpu',local_files_only=True,model_kwargs={'torch_dtype':torch.float16,'use_safetensors':True,'attn_implementation':'eager'})
print('BGE loaded',time.monotonic()-start,flush=True)
optimize_cpu(model,'onednn');print('BGE CPU transform complete',time.monotonic()-start,flush=True)
# Materialize primitive caches on EN/RU text; verify finite embeddings before save.
import numpy as np
vectors=model.encode(['The central bank held its policy interest rate.','Центральный банк сохранил ключевую ставку.'],normalize_embeddings=True,batch_size=2)
assert np.isfinite(vectors).all() and vectors.shape==(2,1024)
temporary=root/'cpu_int8_per_channel.partial';torch.save({'format':'bge_m3_int8_per_channel_v1','modules':list(model.children())},temporary);temporary.replace(output);output.chmod(0o644)
del model;release_unused_memory()
print(json.dumps({'bge/cpu_int8_per_channel.pt':fingerprint(output),'seconds':time.monotonic()-start}),flush=True)
