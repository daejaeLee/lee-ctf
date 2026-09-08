# Source-assisted analysis

When source exists, prefer it to blind prompt injection. Inventory the request handler, message
roles, prompt templates, hidden data insertion, conversation history, retrieval call, tool
registry, input guard, model call, judge/moderation call, schema/parser, and output sanitizer.

Use bounded searches:

```bash
rg -n -i 'system(_prompt)?|messages|role|content|tool_choice|function|retriev|embedding|vector|moderation|guard|judge|conversation|history|memory|secret|flag|schema|parser|validator' .
```

Write the actual execution order to `notes.md`, marking unobserved steps as probable or unknown.
Trace attacker control to a meaningful sink and test only the branch source makes plausible.
