# Decisions

Each entry records what was checked, how (official doc URL or a real read-only call), and what was decided.
Evidence files live in `docs/evidence/`. Account IDs, user IDs and emails are redacted in all evidence.
All calls below ran on 2026-10-10 in us-east-1 under the project AWS account and IAM user `aws-ses-serv`
(identity confirmed with `aws sts get-caller-identity`, see `probe-env-2026-10-10.txt`).

## D1. Bedrock models available to the account (2026-10-10)

Checked by a real call:
- `aws bedrock list-foundation-models --region us-east-1` (124 models) and `aws bedrock list-inference-profiles`
  (99 system-defined profiles). Raw output: `bedrock-foundation-models-2026-10-10.json`,
  `bedrock-inference-profiles-2026-10-10.json`; short list: `bedrock-models-summary-2026-10-10.txt`.
- Claude 3.5 Sonnet does not appear in either list. It is not used.
- Anthropic and Amazon Nova 2 models are listed with inference type `INFERENCE_PROFILE`, so they are called through
  a `us.` or `global.` inference profile ID, not the bare model ID.

Docs:
- https://docs.aws.amazon.com/cli/latest/reference/bedrock/list-foundation-models.html
- https://docs.aws.amazon.com/cli/latest/reference/bedrock/list-inference-profiles.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModels.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListInferenceProfiles.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle.html
- https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html

## D2. Converse with tool use (2026-10-10)

Checked by a real call (`.build/p2_converse.py`, venv boto3 1.43.111): one `log_medicine` tool, a Hindi
voice-note transcript, then a second turn that returns a `toolResult` and asks for a short Hindi reply.
Evidence: `bedrock-converse-tool-use-2026-10-10.json` (full request and responses),
`bedrock-converse-tool-use-summary-2026-10-10.txt`.

| Inference profile | Result |
| --- | --- |
| `us.amazon.nova-2-lite-v1:0` | Works end to end. Turn 1 `stopReason=tool_use` with two correct calls (metformin taken, amlodipine not taken and out of stock). Turn 2 `stopReason=end_turn` with a Hindi reply |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | `ResourceNotFoundException`: Anthropic use case details not submitted for this account |
| `us.anthropic.claude-sonnet-4-6` | Same as above |
| `us.anthropic.claude-haiku-5-5`, `us.anthropic.claude-sonnet-5`, `us.anthropic.claude-sonnet-5-5` | `AccessDeniedException`: model not available for this account |

Decision for now: the agent uses the Converse API with tool use. The model ID is one config value. Default is
`us.amazon.nova-2-lite-v1:0`, the only current model confirmed working in this account today. Its Hindi reply
had a small grammar slip, so Hindi output quality must be reviewed before the demo. Claude Haiku 4.5 or Sonnet 4.6
become usable once the account owner submits the one-time Anthropic use case form (Bedrock console, Model catalog,
any Anthropic model, or `PutUseCaseForModelAccess`); re-run the probe after that and record the result here.

Docs:
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use.html
- https://docs.aws.amazon.com/nova/latest/userguide/tool-use-definition.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-2-lite.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_PutUseCaseForModelAccess.html

## D3. Polly Hindi voice for WhatsApp voice notes (2026-10-10)

Checked by real calls (`.build/p3_polly.py`): `DescribeVoices` for hi-IN and en-IN with
`IncludeAdditionalLanguageCodes=true`, then `SynthesizeSpeech` with `LanguageCode=hi-IN`, Devanagari text,
`OutputFormat=ogg_opus`, `SampleRate=48000`. Evidence: `polly-hindi-2026-10-10.json`,
`polly-hindi-summary-2026-10-10.txt`.

DescribeVoices says:
- Kajal: primary en-IN, additional hi-IN, engines generative and neural.
- Aditi: primary en-IN, additional hi-IN, engine standard.
- Raveena: en-IN only, no additional language, engine standard. Raveena is not a Hindi voice.

SynthesizeSpeech results (all ogg_opus calls succeeded on the first try):

| Voice | Engine | ContentType | Bytes | Header |
| --- | --- | --- | --- | --- |
| Kajal | neural | `audio/ogg; codecs=opus` | 12766 | `OggS`, `OpusHead` present |
| Kajal | generative | `audio/ogg; codecs=opus` | 10586 | `OggS`, `OpusHead` present |
| Aditi | standard | `audio/ogg; codecs=opus` | 13060 | `OggS`, `OpusHead` present |
| Raveena | standard | `audio/ogg; codecs=opus` | 13786 | `OggS`, `OpusHead` present |

Notes:
- The API reference lists `audio/ogg` as the ContentType for ogg_opus; the live response is
  `audio/ogg; codecs=opus`. Code should accept both.
- The API reference says `LanguageCode` only matters for bilingual voices. Raveena accepted `hi-IN` without error,
  but she is not bilingual, so that request most likely used her en-IN default. Audio was not checked by ear.
- Decision: Kajal (neural by default, generative as an option) for Hindi, with `LanguageCode=hi-IN`; Kajal with
  en-IN for English. Aditi is the standard-engine fallback. ogg_opus at 48000 Hz is the output format.
- Not yet verified: that WhatsApp accepts and plays this file as a voice note through End User Messaging Social.

Docs:
- https://docs.aws.amazon.com/polly/latest/dg/API_SynthesizeSpeech.html
- https://docs.aws.amazon.com/polly/latest/dg/API_DescribeVoices.html
- https://docs.aws.amazon.com/polly/latest/dg/available-voices.html
- https://docs.aws.amazon.com/polly/latest/dg/bilingual-voices.html

## D4. Bedrock AgentCore in us-east-1 (2026-10-10)

Checked by real read-only calls (`.build/p4_agentcore.py`, venv boto3 1.43.111). Evidence:
`agentcore-us-east-1-2026-10-10.json`.
- The SDK has two clients: `bedrock-agentcore` (data plane, endpoint
  `https://bedrock-agentcore.us-east-1.amazonaws.com`) and `bedrock-agentcore-control` (control plane, endpoint
  `https://bedrock-agentcore-control.us-east-1.amazonaws.com`). Their operation lists are saved in the evidence.
- Every control-plane `List*` call that needs no parameters was made. These returned OK with zero items:
  ListAgentRuntimes, ListMemories, ListGateways, ListCodeInterpreters, ListBrowsers, ListBrowserProfiles,
  ListHarnesses, ListWorkloadIdentities, ListApiKeyCredentialProviders, ListOauth2CredentialProviders,
  ListOnlineEvaluationConfigs, ListPolicyEngines, ListDatasets, ListCapacityProviders, ListConfigurationBundles,
  ListConsentPortals, ListPaymentManagers, ListPaymentCredentialProviders. ListEvaluators returned 31 items
  (built-in evaluators).
- ListRegistries returned `AccessDeniedException` (not in the `aurasenior-dev` policy). AuraSenior does not need
  registries, so no change is requested.
- The AgentCore regions page lists US East (N. Virginia) as supported for Runtime and harness.
- Result: AgentCore Runtime and Memory are reachable in this account and region. The runtime choice (design
  section 4) is still open; this entry only records availability.

Docs:
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html
- https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/Welcome.html
- https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListAgentRuntimes.html
- https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListMemories.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/Welcome.html
