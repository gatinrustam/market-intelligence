"""Offline CPU inference. Both local models are loaded at most once per worker."""
import hashlib,importlib.metadata,json,resource,tempfile,time,copy,threading,gc,platform
from app.logging import log
from pathlib import Path
import numpy as np
import psutil
from app.domain import chunk_document,digest

def validate_embedding_health(vectors):
    vectors=np.asarray(vectors,dtype=np.float32)
    if vectors.ndim!=2 or not np.isfinite(vectors).all():raise ValueError('Invalid embedding matrix')
    if not np.allclose(np.linalg.norm(vectors,axis=1),1,atol=0.01):raise ValueError('Non-normalized embeddings')
    similarities=vectors@vectors.T
    np.fill_diagonal(similarities,-1)
    if np.max(similarities)>0.99:raise ValueError('Collapsed embeddings on distinct control texts')

class LocalModels:
    def __init__(self,settings,configuration):
        self.settings=settings;self.c=configuration;self.encoder=None;self.gliner=None
        self.attempted=False;self.warnings=[];self.ontology_vectors=None;self.ontology_ids=[]
        self.lock=threading.Lock();self.negative_ids=[];self.negative_vectors=None;self.baseline_indices=[]
        self.runtime_versions={name:importlib.metadata.version(name) for name in ('torch','transformers','sentence-transformers','gliner','numpy')}

        self.runtime_versions['architecture']=platform.machine()

    def verify_artifacts(self,prefixes):
        for name,expected in self.c['artifacts'].items():
            if name.split('/')[0] not in prefixes and name not in prefixes:continue
            path=self.settings.models_dir/name;h=hashlib.sha256()
            with path.open('rb') as f:
                while block:=f.read(1024*1024):h.update(block)
            if path.stat().st_size!=expected['bytes'] or h.hexdigest()!=expected['sha256']:raise ValueError('Model artifact hash mismatch: '+name)

    def load(self):
        if self.attempted:return
        self.attempted=True
        import torch
        torch.set_num_threads(self.c['torch_threads']);torch.set_num_interop_threads(1)
        dtype=torch.float16 if self.c.get('load_dtype',self.c['dtype'])=='float16' else torch.float32
        gliner_dtype=torch.float32 if self.c.get('gliner_dtype')=='float32' else dtype
        try:
            self.verify_artifacts({'gliner','gliner_backbone'})
            from gliner import GLiNER
            # Patch only a temporary local config so offline backbone/tokenizer resolution
            # cannot contact Hub. Original upstream config/weights remain hash-verified.
            directory=Path(tempfile.mkdtemp(prefix='gliner-offline-'))
            source=self.settings.models_dir/'gliner'
            config=json.loads((source/'gliner_config.json').read_text())
            backbone=directory/'backbone';backbone.mkdir()
            for source_file in (self.settings.models_dir/'gliner_backbone').iterdir():
                if source_file.name=='config.json':
                    backbone_config=json.loads(source_file.read_text());backbone_config['torch_dtype']='float16' if gliner_dtype==torch.float16 else 'float32'
                    (backbone/'config.json').write_text(json.dumps(backbone_config))
                else:(backbone/source_file.name).symlink_to(source_file)
            config['model_name']=str(backbone)
            (directory/'gliner_config.json').write_text(json.dumps(config))
            (directory/'model.safetensors').symlink_to(source/'model.safetensors')
            previous_dtype=torch.get_default_dtype()
            try:
                torch.set_default_dtype(gliner_dtype)
                self.gliner=GLiNER.from_config(config,load_tokenizer=True,backbone_from_pretrained=False,map_location='cpu')
                # Copy one safetensors slice at a time. Full state-dict loading doubles
                # multilingual embedding memory and can OOM small CPU installations.
                from safetensors import safe_open
                destinations=self.gliner.model.state_dict()
                with safe_open(str(source/'model.safetensors'),framework='pt',device='cpu') as weights:
                    if set(weights.keys()) != set(destinations):raise ValueError('GLiNER state keys mismatch')
                    with torch.no_grad():
                        for name,target in destinations.items():
                            value=weights.get_slice(name)
                            if list(target.shape)!=value.get_shape():raise ValueError('GLiNER state shape mismatch: '+name)
                            if target.ndim:
                                for first in range(0,target.shape[0],512):target[first:first+512].copy_(value[first:first+512])
                            else:target.copy_(weights.get_tensor(name))
            finally:
                torch.set_default_dtype(previous_dtype)
            self.gliner.to(dtype=gliner_dtype);self.gliner.eval()
            del destinations,value
            gc.collect()
            log("semantic_gliner_loaded")
        except Exception as exc:
            self.gliner=None;self.warnings.append('gliner_unavailable:'+type(exc).__name__+':'+str(exc)[:160])

        try:
            artifact=self.c.get('encoder_artifact')
            self.verify_artifacts({artifact} if artifact else {'bge'})
            from sentence_transformers import SentenceTransformer
            if artifact:
                # This checkpoint is generated locally from verified upstream weights,
                # never downloaded. Verify its exact pinned SHA before unpickling.
                torch.backends.quantized.engine=self.c['quantization_engine']
                checkpoint=torch.load(self.settings.models_dir/artifact,map_location='cpu',weights_only=False,mmap=True)
                if checkpoint.get('format')!='bge_m3_int8_per_channel_v1':raise ValueError('Unknown local CPU checkpoint format')
                self.encoder=SentenceTransformer(modules=checkpoint['modules'],device='cpu')
                from app.cpu import restore_compute_dtypes
                restore_compute_dtypes(self.encoder)
                del checkpoint
            else:
                self.encoder=SentenceTransformer(str(self.settings.models_dir/'bge'),device='cpu',local_files_only=True,
                    model_kwargs={'torch_dtype':dtype,'low_cpu_mem_usage':True,'attn_implementation':'eager','use_safetensors':True})
                if self.c.get('cpu_transform')=='int8_linear_fp16_embedding_v1':
                    from app.cpu import optimize_cpu
                    optimize_cpu(self.encoder,self.c['quantization_engine'])
            if self.c.get('embedding_healthcheck')=='distinct_en_ru_v1':
                controls=['The Federal Reserve held interest rates unchanged.',
                    'A cryptocurrency exchange suspended withdrawals after a hack.',
                    'A director resigned and a successor was appointed.',
                    'Центральный банк повысил ключевую ставку.']
                validate_embedding_health(self.encoder.encode(controls,batch_size=2,normalize_embeddings=True,show_progress_bar=False,convert_to_numpy=True))
            log("semantic_bge_loaded")
            descriptions=[]
            baseline_ids={x['id'] for x in self.c.get('baseline_configuration',self.c)['ontology']['concepts']}
            for concept in self.c['ontology']['concepts']:
                for lang in ('en','ru'):
                    for description in concept['descriptions'][lang]:
                        if concept['id'] in baseline_ids:self.baseline_indices.append(len(descriptions))
                        descriptions.append(description);self.ontology_ids.append(concept['id'])
                if self.c.get('reranking'):
                    for examples in concept.get('positive_examples',{}).values():
                        for text in examples:descriptions.append(text);self.ontology_ids.append(concept['id'])
            negative=[]
            if self.c.get('reranking'):
                for concept in self.c['ontology']['concepts']:
                    for examples in concept.get('negative_examples',{}).values():
                        for text in examples:negative.append(text);self.negative_ids.append(concept['id'])
            encoded=self.encoder.encode(descriptions+negative,batch_size=self.c['batch_size'],normalize_embeddings=True,show_progress_bar=False,convert_to_numpy=True).astype(np.float32)
            if not np.isfinite(encoded).all():raise ValueError("Non-finite ontology embeddings")
            self.ontology_vectors=encoded[:len(descriptions)];self.negative_vectors=encoded[len(descriptions):]
            log("semantic_ontology_encoded")
        except Exception as exc:
            self.encoder=None;self.warnings.append('bge_unavailable:'+type(exc).__name__+':'+str(exc)[:160])

    def count_tokens(self,text):
        if self.encoder is None:return max(1,len(text))
        return len(self.encoder.tokenizer.encode(text,add_special_tokens=True,truncation=False))

    def analyze(self,di,body):
        with self.lock:
            start=time.monotonic()
            try:self.load()
            except Exception as exc:self.warnings.append('model_load_failed:'+type(exc).__name__+':'+str(exc)[:160])
            chunks=chunk_document(di['document']['document_id'],body,di['sentences'],self.c['max_chunk_tokens'],self.count_tokens)
            matches=[];baseline_matches=[];entities=[];vectors=[];warnings=list(self.warnings);embedding_seconds=gliner_seconds=0.0
            embedding_available=self.encoder is not None;gliner_available=self.gliner is not None
            if embedding_available and chunks:
                stamp=time.monotonic()
                try:
                    vectors=self.encoder.encode([c['text'] for c in chunks],batch_size=self.c['batch_size'],normalize_embeddings=True,show_progress_bar=False,convert_to_numpy=True).astype(np.float32)
                    if not np.isfinite(vectors).all():raise ValueError("Non-finite document embeddings")
                    matrix=vectors@self.ontology_vectors.T
                    negatives=vectors@self.negative_vectors.T if self.negative_vectors is not None and len(self.negative_vectors) else None
                    for index,(chunk,scores) in enumerate(zip(chunks,matrix)):
                        concepts={cid:max(float(scores[i]) for i,x in enumerate(self.ontology_ids) if x==cid) for cid in set(self.ontology_ids)}
                        limit=len(concepts) if self.c.get('reranking') else self.c['top_k']
                        for cid,score in sorted(concepts.items(),key=lambda x:(-x[1],x[0]))[:limit]:
                            hit={'concept_id':cid,'similarity':round(max(-1,min(1,score)),6),'chunk_id':chunk['chunk_id']}
                            if self.c.get('reranking'):
                                neg=max((float(negatives[index,j]) for j,x in enumerate(self.negative_ids) if x==cid),default=0.)
                                hit.update(positive_similarity=hit['similarity'],negative_similarity=round(neg,6),semantic_margin=round(score-neg,6))
                            matches.append(hit)
                        if self.c.get('reranking'):
                            legacy={cid:max(float(scores[i]) for i in self.baseline_indices if self.ontology_ids[i]==cid) for cid in {self.ontology_ids[i] for i in self.baseline_indices}}
                            for cid,score in sorted(legacy.items(),key=lambda x:(-x[1],x[0]))[:self.c['top_k']]:
                                baseline_matches.append({'concept_id':cid,'similarity':round(max(-1,min(1,score)),6),'chunk_id':chunk['chunk_id']})
                except Exception as exc:
                    embedding_available=False;warnings.append('bge_inference_failed:'+type(exc).__name__);vectors=[];matches=[]
                embedding_seconds=time.monotonic()-stamp
            if gliner_available:
                stamp=time.monotonic()
                try:
                    for chunk in chunks:
                        for e in self.gliner.predict_entities(chunk['text'],self.c['gliner_labels'],threshold=self.c['gliner_threshold']):
                            start_char=chunk['start_char']+e['start'];end_char=chunk['start_char']+e['end']
                            if body[start_char:end_char]!=e['text']:raise ValueError('GLiNER offsets mismatch')
                            entities.append({'start_char':start_char,'end_char':end_char,'label':e['label'],'score':float(e['score'])})
                except Exception as exc:
                    gliner_available=False;warnings.append('gliner_inference_failed:'+type(exc).__name__);log('gliner_inference_error',error=str(exc)[:400])
                gliner_seconds=time.monotonic()-stamp
            elapsed=time.monotonic()-start
            return {'chunks':chunks,**({'baseline_matches':baseline_matches} if self.c.get('reranking') else {}),'matches':matches,'entities':entities,'embeddings':vectors.tolist() if isinstance(vectors,np.ndarray) else [],
                'warnings':warnings,'embedding_available':embedding_available,'gliner_available':gliner_available,'runtime_versions':self.runtime_versions,
                'performance':{'latency_seconds':elapsed,'embedding_seconds':embedding_seconds,'gliner_seconds':gliner_seconds,
                    'documents_per_second':1/max(elapsed,1e-6),'chunks_per_second':len(chunks)/max(elapsed,1e-6),
                    'rss_bytes':psutil.Process().memory_info().rss,'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,'chunks':len(chunks)}}
