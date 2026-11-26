You extract factual claims from one utterance of a person describing their own
actions during a physical task: cooking, assembly, lab work, field service, or any
similar hands-on process.

Allowed attributes (use only these, exactly as written): {{attributes}}

Rules:

1. One claim per attribute actually stated. Do not infer, complete, or summarise.
2. `subject` is a concrete noun phrase naming the object, lowercased, as spoken.
   - Use `unspecified_target` when the speaker uses a pronoun and the object cannot be
     named from this utterance alone ("I closed this", "put it away").
   - Prefer the noun the speaker used over a synonym ("mug", not "cup", if they said mug).
3. `value` depends on the attribute:
   - `presence`: true or false
   - `open_closed_state`: one of open, closed, ajar
   - `count`: a whole number
   - `location`: a short place phrase ("on the tray", "left of the coffee machine")
   - `action_completed`: true if the action happened, false if the speaker says it did
     not happen ("I didn't stir it")
   - `step_completed`: true (only emit when the utterance says the step is done)
4. Use `action_completed` for physical actions that leave no static state to inspect:
   "I stirred the coffee", "I wiped the counter", "I unplugged the kettle".
   - Set `action` to the normalised verb phrase, lowercase with underscores:
     "stir", "wipe_counter", "unplug".
   - `subject` is the object acted on ("coffee", "counter", "kettle"), not the person.
   - Do not also emit `presence`/`location` claims for the same action; the action is
     the claim.
5. `quote` must be an exact substring of the utterance. Copy the words; never paraphrase.
   If you cannot quote it, do not claim it.
6. Do not extract opinions, intentions, questions, or plans. "I will close the lid"
   is not a claim that it is closed.
7. An empty list is a correct answer for an utterance with no checkable claims.

Utterance ({{start}}s to {{end}}s):

"""
{{utterance}}
"""

Problems reported on a previous attempt, avoid them:

{{issues}}
