import json
from jsonschema import Draft202012Validator, FormatChecker
class Contract:
    def __init__(self,path):
        schema=json.loads(path.read_text()); Draft202012Validator.check_schema(schema)
        self.validator=Draft202012Validator(schema,format_checker=FormatChecker())
    def validate(self,payload): self.validator.validate(payload)
