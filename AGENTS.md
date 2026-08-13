# SurfAnalyze Development Rules

## Primary goal
Ship the smallest usable SurfAnalyze MVP as quickly and safely as possible.

Do not add new features unless explicitly requested.
Prefer finishing existing functionality over redesigning or refactoring.

## Development approach
- Inspect relevant code before editing.
- Understand the existing architecture before proposing changes.
- Make the smallest change that solves the current problem.
- Do not rewrite working components without a concrete reason.
- Work on one task at a time.
- Avoid unnecessary abstractions and premature optimization.

## Git workflow
- Never develop directly on main.
- Create a dedicated branch for implementation tasks:
  codex/<short-task-name>
- Never force-push.
- Never rewrite Git history.
- Never merge into main without explicit approval.
- Review the entire diff before finishing.

## Testing
- Run relevant existing tests after every change.
- Run lint/type checks if configured.
- Start the application locally when technically possible.
- Verify the affected user flow.
- Never claim something works unless it was actually tested when testing is possible.

## Self-review
Before completing every implementation task:
1. inspect git diff against main,
2. look for regressions,
3. look for logic errors,
4. look for security problems,
5. look for unnecessary complexity,
6. look for duplicated or dead code,
7. fix confirmed issues,
8. run relevant tests again.

## Security
- Never commit API keys, Telegram tokens, passwords, cookies, certificates, .env files or secrets.
- Use environment variables.
- Never display full secrets in responses or logs.
- Never rotate or modify credentials unless explicitly requested.

## Dangerous operations
Ask before:
- deleting persistent data,
- irreversible database migrations,
- deleting large amounts of code,
- changing authentication architecture,
- replacing frameworks,
- changing production infrastructure.

## MVP focus
The intended core flow is:

User opens SurfAnalyze
→ uploads surf video
→ video is accepted and processed
→ analysis result is generated
→ user can see the result.

Everything not required for that flow is secondary until MVP is working.

## Completion report
At the end of every task report:
- root cause or objective,
- what changed,
- files changed,
- commands/tests executed,
- test results,
- known remaining issues,
- recommended next step.

## Code review
Flag:
- regressions,
- broken user flows,
- missing error handling,
- security vulnerabilities,
- leaked credentials,
- unnecessary complexity,
- changes unrelated to the task.
