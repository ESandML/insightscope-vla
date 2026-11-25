"""Wire contracts: what models are allowed to return.

These are deliberately separate from ``domain/``. A wire contract is flat, forbids
unknown fields, and contains no internal bookkeeping. When a prompt changes, only
this package should move.
"""
