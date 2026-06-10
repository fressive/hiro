---
name: writeup
description: Generate evidence-based Markdown penetration-test and CTF writeups. Use when producing final reports, summaries, reproduction notes, exploit narratives, flags/proofs, artifact indexes, or next-step recommendations from collected reconnaissance, exploitation logs, tool outputs, and conversation context.
---

# Writeup

## Goal

Produce a concise, evidence-based Markdown report for the current session. Treat the provided conversation, tool outputs, `INFO.md`, `EXPLOIT.md`, saved artifacts, and final assistant result as the only source of truth.

## Workflow

1. Identify the working directory from the session context or explicit path. If no path is provided, use the current DeepAgents working directory.
2. Read available evidence files before writing the report, especially `INFO.md`, `EXPLOIT.md`, tool result files referenced in those notes, and any user-provided hints.
3. Extract only facts that are supported by evidence: target URLs, scope, commands, payloads, vulnerabilities, exploit results, flags, proof values, screenshots or files, and failed attempts that explain the final state.
4. Resolve contradictions by preferring direct tool output and saved logs over summaries. If the evidence is insufficient, mark the item as unverified instead of inventing details.
5. Write the final Markdown report to `WRITEUP.md` with `write_file`.
6. Return the same report Markdown as the final response, with no preamble or postscript.

## Report Structure

Use these sections when applicable:

```markdown
# Writeup

## Summary

## Scope

## Steps Performed

## Findings

## Evidence

## Impact

## Recommendations

## Artifacts

## Next Steps
```

Omit a section only when it has no useful evidence-backed content. Keep the report compact, but include exact commands, URLs, payloads, and outputs when they are necessary to reproduce or verify a finding.

## Evidence Rules

- Include a flag or proof value explicitly when present. If none is present, write `Flag: Not found`.
- Do not claim successful exploitation unless the evidence includes a successful result, retrieved flag, proof value, privileged action, or equivalent verification.
- Preserve payloads exactly where possible, including quoting, URL encoding, headers, and request bodies.
- Include failed commands or negative scan results only when they changed the investigation path or constrain the conclusion.
- If the target is unresolved, unavailable, or only partially tested, say so directly in `Next Steps`.
- Never include secrets, tokens, or credentials unless they are the challenge proof value or are essential to the documented finding.

## Style

- Write in clear technical Markdown.
- Prefer chronological steps for CTF writeups and finding-centered structure for penetration-test reports.
- Use fenced code blocks for commands, HTTP requests, payloads, and important output.
- Avoid speculation, marketing language, and generic security filler.
- Keep recommendations specific to the observed issue.
