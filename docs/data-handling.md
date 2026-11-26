# Data handling

Short version: everything stays on your machine, and your face never goes into git.

## Where things live

| Thing | Location | Committed |
| --- | --- | --- |
| Source clip / audio | wherever you keep it | no |
| Extracted keyframes, flagged frames | `artifacts/<run_id>/` | no |
| Audit history | `audits.db` | no |
| Model weights | pulled by Ollama, outside the repo | no |
| Settings / API keys | `.env` | no (`.env.example` is) |

`.gitignore` enforces all of the above. `make check` does not need any of it.

## Rules

1. **Do not commit footage or audio of people.** Test with synthetic fixtures or clips you
   are happy to publish; the repository's fixtures are generated, not recorded.
2. **Keep artifacts local.** `artifacts/` and `audits.db` are run outputs. Deleting them must
   lose nothing except history.
3. **No secrets in the repo.** `.env` only, and only locally. CI needs no credentials for the
   default test suite — that is deliberate.
4. **Don't paste transcripts into issues.** Even for a kitchen-counter demo, a transcript
   can contain names and locations. Reproduce with a minimal synthetic example.

## If this is later used with real recordings

Add the redaction step before anything leaves the machine: a `Redactor` on the transcript,
applied at ingestion, so that no node or client ever sees raw text. The seam is
intentionally not built yet — there is nothing to protect while fixtures are synthetic,
and unused security machinery rots.
