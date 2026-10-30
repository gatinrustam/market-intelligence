import json
from jsonschema.exceptions import ValidationError
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker


class Contract:
    def __init__(self, path: Path):
        required_formats = {'uuid', 'date-time', 'date', 'uri'}
        if not required_formats <= FormatChecker.checkers.keys():
            raise RuntimeError('Missing required JSON Schema format validators')
        schema = json.loads(path.read_text())
        Draft202012Validator.check_schema(schema)
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def validate(self, payload: dict):
        self.validator.validate(payload)


class CanonicalContract(Contract):
    def validate(self,payload):
        from datetime import date
        super().validate(payload)
        evidence=payload['evidence']
        documents=evidence['documents']
        def require(condition,reason):
            if not condition:
                raise ValidationError(reason)
        require(len({d['document_id'] for d in documents})==len(documents),'duplicate evidence document')
        require(evidence['document_count']==len(documents),'document_count mismatch')
        sources=len({d['source_id'] for d in documents})
        require(evidence['independent_source_count']==sources,'independent_source_count mismatch')
        require(payload['lifecycle']['status']==('corroborated' if sources>=2 else 'detected'),'lifecycle mismatch')
        require(sum(d['relation']=='primary' for d in documents)==1,'one primary document required')
        if payload['time']['event_time_precision']=='date_range':
            try:
                start,end=map(date.fromisoformat,payload['time']['event_time'].split('/'))
                require(start<=end,'reversed event date range')
            except ValueError:
                raise ValidationError('invalid date range') from None

class ContextContract(Contract):
    def validate(self,payload):
        import copy
        from datetime import timedelta
        from app.domain import status,returns,parse,decimal,iso
        super().validate(payload)
        def require(ok,reason):
            if not ok:raise ValidationError(reason)
        points=payload['points'];anchor=payload['anchor']
        require(payload['status']==status(points),'status counts mismatch')
        try:computed=returns(copy.deepcopy(points))
        except (ArithmeticError,ValueError):raise ValidationError('invalid decimal returns') from None
        require(computed==points,'derived returns mismatch')
        require((anchor['at'] is None)==(anchor['unavailable_reason'] is not None),'anchor availability mismatch')
        if anchor['type']=='source_published_at':require(anchor['precision']=='exact','publication time precision mismatch')
        for p in points:
            require(p['target_at']==(iso(parse(anchor['at'])+timedelta(seconds=p['offset_seconds'])) if anchor['at'] else None),'target offset mismatch')
            if p['available']:
                require(decimal(p['price'])>0,'nonpositive price')
                if p['resolution']=='candle_1m':
                    require(p['price']==p['candle']['close'] and p['price_at']==p['candle']['close_time'],'candle price mismatch')
                else:require(decimal(p['bid'])<=decimal(p['ask']),'crossed book')
            if p['status']=='pending':require(p['reason'] in ('future_target','awaiting_market_data'),'pending reason mismatch')
            if p['status']=='unavailable':require(p['reason'] not in ('future_target','awaiting_market_data',None),'unavailable reason mismatch')
