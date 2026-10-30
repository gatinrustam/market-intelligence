def test_cpu_transform_keeps_embedding_compact_and_finite_outputs():
    import torch
    from app.cpu import HalfEmbedding,optimize_cpu
    torch.set_num_threads(2);torch.manual_seed(19)
    model=torch.nn.Sequential(torch.nn.Embedding(5000,8),torch.nn.Linear(8,4),torch.nn.LayerNorm(4)).half().eval()
    original=model.float()(torch.tensor([[1,2,3]])).detach();model.half()
    optimize_cpu(model,'qnnpack')
    assert isinstance(model[0],HalfEmbedding)
    assert model[0].weight.dtype==torch.float16
    assert isinstance(model[1],torch.ao.nn.quantized.dynamic.Linear)
    actual=model(torch.tensor([[1,2,3]])).detach()
    assert actual.dtype==torch.float32 and torch.isfinite(actual).all()
    assert torch.allclose(original,actual,atol=.06,rtol=.06)

def test_checkpoint_restore_preserves_float_compute_after_constructor_cast(tmp_path):
    import torch
    from app.cpu import optimize_cpu,restore_compute_dtypes
    torch.set_num_threads(2)
    model=torch.nn.Sequential(torch.nn.Embedding(5000,8),torch.nn.Linear(8,4),torch.nn.LayerNorm(4)).half().eval()
    optimize_cpu(model,'qnnpack');path=tmp_path/'local.pt';torch.save(model,path)
    restored=torch.load(path,weights_only=False,map_location='cpu',mmap=True)
    restored.half() # SentenceTransformer's dtype harmonization during reconstruction.
    restore_compute_dtypes(restored)
    assert restored[0].weight.dtype==torch.float16
    assert restored[2].weight.dtype==torch.float32
    assert torch.isfinite(restored(torch.tensor([[1,2]]))).all()
