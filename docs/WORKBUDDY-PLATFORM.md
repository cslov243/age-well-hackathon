# WorkBuddy platform reference

WorkBuddy is a Tencent AI agent desktop workstation, released March 2026. It is
almost certainly **not in your training data**, and the published English
documentation is thin, partly machine-translated, and in at least one place
wrong. Do not infer its formats from Claude Code, OpenAI Assistants, or any
other agent framework.

Each fact below is tagged:

- **[VERIFIED]** — read directly off a working installed plugin on disk.
- **[DOCS]** — stated in Tencent's documentation, not independently confirmed.
- **[UNKNOWN]** — open question; do not assume either way.

---

## Plugin structure [VERIFIED]

An expert and its skills ship as **one installable plugin**. Installed path on
Windows:

```
C:/Users/<USER>/.workbuddy-ai/plugins/marketplaces/my-experts/plugins/<plugin-name>/
```

```
care-navigator/
├── .codebuddy-plugin/
│   └── plugin.json                      # marketplace + display metadata
├── agents/
│   └── care-navigator.md                # the expert persona
├── skills/
│   └── care-coordinator-toolkit/
│       ├── SKILL.md                     # when/how to invoke each script
│       ├── scripts/*.py
│       ├── references/*.md
│       └── templates/*
├── avatars/
│   └── expert.png                       # 1024×1024 PNG; placeholder tolerated
└── README.md
```

Note the directory is `.codebuddy-plugin` — WorkBuddy shares an architecture and
codebase lineage with Tencent's CodeBuddy IDE, which is why its docs site still
carries CodeBuddy branding.

**The English docs claim skills are defined by `skill.yml`. They are not.** The
real format is `SKILL.md` with YAML frontmatter. Trust the on-disk structure.

Files on the target machine have **CRLF line endings**. Preserve them or expect
noisy diffs.

## `plugin.json` schema [VERIFIED]

Display fields are `{en, zh}` objects. A working example:

```json
{
  "name": "care-navigator",
  "version": "1.0.0",
  "description": "One-line English description.",
  "author": { "name": "Care Navigator", "email": "care-navigator@local" },
  "agents": ["./agents/care-navigator.md"],
  "skills": ["./skills/care-coordinator-toolkit"],

  "expertType": "agent",
  "agentName": "care-navigator",

  "displayName":        { "en": "Care Navigator", "zh": "照护领航员" },
  "profession":         { "en": "Family Care Coordinator", "zh": "家庭照护协调员" },
  "displayDescription": { "en": "...", "zh": "..." },
  "avatar": "avatars/expert.png",
  "categoryId": "12-IndustryConsultant",
  "defaultInitPrompt": { "en": "...", "zh": "..." },
  "plugin": "care-navigator",
  "tags": [
    { "en": "Government Letter Triage", "zh": "政府信件解读" }
  ],
  "quickPrompts": [
    { "en": "...", "zh": "..." }
  ]
}
```

`tags` and `quickPrompts` are arrays of `{en, zh}` objects, not arrays of
strings. `categoryId` is one of twelve fixed categories; `12-IndustryConsultant`
is the fallback for cross-domain personal advisory work.

## Agent file format [VERIFIED]

`agents/<name>.md`, YAML frontmatter then markdown body:

```yaml
---
name: care-navigator
description: "Activation condition — when this expert should be selected."
displayName:
  en: "Care Navigator"
  zh: "照护领航员"
profession:
  en: "Family Care Coordinator"
  zh: "家庭照护协调员"
maxTurns: 50
skills: [care-coordinator-toolkit]
---

# Body: persona, methodology, hard rules, in second person.
```

`description` is an **activation condition**, not a summary — it decides when
the expert gets selected. `skills:` is what wires the expert to its toolkit.

## Skill file format [VERIFIED]

`skills/<skill-name>/SKILL.md`, frontmatter is minimal:

```yaml
---
name: care-coordinator-toolkit
description: "What this skill provides and when the expert must use it."
---
```

The body documents, for the model's benefit: when to invoke each script, how to
invoke it, where the source of truth lives, and what the skill explicitly does
**not** do. Treat the body as a prompt, because that is what it is.

## Script invocation contract [VERIFIED]

Established convention across all existing scripts — **keep it**:

```bash
python3 scripts/<script>.py --input <input.json> [--output <output.json>]
```

- `--input` omitted → read JSON from **stdin**.
- `--output` omitted → write JSON to **stdout**.
- Every output object carries `tool_run_id` (uuid4) and `issued_at` (ISO 8601,
  `+08:00` Singapore offset) so an artifact can cite a specific run.
- Exit 0 on success. Raise on invalid input — do not emit a plausible wrong
  number.

**[UNKNOWN]** Whether WorkBuddy invokes `python3` or `python`, which interpreter
it resolves to on Windows, and what the working directory is at invocation time.
Take paths as arguments; do not rely on relative defaults resolving as expected.

## Experts vs skills vs expert teams [DOCS]

- A **skill** is a capability — it lets the AI *do* something.
- An **expert** is capability plus experience: persona + methodology + toolchain.
  It is a role-switching mechanism.
- An **expert team** is multiple experts with a leader that decomposes and
  parallelises. It costs **3–5× the credits of a single expert**. Do not build
  one here.

**Critical:** an expert has no filesystem access of its own. It only handles the
conversation and files the user actively provides, and reaches files or external
services *only* when equipped with a Skill or MCP, under user authorization. The
expert is the front end; the skill is the hands.

## Permission modes [DOCS] — this is the main operational risk

Under **Default Permissions**, WorkBuddy asks for confirmation before running
scripts, commands, or external programs. It is a runtime gate: even when the
agent has already planned the task, the decision returns to the user when the
next step runs a script.

**Full Access** turns off the confirmation flow for writing files, deleting
files, running scripts, and calling external programs. The docs advise against
it near personal document roots.

Since this project's entire architecture is "skills invoke deterministic Python",
Default Permissions means every script call raises a dialog.

**[UNKNOWN] — the single most important open question:** whether a scheduled
automation can carry Full Access, or whether unattended scheduled runs stall on
the confirmation dialog. If they stall, all scheduled skills (`daily-brief`,
`medication-watch`, `deadline-watch`, `scheme-radar`) must fall back to
caregiver-triggered runs. **Write them so either mode works.**

## Automation [DOCS]

Scheduled tasks support daily / weekly / hourly / one-time. Results push to
Slack, Telegram, Discord, or email on completion.

Chinese-language sources describe triggers as 定时/监听 — *scheduled or
listening* — suggesting a file-watch trigger may exist that the English docs
never mention. **[UNKNOWN]** If it does, `letter-triage` can be genuinely
event-driven; if not, fall back to an hourly poll of `inbox/`.

## Third-party marketplace skills [UNKNOWN]

WorkBuddy's marketplace carries first-party and partner skills, including
commerce integrations (GrabMall, GrabFood).

**Open question, testable only inside WorkBuddy:** can a commerce skill be
invoked such that it halts *before* checkout — preparing a cart for human review
rather than completing a purchase? If it cannot, it is unusable here regardless
of use case, because this product never acts financially on a senior's behalf.

Worth a five-minute check while access lasts. It either opens the door for a
post-submission pharmacy-delivery feature or closes it permanently. See
`CLAUDE.md` → Scope decisions for the reasoning and the prepared Demo Day
answer.

Second open question: trigger collisions between third-party skills and this
plugin's skills on the same input. Broad commerce trigger phrases are the most
likely source.

## Telegram [DOCS]

Bidirectional. Users can send **photos**, documents and files to the bot as
context, and automation results push back to it. This is how the senior gets her
own channel — she photographs a letter into her own chat rather than reaching
through her son's desktop.

Caveat: the bot only responds while WorkBuddy is running on the desktop with the
Assistant enabled. The caregiver's machine remains a dependency; say so openly
rather than letting a judge find it.

## Models and credits [DOCS]

- Custom API providers are supported — enter your own key.
- **Local Ollama** is supported via an OpenAI-compatible interface, with no
  token consumption and no paid key. This is the zero-credit development path.
- Not all models accept images. When a selected model lacks vision, the app
  surfaces a toast prompting a model switch — so the extraction step requires
  deliberately choosing a vision-capable model.

Architecture is local-first: data is processed locally and not uploaded; the
server handles only fragments, discarded after use.

## Security scan [DOCS]

WorkBuddy runs an automatic security scan before installing any skill, looking
for malicious scripts and risky behaviour. Consequences for authoring: no
secrets in any file, no credential handling, and prefer stdlib-only Python so
there is no dependency install step to flag.

**Outbound HTTP from a script is the remaining exposure**, and as of 6 August
2026 the project accepts it — see `docs/DECISIONS.md`. Whether the scanner
actually rejects it is **[UNKNOWN]** and untestable since access lapsed. If an
install is refused at submission, this is the first thing to strip out.

## Known documentation defects

- English docs say `skill.yml`; reality is `SKILL.md`. **Docs wrong.**
- The published `SKILL.md` in `care-coordinator-toolkit` references
  `scripts/verify_scheme.py`, which **does not exist**. The 30-day eligibility
  freshness rule it describes is documented but unimplemented.
- That same `SKILL.md` uses "14 days left on the metformin" as its worked
  example, while the script's own docstring example yields 7. Inconsistent.
