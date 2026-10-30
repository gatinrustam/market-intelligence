from app.extraction.models import Actor


def issuer(source, registry):
    entity=registry.entities[source.issuer]
    return Actor(entity_id=source.issuer,entity_type=entity.entity_type,name=entity.name,role='issuer',resolution='canonical')


def speaker(name,registry):
    for key,entity in registry.entities.items():
        if entity.entity_type=='person' and name.casefold() in {s.casefold() for s in [entity.name,*entity.aliases]}:
            return Actor(entity_id=key,entity_type='person',name=entity.name,role='speaker',resolution='canonical')
    return Actor(entity_id=None,entity_type='person',name=name,role='speaker',resolution='unresolved')
