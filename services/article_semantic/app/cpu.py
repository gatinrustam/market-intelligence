"""Pinned CPU transform: INT8 Linear, FP16 embedding storage, FP32 activations.
Embedding lookup is cheap; quantizing its huge vocabulary table would create
unacceptable temporary copies on small machines. No training/calibration corpus.
"""
import ctypes,gc
import torch
from torch.ao.quantization import quantize_dynamic,per_channel_dynamic_qconfig

class HalfEmbedding(torch.nn.Module):
    def __init__(self,embedding):
        super().__init__();self.embedding=embedding
    @property
    def weight(self):return self.embedding.weight
    def forward(self,*args,**kwargs):return self.embedding(*args,**kwargs).float()

def release_unused_memory():
    gc.collect()
    try:ctypes.CDLL('libc.so.6').malloc_trim(0)
    except (OSError,AttributeError):pass

def optimize_cpu(parent,engine='qnnpack'):
    if engine not in torch.backends.quantized.supported_engines:raise ValueError('Unsupported pinned quantization engine')
    torch.backends.quantized.engine=engine
    def convert(module):
        for name,child in list(module.named_children()):
            if isinstance(child,torch.nn.Embedding):
                setattr(module,name,HalfEmbedding(child) if child.num_embeddings>4096 else child.float());continue
            if isinstance(child,torch.nn.Linear):
                child.float();wrapper=torch.nn.Sequential(child)
                quantize_dynamic(wrapper,{torch.nn.Linear:per_channel_dynamic_qconfig},inplace=True)
                setattr(module,name,wrapper[0])
            else:convert(child)
        for param in module.parameters(recurse=False):param.data=param.data.float()
        for name,buffer in module.named_buffers(recurse=False):
            if buffer.is_floating_point():setattr(module,name,buffer.float())
    convert(parent);release_unused_memory()
    return parent

def restore_compute_dtypes(model):
    """SentenceTransformer constructor harmonizes float parameters to its first
    parameter (our compact FP16 vocabulary). Restore FP32 compute explicitly.
    Packed INT8 parameters and large vocabulary storage remain untouched.
    """
    for module in model.modules():
        if isinstance(module,torch.nn.Embedding) and module.num_embeddings>4096:continue
        for param in module.parameters(recurse=False):
            if param.is_floating_point():param.data=param.data.float()
        for name,buffer in module.named_buffers(recurse=False):
            if buffer.is_floating_point():setattr(module,name,buffer.float())
    release_unused_memory()
