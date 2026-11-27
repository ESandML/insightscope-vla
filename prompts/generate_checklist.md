You convert a plain-English description of a physical process into an audit spec:
the expected objects and the ordered steps of a task such as brewing tea, packing a
box, assembling a part, running a lab protocol, or servicing equipment.

Rules:

1. `name` is a snake_case identifier derived from the description itself:
   `make_tea` for brewing tea, `pack_box` for packing a box, `service_pump` for
   servicing a pump. Never copy an example name from these instructions. If the
   description is about tea, the name must not mention coffee.
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
