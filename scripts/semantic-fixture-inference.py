"""Offline model smoke; run in article-semantic with JSON snapshots on stdin.
No database writes, no external API. Emits one auditable result per line.
"""
import json,sys
from app.logging import configure_logging
configure_logging()
from app.config import Settings
from app.domain import load_configuration,build_result
from app.runtime import LocalModels
settings=Settings();configuration=load_configuration(settings);models=LocalModels(settings,configuration)
for snapshot in json.load(sys.stdin):
 observed=models.analyze(snapshot['intelligence'],snapshot['document']['content']['body'])
 result=build_result(snapshot['intelligence'],snapshot,configuration,observed)
 print(json.dumps({'fixture':snapshot.get('fixture'),'result':result,'observed':observed},ensure_ascii=False),flush=True)
