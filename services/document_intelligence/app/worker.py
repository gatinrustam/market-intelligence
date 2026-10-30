import asyncio
from jsonschema.exceptions import ValidationError
from app.domain import digest
from app.pipeline import Pipeline
class Worker:
    def __init__(self,repo,pipeline):self.repo,self.pipeline=repo,pipeline
    async def run_once(self):
        claim=await asyncio.to_thread(self.repo.claim)
        if claim is None:return False
        job,doc=claim
        try:
            pipeline=self.pipeline
            if digest(job.configuration)!=digest(pipeline.configuration):
                pipeline=Pipeline(job.configuration);pipeline.backends=self.pipeline.backends
            output=await asyncio.to_thread(pipeline.analyze,doc)
        except Exception as exc:await asyncio.to_thread(self.repo.failure,job,type(exc).__name__)
        else:
            # Storage failure leaves a recoverable lease; no partial facts committed.
            try:await asyncio.to_thread(self.repo.finish,job,output)
            except (ValueError,ValidationError) as exc:await asyncio.to_thread(self.repo.failure,job,type(exc).__name__)
        return True
