# Multi-session protocol

Paste this into a session's first message, or have the environment's setup script write it to
`~/.claude/CLAUDE.md` so every new session loads it. The control tower ([TOWER.md](TOWER.md))
reads the status blocks and FINDING lines it asks for.

```markdown
## Multi-session protocol
I run many sessions in parallel and read each one only briefly. Optimize for that.

Autonomy
- Do without asking: edit, build, test, benchmark, commit and push to your designated
  branch; fix and reply on PRs you opened; use subagents; schedule check-ins; spawn bug
  sessions as described below.
- Never without a written go from me: merge, tag, release or publish; push to branches
  you did not create; comment on issues or PRs you did not open; delete what you did not create.
- Any other decision: take the option you would recommend, note it as ASSUMPTION, continue.
  Ask only if a wrong guess costs more than ~1 hour of work or is hard to undo.
- If you must ask, ask everything in one message: numbered questions, each with your
  recommended answer. Keep working on whatever does not depend on the answers.

Reporting
- At most 10 lines of prose per turn. Report outcomes, not steps: no restating the task,
  no lists of files you read. Put tables, logs and analyses in a file on your branch or in
  the PR description, and link them. Give every number with its baseline and the
  commit/command it came from.
- End every turn with this block and nothing after it:
  STATUS: working | needs-you | blocked | done
  ASK: <numbered questions with recommended answers, or none>
  DONE: <up to 3 outcomes, with PR/commit links>
  NEXT: <one line>
  FINDING: <one line per NEW out-of-scope finding; omit if none>
- If set_session_title is available, prefix this session's title with its status when it
  changes (🔴 needs-you, ⛔ blocked, 🟢 working, ✅ done). Get your id from get_session
  called without an id.

Bugs outside your task: spawn a session, don't fix them here
- Bugs (wrong results, crashes, failing or flaky tests, build or packaging breakage,
  performance regressions) that are outside your task get their own session:
  1. Run list_sessions(mine: true) and check whether a session already covers the bug.
     If one does, skip to step 3.
  2. Otherwise call create_session with source_url set to the repo the bug is in. Title it
     "Bug: <short>" and tag it spawned-from:<your session id>. Never pass permission_mode plan.
     Its prompt must stand on its own: what is wrong; how to reproduce it (command, input,
     commit); evidence (log lines, numbers); suspected location (file:line); what "fixed"
     means; "Follow the multi-session protocol. Do not spawn sessions yourself: report
     further bugs as FINDING lines."
  3. Report it once in your status block:
     FINDING: <repo> <file:line|component> — <what> — <severity> — spawned: <session title>
- Minor items (typos, doc wording, small cleanups) get no session. Report them as FINDING only.
- Spawn at most 3 sessions on your own. After that, end the FINDING line with "spawn?"
  and leave the decision to me.
- If create_session isn't available, end the FINDING line with "spawn?".
```
