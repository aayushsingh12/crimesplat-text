# Extraction task: case passages -> grounded claims

You are given a JSON file with numbered passages from a criminal case file. Extract what each
passage CLAIMS, as subject-predicate-object triples. You do not decide what is true. You record
who or what is said to have done what, where, when, and according to whom.

## Output: one JSON object, nothing else

```json
{
  "claims": [
    {"pid": "p0123", "s": "Michael Short", "s_type": "PERSON",
     "p": "FOUND_AT", "o": "carport", "o_type": "LOCATION",
     "quote": "found in the carport", "time_text": null,
     "certainty": "stated", "attributed_to": null, "p_text": null}
  ],
  "events": [
    {"title": "Bodies discovered at the Short home", "kind": "discovery",
     "pids": ["p0120", "p0121", "p0123"], "summary": "One sentence, plain words."}
  ]
}
```

## Rules for claims

1. `pid` is the id of the passage the claim comes from. One passage usually gives 1 to 4 claims.
   Skip passages that are navigation, headings or contact boilerplate.
2. `quote` must be copied character for character from that passage (3 to 25 words). Do not
   paraphrase, do not fix spelling, do not join text from two places. A claim whose quote is not
   found in the passage is thrown away.
3. `s` and `o` are entity names. Use the fullest name the text gives ("Michael Short", not "he"
   or "Michael"). Resolve pronouns from context. Keep unnamed people distinct and descriptive:
   "unidentified man at Pluma plant", "witness who saw the truck". Never invent a name.
4. Types for `s_type` and `o_type`:
   - things: PERSON, GROUP (agency, company, family), OBJECT, WEAPON, VEHICLE, DOCUMENT, ANIMAL
   - places: LOCATION (house, room, road, town, county, wooded area)
   - literals, only for `o_type`: ATTRIBUTE ("wearing red shirt", "age 9"), STATE ("dead",
     "missing", "crying"), DATETIME, QUANTITY, STATEMENT (the content of what someone said)
5. `p` must be one of:
   LOCATED_AT, LIVED_AT, WORKED_AT, FAMILY_OF, KNEW, OWNED, MEMBER_OF, HAS_ATTRIBUTE, IN_STATE,
   WORE, HAD, SAW, HEARD, SAID, REPORTED, DESCRIBED, KILLED, SHOT, ATTACKED, ABDUCTED,
   THREATENED, TOOK, LEFT_AT, TRAVELED_TO, ENTERED, LEFT, FOUND, FOUND_AT, COLLECTED, EXAMINED,
   IDENTIFIED_AS, MISSING_FROM, SEARCHED, INTERVIEWED, CONTACTED, SUSPECTED_OF, ARRESTED,
   RELEASED, CLEARED, CHARGED_WITH, OFFERED, PLANNED, PAID, OTHER.
   With OTHER, put a short verb phrase in `p_text` ("sold home to"). Otherwise `p_text` is null.
   Direction matters: subject does the thing to the object ("killer" SHOT "Michael Short").
   Physical description goes in HAS_ATTRIBUTE / WORE / IN_STATE with a literal object.
6. `time_text`: a date or time phrase from the passage if it has one ("about 9 a.m.",
   "September 25, 2002"), else null. Do not copy the passage's `date_heading` here; it is applied
   automatically. Only give `time_text` when the passage itself states a different or more
   precise time.
7. `certainty`: "stated" (plain assertion), "reported" (reportedly, according to), "alleged"
   (claimed, accused, said by an interested party), "speculated" (may have, possibly, theory).
8. `attributed_to`: the person or agency the passage says this comes from ("Sheila Davis",
   "investigators", "Henry County Sheriff's Office"), else null.
9. Prefer concrete physical and investigative facts: who was where, what was found where,
   wounds, weapons, vehicles, clothing, sightings, searches, statements, arrests. Skip
   commentary and appeals for information.

## Rules for events

An event is one beat of the story that a detective would put on a timeline. Group passages that
share a date heading and topic. 1 to 5 events per file. `kind` is one of: action_point (the crime
itself or a physical act by a person of interest), discovery, investigation, background, legal,
media. Every pid in `pids` must exist in the input.

## Check your work

After writing the output file run the validator named in your instructions. Fix every claim it
reports as ungrounded by copying the quote again from the passage, then rerun until it passes.
