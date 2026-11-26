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
   - `location`: a short place phrase ("on the tray", "left of the laptop")
   - `step_completed`: true (only emit when the utterance says the step is done)
4. `quote` must be an exact substring of the utterance. Copy the words; never paraphrase.
   If you cannot quote it, do not claim it.
5. Do not extract opinions, intentions, questions, or plans. "I will close the laptop"
   is not a claim that it is closed.
6. An empty list is a correct answer for an utterance with no checkable claims.

Utterance ({{start}}s to {{end}}s):

"""
{{utterance}}
"""

Problems reported on a previous attempt, avoid them:

{{issues}}
