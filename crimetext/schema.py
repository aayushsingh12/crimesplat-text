"""The closed vocabulary shared by the extractor, the validator, the graph builder and the dashboard."""

# "thing" = countable, trackable instance; "stuff" = setting or region. This is the panoptic split.
ENTITY_TYPES = {
    "PERSON": "thing", "GROUP": "thing", "OBJECT": "thing", "WEAPON": "thing", "VEHICLE": "thing",
    "DOCUMENT": "thing", "ANIMAL": "thing",
    "LOCATION": "stuff",
}
# literal object types: rendered as attribute chips on the subject, not as graph nodes
LITERAL_TYPES = {"ATTRIBUTE", "STATE", "DATETIME", "QUANTITY", "STATEMENT"}

PREDICATES = [
    # where / who
    "LOCATED_AT", "LIVED_AT", "WORKED_AT", "FAMILY_OF", "KNEW", "OWNED", "MEMBER_OF",
    # description
    "HAS_ATTRIBUTE", "IN_STATE", "WORE", "HAD",
    # perception and speech
    "SAW", "HEARD", "SAID", "REPORTED", "DESCRIBED",
    # the incident
    "KILLED", "SHOT", "ATTACKED", "ABDUCTED", "THREATENED", "TOOK", "LEFT_AT",
    # movement
    "TRAVELED_TO", "ENTERED", "LEFT",
    # discovery and evidence
    "FOUND", "FOUND_AT", "COLLECTED", "EXAMINED", "IDENTIFIED_AS", "MISSING_FROM",
    # investigation
    "SEARCHED", "INTERVIEWED", "CONTACTED", "SUSPECTED_OF", "ARRESTED", "RELEASED", "CLEARED",
    "CHARGED_WITH", "OFFERED", "PLANNED", "PAID",
    "OTHER",
]
CERTAINTY = ["stated", "reported", "alleged", "speculated"]   # strongest to weakest wording
EVENT_KINDS = ["action_point", "discovery", "investigation", "background", "legal", "media"]
