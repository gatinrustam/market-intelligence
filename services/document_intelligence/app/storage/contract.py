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
