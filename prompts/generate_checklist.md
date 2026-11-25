You convert a plain-English description of a desk task into a checklist.

Rules:

1. `name` is a short snake_case identifier for the task.
2. `expected_objects` lists the concrete objects involved, lowercased snake_case.
3. `aliases` maps each object to alternative names a person might actually say. Only
   real synonyms; do not invent related objects. Use the same keys as expected_objects.
4. `steps` is ordered as described. Each step has a snake_case `step_id` and a one-line
   description. Keep it under 12 steps and do not invent steps that were not described.
5. If the description is ambiguous, take the most literal reading.

Description:

"""
{{description}}
"""
