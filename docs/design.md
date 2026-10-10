# Design

Status: outline. Each section is filled in the next revision. AWS service names, APIs, resource types, limits and
model IDs below are planned, not yet verified. Each one is checked against official AWS documentation or a real
call and recorded in `docs/decisions.md` (with the doc URL) before it is used in code.

## 1. Overview

AuraSenior is a companion that lives inside WhatsApp for older people who send voice notes and will not install an
app. It checks in each morning, understands voice replies in Hindi and English, keeps family and care team informed
on RCS, SMS and email, and only acts on her behalf (refills, alerts) after a person approves.

It is not a medical device. It never diagnoses, names a disease, changes doses or gives a health score.

Demo household: Kamala (78, Pune, WhatsApp voice), her son Rohan (Seattle, RCS with SMS fallback), and her doctor
or pharmacy (email).

## 2. Architecture

Serverless, per-household state, near-zero idle cost. Inbound events (WhatsApp messages, RCS/SMS replies, delivery
events, schedules) reach Lambda handlers that call one agent; the agent uses tools that send through channel
adapters.

```mermaid
%% Placeholder. Filled in the next revision:
%% WhatsApp / RCS / SMS / SES events -> event intake -> agent (Bedrock) -> tools -> channel adapters -> people
%% EventBridge Scheduler -> check-in, follow-up, weekly summary
%% DynamoDB: household, medicine log, conversation state, signals, approvals, trace
```

## 3. AWS services and APIs used (all to be verified)

- AWS End User Messaging Social: WhatsApp voice and text with the elder, Meta-approved templates for messages the
  agent starts, the 24-hour customer-service window, inbound message and status events.
- AWS End User Messaging SMS and RCS: RCS rich cards with suggested replies for Rohan (testing agent, registered test
  devices), SMS fallback (simulator origination number to simulator destinations), inbound replies and events.
- Amazon SES: pharmacy refill email and weekly summary email (sandbox, verified recipients), configuration set with
  event tracking.
- Amazon Bedrock and Bedrock AgentCore: model for understanding and planning; AgentCore Runtime, Memory and
  Observability if adopted (section 4). Model chosen from what the account actually lists.
- Amazon Transcribe: voice note to text with word timestamps (Hindi and English support to be confirmed).
- Amazon Polly: text to voice note (Hindi voice and output format suitable for WhatsApp to be confirmed).
- AWS Lambda: webhooks, event handlers, agent tools.
- Amazon DynamoDB: household data, logs, approvals, trace.
- Amazon EventBridge Scheduler: daily check-in, follow-ups, weekly summary.

## 4. Agent runtime decision (to decide, with reasons)

Option A: Bedrock AgentCore Runtime, Memory and Observability, agent written with Strands Agents.
Option B: Lambda calling the Bedrock Converse API with tool use, memory and trace kept in DynamoDB.
Decision criteria: availability in us-east-1 for this account, boto3/CLI support (project venv), deploy path from
IaC, cold start and cost, how traces are shown in the demo trace view. The agent code sits behind one interface so
B is a working fallback if A is blocked.

## 5. IaC decision (to decide, with reasons)

Option A: AWS CDK. Option B: AWS SAM.
Decision criteria: support for every resource type used (including AgentCore and End User Messaging resources, if
any exist in CloudFormation), a single stack named `aurasenior` with tag project=aurasenior, reproducible deploy from
the README, and not modifying the shared `aws-sam-cli-managed-default` stack.

## 6. Channel matrix (placeholder)

One table filled in the next revision: for each event (morning check-in, follow-up, refill request, refill
confirmed, missed check-in, fall or help, "How was Mom?", weekly summary, opt-in, STOP), who receives it, on which
channel, and with which WhatsApp template, RCS card, SMS fallback text or SES template.

## 7. Channel adapter interface and local simulators

One small interface per channel (send, parse inbound, parse status event) with two implementations: real AWS and a
local simulator that records messages to a file. Selected by configuration per channel. Simulated paths are labelled
as simulated in code, logs, the trace view and the demo.

## 8. Agent tools and memory

Tools: `send_whatsapp_voice`, `send_whatsapp_text`, `send_whatsapp_template`, `send_rcs_card`, `send_sms`,
`send_email`, `log_medicine`, `get_household`, `schedule_followup`, `escalate`. Each tool validates input, checks
consent and channel rules (for example the 24-hour window) before sending, and writes a trace entry.
Memory: her medicines, routine, people she mentions, and short notes from recent conversations, kept per household.

## 9. Household data model

DynamoDB, keyed by household. Items planned: household profile and members with channel and consent per channel,
medicines and stock, medicine log, conversation window state, pending approvals, follow-ups, voice signals, and the
agent trace. Minimal data kept; family sees summaries, not full transcripts, unless the elder agrees.

## 10. Scheduled check-in

EventBridge Scheduler starts the 9 AM (her local time) check-in. Outside the 24-hour window the agent must open with
an approved WhatsApp template, then continue with voice notes once she replies.

## 11. Refill-approval flow

She says a medicine has run out. The agent sends Rohan an RCS card with [Order refill] [I'll handle it] [Call Mom]
(SMS with a short link if RCS fails). Only after he taps Order refill does SES email the pharmacy, and she gets a
voice note confirming it.

## 12. Missed check-in and fall escalation

No reply by a set time: one gentle follow-up voice note, then SMS or RCS to Rohan. Words like "I slipped" or "help"
send an urgent alert to Rohan and a neighbour at once, and the agent keeps talking to her until someone confirms.

## 13. Weekly summary and "How was Mom?"

Every Sunday SES sends a short factual summary (medicine days taken, refills, mentions of pain or low mood,
emergencies). Rohan can ask "How was Mom this week?" on RCS or SMS and get a short answer built from the same data.

## 14. Opt-in and STOP handling

Every person opts in on every channel before the agent messages them. STOP (and its Hindi equivalent, to be chosen)
on any channel stops that channel for that person at once, is recorded, and is respected by every tool.

## 15. Tier 1 voice signals: change from her usual

From Transcribe word timestamps and text: speech rate, pauses, reply delay, amount spoken, and mentions of pain or
low mood. Each is compared only with her own last two weeks. The only output is a "worth a call" suggestion to
family with the plain reason. Never a diagnosis, a disease name or a score.

## 16. Testing plan

Unit tests for adapters, tools, consent and window rules, the data model and the signals. One end-to-end scenario
that replays the demo story (check-in, voice reply, refill approval, pharmacy email, missed check-in, fall alert,
weekly summary) against the simulators and prints the agent trace. Live channel checks are saved under
`docs/evidence/`.
