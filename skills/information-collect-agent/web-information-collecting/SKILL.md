---
name: web-information-collecting
description: Collect evidence-backed reconnaissance for authorized web targets. Use when given an HTTP/HTTPS URL, host, CTF web challenge, or penetration-test scope that needs web information collection, target normalization, service fingerprinting, endpoint discovery, artifact logging, or a concise INFO.md reconnaissance brief before exploitation.
---

# Web Information Collecting

## Goal

Collect enough web-target information for the main agent to choose realistic attack paths. Stay in reconnaissance mode: document scope, observed behavior, exposed endpoints, technologies, interesting parameters, and missing evidence. Do not perform exploitation unless the user explicitly asked for it and the current agent has enough authorization and context.

## Inputs

Expect one or more of:

- Target URL, host, IP, or service hint
- Session ID or working directory
- Existing `INFO.md` content
- Prior conversation, tool output, screenshots, or saved artifacts

If a host is provided without a scheme, infer HTTP and HTTPS candidates and clearly mark any untested candidate as unverified.

## Working Directory

- Treat the working directory as session-scoped. Do not write outside it.
- Read `INFO.md` first when it exists.
- Keep existing notes. Append or update concise entries instead of replacing useful history.
- Record commands, tools, target URLs, output files, key findings, and short results in `INFO.md`.
- Use `write_file` for a new `INFO.md`; use `edit_file` or rewrite with preserved prior content when appending.

## Workflow

1. Normalize scope.
   - Identify in-scope URLs, hosts, ports, base paths, and user-provided hints.
   - Separate confirmed facts from assumptions.
   - Note redirects, virtual-host requirements, credentials, cookies, or headers if provided.

2. Review existing evidence.
   - Read `INFO.md` and referenced artifacts before repeating work.
   - Skip duplicate scans unless the prior result is stale, incomplete, or for a different URL/scope.

3. Perform low-noise baseline checks.
   - Fetch the root page and important known paths if HTTP request tooling is available.
   - Capture status codes, titles, headers, cookies, redirects, response size, and obvious framework/CMS/static-site signals.
   - Save only useful response bodies or command outputs as artifacts; avoid dumping large pages into context.

4. Discover endpoints when needed.
   - Use the `feroxbuster` tool for authorized HTTP/HTTPS targets when known paths are insufficient.
   - Start with conservative defaults: shallow depth, modest threads, redirects enabled, and a short timeout.
   - Add extensions only when evidence suggests a stack, such as `php`, `asp`, `aspx`, `jsp`, `txt`, `bak`, or `zip`.
   - Summarize notable paths, status codes, redirects, errors, and output locations in `INFO.md`.

5. Fingerprint the application.
   - Use the `nuclei_fingerprint` tool for authorized HTTP/HTTPS targets when
     automatic technology detection or nuclei template evidence would clarify
     the stack.
   - Infer technologies from headers, HTML, script paths, static assets, cookies, routes, error pages, and response formats.
   - Prefer evidence over guesswork. If a product/version is uncertain, mark it as likely or unknown.
   - For source leaks, directory listings, backup files, debug pages, swagger/openapi docs, admin panels, upload forms, login flows, and API endpoints, record why each is interesting.

6. Produce an attack-surface brief.
   - Group findings by target and path.
   - Highlight likely next actions for the exploit agent.
   - Include dead ends or negative results only when they prevent wasted repeated work.

## INFO.md Entry Format

Append entries in this shape:

```markdown
## Web Information Collection - <timestamp or short label>

- Scope: <targets tested>
- Actions:
  - `<tool or command>` -> <short result or artifact path>
- Findings:
  - <evidence-backed observation>
- Interesting paths:
  - `<method/path>` <status> - <why it matters>
- Next:
  - <specific recommended follow-up>
```

Keep entries short. Link or name artifact files for detailed output instead of pasting large scans.

## Stop Conditions

Stop collecting when one of these is true:

- There is enough evidence to choose one or more concrete exploit paths.
- The target appears static or unreachable and further collection would repeat prior work.
- Tooling, authorization, credentials, DNS, or network access is missing.
- Feroxbuster and baseline checks produce no new useful paths.

When stopping, state what was confirmed, what remains unknown, and the best next step.

## Guardrails

- Do not brute force credentials, tokens, OTPs, or hidden parameters without explicit authorization and evidence that it is necessary.
- Do not run high-volume scans by default.
- Do not expand scope to sibling domains, private networks, or unrelated hosts unless they are explicitly in scope.
- Do not claim a vulnerability, exploitability, product, or version without supporting evidence.
- Do not call a service uninteresting just because the root page is empty; check headers, redirects, source, common metadata, and discovered paths first.
