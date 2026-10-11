# Roadmap

Not part of the current build. Items move into scope only after every current must-have is done and verified.

AgentCore Memory is not on this list: it is part of Milestone 1 (design section 8.7, D11).

- Milestone 2 (planned, target Oct 16-20): move the agent loop onto Amazon Bedrock AgentCore Runtime
  behind the existing `AgentRunner` interface, keep Lambda as the event entry point, and add AgentCore
  Observability traces if workable. If Runtime cannot be made reliable by Oct 20, Lambda stays and the docs say so
  (docs/decisions.md D11).
- Deleting one household's AgentCore Memory records on request (design section 8.7).
- Reminders at times other than the morning check-in chain (design section 8.2).
- More languages, starting with Spanish: one row in the language table plus a verification test.
- A simple family web page.
- Pharmacy integrations beyond email.
- Home-care agency dashboard.
- Smart-speaker or TV mode.
