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

Decision (confirmed by the owner, 2026-10-10): the agent uses the Converse API with tool use, and the default
model is `us.amazon.nova-2-lite-v1:0`, the only current model confirmed working in this account today. The model
ID is one config value, `[agent] model_id` in `config/app.toml`, so another model can be swapped in without code
changes. Its Hindi reply had a small grammar slip, so Hindi output quality must be reviewed before the demo.
Claude Haiku 4.5 or Sonnet 4.6 become usable only if the account owner submits the one-time Anthropic use case
form (Bedrock console, Model catalog, any Anthropic model, or `PutUseCaseForModelAccess`). This is optional and
does not block the build. If it is submitted, re-run `.build/p2_converse.py` and add a comparison here.

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
  en-IN for English. Aditi is the standard-engine fallback. ogg_opus at 48000 Hz is the output format. Voice
  settings live in `[voice]` in `config/app.toml`.
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
- Result: AgentCore Runtime and Memory are reachable in this account and region. This entry only records
  availability; the runtime decision is D11.

Docs:
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html
- https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/Welcome.html
- https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListAgentRuntimes.html
- https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListMemories.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/Welcome.html

## How entries D3b to D14 were checked (2026-10-10)

- Doc URLs: every URL below returned HTTP 200 on 2026-10-10 (`curl`), and the facts quoted were read from the page
  text. Pages were saved locally while reading and are not committed.
- SDK model reads (no network): parameter and enum names were read from the botocore 1.43.111 service models in the
  project venv (`.build/p6_shapes.py`). This confirms names and enums only, not runtime behaviour.
- Real read-only calls under the project account: `polly describe-voices` for en-US (D3b) and
  `cloudformation describe-type` for every resource type in the template (D12). Evidence files are named in each
  entry.
- Not used as evidence: an earlier discovery run on 2026-10-10 (Claude models working, SMS spend limits, SES quota)
  ran under the wrong AWS profile, not the project account. Its output was moved out of `docs/evidence/` and none of
  its results are relied on here. Read-only calls only; nothing was created or changed.

## D3b. Polly en-US voice for English-speaking elders in the US (2026-10-10)

Real call `polly.describe_voices(LanguageCode='en-US', Engine='neural')` (`.build/p5_polly_en_us.py`), evidence
`polly-en-us-2026-10-10.json`: 13 voices, including Joanna, Ruth, Matthew, Danielle. Decision: Joanna, neural,
`LanguageCode=en-US` in the `en-US` language row. Synthesis to `ogg_opus` with Joanna is not yet called; it is the
first test when the `en-US` row is added (design section 9.2).

Docs: https://docs.aws.amazon.com/polly/latest/dg/available-voices.html,
https://docs.aws.amazon.com/polly/latest/dg/API_DescribeVoices.html

## D5. WhatsApp through AWS End User Messaging Social

Facts used in the design:
- Template messages are the only messages that can be sent to people who have not messaged in the last 24 hours;
  templates need Meta approval, review can take up to 24 hours (managing-templates). Non-template messages can only
  be sent in an open 24-hour customer service window that opens and resets with each user message (Meta pricing).
- Inbound messages are published to the event destination SNS topic, which must be enabled for the WABA
  (receive-message). The SNS topic policy must allow `social-messaging.amazonaws.com` to `sns:Publish`
  (managing-event-destinations-add).
- Media: upload to S3, then `PostWhatsAppMessageMedia` returns a media ID used in `SendWhatsAppMessage`; WhatsApp
  keeps media 30 days; CLI example uses `--meta-api-version v20.0` (send-message-media). Audio types include
  `audio/ogg`, 16 MB max (supported-media-types). Mark as read with a `status: read` message (receive-message-status).
- Default quota: `SendWhatsAppMessage` 1,000 requests per second, `PostWhatsAppMessageMedia` and
  `GetWhatsAppMessageMedia` 100 (quotas).
- SDK model: `SendWhatsAppMessage(originationPhoneNumberId, message, metaApiVersion)`,
  `GetWhatsAppMessageMedia(mediaId, originationPhoneNumberId, metadataOnly, destinationS3PresignedUrl,
  destinationS3File)`, `PostWhatsAppMessageMedia(originationPhoneNumberId, sourceS3PresignedUrl, sourceS3File)`,
  `PutWhatsAppBusinessAccountEventDestinations(id, eventDestinations)`, `CreateWhatsAppMessageTemplate(
  templateDefinition, id)`.
- `cloudformation describe-type AWS::SocialMessaging::WhatsAppBusinessAccount`: TypeNotFoundException (evidence
  `cfn-types-2026-10-10.json`). WhatsApp setup is done by the owner in the console plus `scripts/post_deploy.py`.

Docs:
- https://docs.aws.amazon.com/social-messaging/latest/userguide/what-is-service.html
- https://docs.aws.amazon.com/social-messaging/latest/userguide/managing-templates.html
- https://docs.aws.amazon.com/social-messaging/latest/userguide/create-message-templates-api.html
- https://docs.aws.amazon.com/social-messaging/latest/userguide/receive-message.html
- https://docs.aws.amazon.com/social-messaging/latest/userguide/receive-message-status.html
- https://docs.aws.amazon.com/social-messaging/latest/userguide/managing-event-destinations-add.html
- https://docs.aws.amazon.com/social-messaging/latest/userguide/send-message-media.html
- https://docs.aws.amazon.com/social-messaging/latest/userguide/supported-media-types.html
- https://docs.aws.amazon.com/social-messaging/latest/userguide/message-types.html
- https://docs.aws.amazon.com/social-messaging/latest/userguide/quotas.html
- https://docs.aws.amazon.com/social-messaging/latest/userguide/whatsapp-best-practices.html
- https://docs.aws.amazon.com/social-messaging/latest/APIReference/API_SendWhatsAppMessage.html
- https://docs.aws.amazon.com/social-messaging/latest/APIReference/API_PostWhatsAppMessageMedia.html
- https://docs.aws.amazon.com/social-messaging/latest/APIReference/API_GetWhatsAppMessageMedia.html
- https://docs.aws.amazon.com/social-messaging/latest/APIReference/API_PutWhatsAppBusinessAccountEventDestinations.html
- https://docs.aws.amazon.com/social-messaging/latest/APIReference/API_CreateWhatsAppMessageTemplate.html
- https://developers.facebook.com/docs/whatsapp/pricing/
- https://developers.facebook.com/docs/whatsapp/message-templates/guidelines/

## D6. RCS and SMS through AWS End User Messaging SMS

Facts used in the design:
- A testing agent sends to registered test devices without carrier approval; a test device is added with
  `CreateVerifiedDestinationNumber --rcs-agent-id` and a verification code (rcs-getting-started, rcs-testing).
- Rich card: `Content.RichCard.StandaloneCard` with `CardOrientation` (required, VERTICAL or HORIZONTAL), at least
  one of Media, Title, Description; title max 200 characters; up to 4 card suggestions (rcs-rich-cards). A Reply
  suggestion returns its `PostbackData` to the application (rcs-suggestions).
- Per-message fallback: `FallbackConfiguration` on `SendRcsMessage`; SDK model members `Channel` (enum `SMS`, `MMS`),
  `MessageBody`, `MediaUrls`, `OriginationIdentity` (rcs-fallback-per-message, SDK model). `Context` map max 5
  entries (API_SendRcsMessage).
- Inbound RCS follows the two-way SMS pattern: delivered to an SNS topic set on the RCS agent; the topic policy or a
  role must allow `sms-voice.amazonaws.com` to publish (rcs-inbound). Two-way SMS payload fields
  `originationNumber`, `destinationNumber`, `messageKeyword`, `messageBody`, `inboundMessageId` (two-way-sms-payload).
- Delivery events: `RCS_DELIVERED` and `RCS_READ` among RCS event types (rcs-events).
- Opt-out: replies with STOP and the other required keywords add the number to the opt-out list unless self-managed
  opt-outs are on (opt-out-list, keywords-required).
- Simulator: origination simulator numbers send to destination simulator numbers (test-phone-numbers);
  `AWS::SMSVOICE::PhoneNumber` `NumberType` enum includes `SIMULATOR`; required properties `IsoCountryCode`,
  `NumberCapabilities`, `NumberType`, `MandatoryKeywords` (CloudFormation schema, `cfn-types-2026-10-10.json`).

Docs:
- https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs.html
- https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-getting-started.html
- https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-testing.html
- https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-rich-cards.html
- https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-suggestions.html
- https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-fallback-per-message.html
- https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-sms-fallback.html
- https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-events.html
- https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-inbound.html
- https://docs.aws.amazon.com/sms-voice/latest/userguide/two-way-sms.html
- https://docs.aws.amazon.com/sms-voice/latest/userguide/two-way-sms-payload.html
- https://docs.aws.amazon.com/sms-voice/latest/userguide/opt-out-list.html
- https://docs.aws.amazon.com/sms-voice/latest/userguide/keywords-required.html
- https://docs.aws.amazon.com/sms-voice/latest/userguide/test-phone-numbers.html
- https://docs.aws.amazon.com/sms-voice/latest/userguide/configuration-sets-sns.html
- https://docs.aws.amazon.com/pinpoint/latest/apireference_smsvoicev2/API_SendRcsMessage.html
- https://docs.aws.amazon.com/pinpoint/latest/apireference_smsvoicev2/API_SendTextMessage.html
- https://docs.aws.amazon.com/pinpoint/latest/apireference_smsvoicev2/API_UpdateRcsAgent.html
- https://docs.aws.amazon.com/pinpoint/latest/apireference_smsvoicev2/API_CreateVerifiedDestinationNumber.html
- https://docs.aws.amazon.com/pinpoint/latest/apireference_smsvoicev2/API_DescribeOptedOutNumbers.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-smsvoice-phonenumber.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-smsvoice-configurationset.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-smsvoice-optoutlist.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-smsvoice-rcsagent.html

## D7. Email through Amazon SES

Facts used in the design:
- Sandbox: only verified addresses or the mailbox simulator, 200 messages per 24 hours, 1 per second
  (request-production-access).
- SES v2 `SendEmail` supports templated content (`Content.Template` with `TemplateName`, `TemplateData`) and
  `ConfigurationSetName` (API_SendEmail). SDK model: `ListManagementOptions(ContactListName, TopicName)`,
  operation `CreateContactList` exists.
- Event publishing from a configuration set to SNS (or the EventBridge default bus) (monitor-using-event-publishing,
  event-publishing-add-event-destination-sns).
- Resource types `AWS::SES::Template`, `AWS::SES::ConfigurationSet`, `AWS::SES::ConfigurationSetEventDestination`,
  `AWS::SES::ContactList` exist (`cfn-types-2026-10-10.json`).

Docs:
- https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html
- https://docs.aws.amazon.com/ses/latest/dg/send-personalized-email-api.html
- https://docs.aws.amazon.com/ses/latest/APIReference-V2/API_SendEmail.html
- https://docs.aws.amazon.com/ses/latest/APIReference-V2/API_CreateContactList.html
- https://docs.aws.amazon.com/ses/latest/APIReference-V2/API_ListManagementOptions.html
- https://docs.aws.amazon.com/ses/latest/dg/sending-email-subscription-management.html
- https://docs.aws.amazon.com/ses/latest/dg/using-configuration-sets.html
- https://docs.aws.amazon.com/ses/latest/dg/monitor-using-event-publishing.html
- https://docs.aws.amazon.com/ses/latest/dg/event-publishing-add-event-destination-sns.html
- https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ses-template.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ses-configurationset.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ses-configurationseteventdestination.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ses-contactlist.html

## D8. EventBridge Scheduler

Facts used: recurring `cron(minutes hours day-of-month month day-of-week year)` and one-time `at(yyyy-mm-ddThh:mm:ss)`
schedules, both in any time zone via `ScheduleExpressionTimezone` (schedule-types). SDK model `CreateSchedule`
members include `ActionAfterCompletion` (enum `NONE`, `DELETE`), `FlexibleTimeWindow`, `GroupName`, `Target`
(API_CreateSchedule, managing-schedule-delete). `AWS::Scheduler::Schedule` requires `FlexibleTimeWindow`,
`ScheduleExpression`, `Target`; `AWS::Scheduler::ScheduleGroup` exists (`cfn-types-2026-10-10.json`).

Docs:
- https://docs.aws.amazon.com/scheduler/latest/UserGuide/schedule-types.html
- https://docs.aws.amazon.com/scheduler/latest/UserGuide/managing-schedule-delete.html
- https://docs.aws.amazon.com/scheduler/latest/UserGuide/managing-targets-templated.html
- https://docs.aws.amazon.com/scheduler/latest/APIReference/API_CreateSchedule.html
- https://docs.aws.amazon.com/scheduler/latest/APIReference/API_DeleteSchedule.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-scheduler-schedule.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-scheduler-schedulegroup.html

## D9. Lambda, DynamoDB, S3, SNS, CloudWatch, Budgets

Facts used: Lambda runtime `python3.13` on Amazon Linux 2023, deprecation listed for Jun 30, 2029 (lambda-runtimes);
SNS and EventBridge invoke Lambda asynchronously with retries (invocation-async, with-sns). DynamoDB TTL deletes
expired items (TTL guide). All resource types confirmed with `describe-type`: `AWS::Lambda::Function`,
`AWS::DynamoDB::Table`, `AWS::S3::Bucket`, `AWS::SNS::Topic`, `AWS::SNS::TopicPolicy`, `AWS::SNS::Subscription`,
`AWS::CloudWatch::Alarm`, `AWS::Budgets::Budget`. The registry reports `NON_PROVISIONABLE` for
`AWS::Budgets::Budget`; that marks a legacy (non-registry) resource provider, not a type that cannot be used in a
template, so the budget `aurasenior-monthly` is in the SAM template (A9).

Docs:
- https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html
- https://docs.aws.amazon.com/lambda/latest/dg/invocation-async.html
- https://docs.aws.amazon.com/lambda/latest/dg/with-sns.html
- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-dynamodb-table.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-s3-bucket.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-sns-topicpolicy.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-cloudwatch-alarm.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-budgets-budget.html
- https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_CreateBudget.html
- https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html

## D10. Transcribe and the completion event

Facts used: Hindi `hi-IN`, English Indian `en-IN` and English US `en-US` support batch transcription
(supported-languages; SDK `LanguageCode` enum contains all three). Batch input formats include Ogg; SDK `MediaFormat`
enum includes `ogg` (how-input). `StartTranscriptionJob` takes `Media.MediaFileUri` (S3), `LanguageCode`,
`MediaFormat`, `OutputBucketName`, `OutputKey`. EventBridge event `source aws.transcribe`, detail-type
`Transcribe Job State Change`, `TranscriptionJobStatus` `COMPLETED` or `FAILED` (monitoring-events).
`AWS::Events::Rule` exists (`cfn-types-2026-10-10.json`). Word timings for Hindi Ogg are A4.

Docs:
- https://docs.aws.amazon.com/transcribe/latest/dg/supported-languages.html
- https://docs.aws.amazon.com/transcribe/latest/dg/how-input.html
- https://docs.aws.amazon.com/transcribe/latest/dg/how-it-works.html
- https://docs.aws.amazon.com/transcribe/latest/dg/monitoring-events.html
- https://docs.aws.amazon.com/transcribe/latest/APIReference/API_StartTranscriptionJob.html
- https://docs.aws.amazon.com/transcribe/latest/APIReference/API_GetTranscriptionJob.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-events-rule.html

## D11. Agent runtime: Lambda with the Converse API (decided 2026-10-10)

Decision: the agent loop runs in-process in the two Lambda functions and calls Bedrock `Converse` with `toolConfig`
and `guardrailConfig`; memory and trace are DynamoDB items. Bedrock AgentCore Runtime, Memory and Observability
are not used in Milestone 1. Full reasons in design section 4. In short: Converse tool use is proven here (D2);
AgentCore Runtime direct code deploy needs a Linux arm64 dependency zip in S3 and the runtime contract entrypoint,
plus an extra `InvokeAgentRuntime` hop, and has had no successful deploy yet; our own trace items give the demo trace
view directly; the Oct 15 target. The agent sits behind `AgentRunner`, so AgentCore can be added later without
changing tools or adapters (roadmap, only after all must-haves are verified by 2026-10-20).

Guardrail: `AWS::Bedrock::Guardrail` `aurasenior-safety` (required `Name`, `BlockedInputMessaging`,
`BlockedOutputsMessaging`) with denied topics for diagnosis and dose advice. With tools, a guardrail in
`guardrailConfig` does not evaluate tool call arguments (guardrails-use-converse-api), so the outbound guard in code
is the main wording control. SDK model: `Converse` input includes `toolConfig` and `guardrailConfig`.

Docs:
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-components.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-converse-api.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreateGuardrail.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrock-guardrail.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-service-contract.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html
- https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_InvokeAgentRuntime.html

## D12. IaC: AWS SAM (decided 2026-10-10)

Decision: one SAM template, deployed with `sam build` and `sam deploy --stack-name aurasenior --region us-east-1
--tags project=aurasenior --resolve-s3 --capabilities CAPABILITY_IAM`. Reasons in design section 5: Python only,
SAM CLI 1.165.0 installed, no CDK toolchain installed, every resource type confirmed by a real
`cloudformation describe-type` call under the project account (evidence `cfn-types-2026-10-10.json`: all found
except `AWS::SocialMessaging::WhatsAppBusinessAccount`). WhatsApp linking (no resource type), RCS testing agent
registration and test device (resource type `AWS::SMSVOICE::RcsAgent` exists, but the test device needs a phone
verification code entered by a person), template submission and per-household schedules are done by the owner or
by idempotent scripts. The budget is in the template.

Docs:
- https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/what-is-sam.html
- https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-resource-function.html
- https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-cli-command-reference-sam-deploy.html
- https://docs.aws.amazon.com/cdk/v2/guide/home.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_DescribeType.html

## D13. Open assumptions (checked during the build, result recorded here)

| ID | Assumption | How it is checked |
| --- | --- | --- |
| A1 | Polly `ogg_opus` sent as WhatsApp `audio` plays as a voice note | Live send to the owner's phone, screenshot of the message |
| A2 | SNS payload shapes for WhatsApp audio, template button taps, status | Save first real events to `docs/evidence/` and build parser tests from them |
| A3 | Templates accepted as UTILITY in Hindi and English; language codes | Template status after Meta review |
| A4 | Transcribe output for Hindi Ogg Opus has word start and end times | First real transcription job |
| A5 | RCS two-way payload field for `PostbackData` and opt-out keyword | First real tap on the test device |
| A6 | Nova 2 Lite Hindi replies are good enough | A Hindi speaker reviews 10 replies |
| A7 | SMS and RCS monthly spend limits in the project account, and whether simulator messages count | `DescribeSpendLimits` read under the project account |
| A8 | SES unsubscribe link via `ListManagementOptions` works in the sandbox | Send to a verified address |
| A9 | CloudFormation creates `AWS::Budgets::Budget` `aurasenior-monthly` with `budgets:ModifyBudget` on `aurasenior-*` | First `sam deploy` |
| A10 | Deploy user can create EventBridge rules | Simulate or deploy; see D14 |

## D14. Permissions needed beyond the `aurasenior-dev` policy

The deploy user `aws-ses-serv` has, per BUILD_BRIEF.md, full access to CloudFormation, Lambda, DynamoDB, S3, SES,
Bedrock, EventBridge Scheduler, CloudFront and IAM, plus `aurasenior-dev`. Compared with what the stack and scripts
call:

1. EventBridge rules (not Scheduler): `events:PutRule`, `events:PutTargets`, `events:DescribeRule`,
   `events:DeleteRule`, `events:RemoveTargets`, `events:TagResource` on `arn:aws:events:us-east-1:<account>:rule/aurasenior-*`.
   Needed for the Transcribe completion rule. Not in `aurasenior-dev`, and "EventBridge Scheduler full access" does
   not name `events:*`. Not yet verified whether another attached policy grants it; check before the first deploy
   with `iam simulate-principal-policy` (read-only). If missing, the owner approves this one statement.
2. Nothing else is expected: SNS, Logs, Alarms, Budgets are scoped to `aurasenior` names in `aurasenior-dev`;
   Transcribe, Polly, social-messaging and sms-voice are allowed there; IAM full access covers the function roles
   and `iam:PassRole` for the scheduler role.
3. Optional, owner only: Anthropic model use case form, if Claude models are wanted later (D2).
