---
name: writeup
description: Generate a writeup with format. Use when you want to generate a writeup.
---

## Instruction

1. Read through the `EXPLOIT.md` and summarize it. 
2. Save the write up in the directory with name `WRITEUP.md`

## Output

```
# Writeup \#{session_id}
Generated time: {time}
Flag: {flag}

{exploit_steps}
```

### Exmaple Output

```
# Writeup \#1
Generated time: 2026-05-26 23:09
Flag: flag{test}

Use dirsearch tool to scan the website and `robots.txt` is found. The contents of `robots.txt` says that `/flllag` exists. Visit `/flllag` to get the flag.
```