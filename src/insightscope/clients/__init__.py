"""Model clients: the only package allowed to talk to a model server.

Empty until Slice 3. The import contract in ``pyproject.toml`` already forbids
``reconcile`` and ``contracts`` from importing this package, so the dependency
direction is enforced before the first client exists.
"""
