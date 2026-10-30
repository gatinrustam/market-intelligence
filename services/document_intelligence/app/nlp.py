"""Local NLP adapters. No spaCy objects cross this boundary."""
from dataclasses import dataclass
from typing import Protocol
import spacy,re
from langdetect import DetectorFactory,detect_langs,LangDetectException

@dataclass(frozen=True)
class Token:
    id:int; text:str; lemma:str; pos:str; dep:str; head:int; start:int; end:int; morph:str
@dataclass(frozen=True)
class Sentence:
    id:int; start:int; end:int; text:str; tokens:tuple[Token,...]
@dataclass(frozen=True)
class NamedEntity:
    start:int; end:int; label:str
@dataclass(frozen=True)
class NLPDocument:
    sentences:tuple[Sentence,...]; entities:tuple[NamedEntity,...]
class NLPBackend(Protocol):
    def analyze(self,text:str)->NLPDocument:...
class AuxiliaryExtractor(Protocol):
    name:str
    def extract(self,document:NLPDocument,body:str)->list[dict]:...
class LanguageDetector:
    def __init__(self,profiles):self.profiles=profiles
    def detect(self,text:str)->str:
        if not text.strip():return 'unsupported'
        # langdetect's public detector uses a fixed global seed; workers serialize NLP.
        DetectorFactory.seed=0
        try:
            scores=detect_langs(text);top=scores[0]
            words=set(re.findall(r'[а-яё]+',text.casefold()))
            if not re.search('[іїєґўѓќјљњџ]',text.casefold()) and len(words.intersection(self.profiles['ru_short_text_markers']))>=self.profiles['minimum_markers']:
                return 'ru'
            return top.lang if top.lang in ('en','ru') and top.prob>=.80 else 'unsupported'
        except LangDetectException:return 'unsupported'
class SpacyBackend:
    model=''
    def __init__(self):
        spacy.util.fix_random_seed(0)
        self.nlp=spacy.load(self.model);self.nlp.max_length=4_000_000
    def analyze(self,text):
        doc=self.nlp(text)
        return NLPDocument(tuple(Sentence(i,s.start_char,s.end_char,s.text,tuple(Token(t.i,t.text,t.lemma_.casefold(),t.pos_,t.dep_,t.head.i,t.idx,t.idx+len(t.text),str(t.morph)) for t in s)) for i,s in enumerate(doc.sents)),tuple(NamedEntity(e.start_char,e.end_char,e.label_) for e in doc.ents))
class EnglishSpacyBackend(SpacyBackend):model='en_core_web_sm'
class RussianSpacyBackend(SpacyBackend):model='ru_core_news_sm'
