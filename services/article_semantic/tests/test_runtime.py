import numpy as np
from app.runtime import LocalModels
from app.domain import chunk_document

def test_models_reused_and_embedding_batches_include_every_chunk(settings,configuration,examples):
    model=LocalModels(settings,configuration);model.attempted=True
    class Tokenizer:
        def encode(self,text,**kwargs):return list(text)
    class Encoder:
        tokenizer=Tokenizer()
        calls=[]
        def encode(self,texts,**kwargs):
            self.calls.append((list(texts),kwargs['batch_size']))
            return np.array([[1.,0.] for text in texts])
    class Gliner:
        def predict_entities(self,text,labels,threshold):return []
    model.encoder=Encoder();model.gliner=Gliner();model.ontology_vectors=np.array([[1.,0.]])
    model.ontology_ids=['interest_rates'];s=examples['Fed'];body=s['document']['content']['body']
    a=model.analyze(s['intelligence'],body);b=model.analyze(s['intelligence'],body)
    assert len(model.encoder.calls)==2 and all(''.join(texts)==body for texts,_ in model.encoder.calls)
    assert all(batch==configuration['batch_size'] for _,batch in model.encoder.calls)
    assert a['embedding_available'] and b['gliner_available']

def test_gliner_runtime_exception_leaves_embeddings(settings,configuration,examples):
    model=LocalModels(settings,configuration);model.attempted=True
    class Tokenizer:
        def encode(self,text,**kwargs):return list(text)
    class Encoder:
        tokenizer=Tokenizer()
        def encode(self,texts,**kwargs):return np.array([[1.,0.] for text in texts])
    class Gliner:
        def predict_entities(self,*args,**kwargs):raise RuntimeError('test failure')
    model.encoder=Encoder();model.gliner=Gliner();model.ontology_vectors=np.array([[1.,0.]])
    model.ontology_ids=['interest_rates'];s=examples['Fed']
    result=model.analyze(s['intelligence'],s['document']['content']['body'])
    assert result['embedding_available'] and not result['gliner_available'] and result['matches']
    assert 'gliner_inference_failed:RuntimeError' in result['warnings']

def test_gliner_artifact_failure_does_not_disable_bge(settings,configuration,monkeypatch):
    import sys,types
    configuration.pop('encoder_artifact',None)
    configuration.pop('embedding_healthcheck',None)
    model=LocalModels(settings,configuration)
    torch=types.SimpleNamespace(float16='float16',float32='float32',set_num_threads=lambda n:None,set_num_interop_threads=lambda n:None)
    monkeypatch.setitem(sys.modules,'torch',torch)
    monkeypatch.setitem(sys.modules,'app.cpu',types.SimpleNamespace(optimize_cpu=lambda *args:None))
    def verify(prefixes):
        if 'gliner' in prefixes:raise ValueError('Corrupt GLiNER artifact')
    monkeypatch.setattr(model,'verify_artifacts',verify)
    class Encoder:
        def __init__(self,*args,**kwargs):pass
        def encode(self,texts,**kwargs):return np.array([[1.,0.] for _ in texts])
    monkeypatch.setitem(sys.modules,'sentence_transformers',types.SimpleNamespace(SentenceTransformer=Encoder))
    model.load()
    assert model.encoder is not None and model.gliner is None
    assert any(w.startswith('gliner_unavailable:ValueError') for w in model.warnings)
    assert model.ontology_vectors.shape[0]==len(model.ontology_ids)

def test_nonfinite_embeddings_are_failure_not_perfect_similarity(settings,configuration,examples):
    model=LocalModels(settings,configuration);model.attempted=True
    class Tokenizer:
        def encode(self,text,**kwargs):return list(text)
    class Encoder:
        tokenizer=Tokenizer()
        def encode(self,texts,**kwargs):return np.array([[float('nan'),0.] for _ in texts])
    model.encoder=Encoder();model.ontology_vectors=np.array([[1.,0.]]);model.ontology_ids=['interest_rates']
    snap=examples['Fed'];result=model.analyze(snap['intelligence'],snap['document']['content']['body'])
    assert not result['embedding_available'] and result['matches']==[]
    assert 'bge_inference_failed:ValueError' in result['warnings']


def test_collapsed_normalized_embeddings_fail_healthcheck():
    import pytest
    from app.runtime import validate_embedding_health
    with pytest.raises(ValueError,match='Collapsed'):
        validate_embedding_health(np.array([[1.,0.],[1.,0.]]))
    validate_embedding_health(np.eye(4))


def test_non_normalized_embeddings_fail_healthcheck():
    import pytest
    from app.runtime import validate_embedding_health
    with pytest.raises(ValueError,match='Non-normalized'):
        validate_embedding_health(np.array([[2.,0.],[0.,2.]]))
