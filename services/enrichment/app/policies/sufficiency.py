from dataclasses import dataclass

from app.normalization.text import normalize_text


@dataclass(frozen=True)
class Decision:
    required: bool
    reason: str
    sufficient: bool


class EnrichmentPolicy:
    def __init__(self, config):
        self.config = config

    def evaluate(self, event) -> Decision:
        body = normalize_text(event['content']['body'])
        title = normalize_text(event['content']['title'])
        if not body:
            reason = 'rss_body_empty'
        elif ' '.join(body.casefold().split()) == ' '.join(title.casefold().split()):
            reason = 'rss_body_equals_title'
        elif event['url'] and body.endswith(('…', '...')):
            reason = 'rss_body_truncated'
        elif len(body) < self.config.minimum_body_characters:
            reason = 'rss_body_short'
        else:
            reason = 'rss_body_sufficient'
        sufficient = reason == 'rss_body_sufficient'
        if self.config.mode == 'never':
            return Decision(False, 'policy_never', sufficient)
        if self.config.mode == 'always':
            return Decision(True, 'policy_always', sufficient)
        return Decision(not sufficient, reason, sufficient)
