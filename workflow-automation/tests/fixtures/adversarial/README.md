# Adversarial fixtures

Attacker-controlled payloads used by the security suite (spec §10). Every field in
these files is T4 (spec §1.2): the payloads assert privileged `author_association`,
carry command-injection branch names, and embed natural-language "instructions"
aimed at the engine and any downstream LLM step.

The security tests assert that none of this content changes provenance
classification (still `UNTRUSTED`), reaches an interpreter, or obtains a credential.
