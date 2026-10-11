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
  project venv. This confirms names and enums only, not runtime behaviour. The output is saved as
  `docs/evidence/sdk-shapes-2026-10-10.json` (operation, member and enum names, the `TranscriptionJobName`
  constraint, and the guardrail tier enum).
- IAM actions: the resource types each action supports were read from the public AWS Service Reference data
  (`https://servicereference.us-east-1.amazonaws.com/`, the machine-readable form of the Service Authorization
  Reference). Output: `docs/evidence/service-reference-actions-2026-10-10.txt`.
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
- Opt-in (Meta "Get opt-in for WhatsApp", updated Jun 16, 2026, read 2026-10-10): businesses are required to obtain
  opt-in before messaging people on WhatsApp; they may contact people if the person gave their number and the
  business received opt-in permission to receive messages from that business; the business must clearly state its
  name. Decision: opt-in is person-started (the person sends START, AuraSenior replies inside the window it opened
  and asks for YES). No opt-in template is sent. The `wa.me` prefilled link is a convenience only (A12).
- Template components (Meta "Components" page): a template has header, body, footer and buttons; only the body is
  required; variables need sample values at creation; a `QUICK_REPLY` button label is at most 25 characters. The
  page text read did not list an audio header, so no audio header is used: voice reaches a closed window through a
  quick-reply "Listen" tap that opens the window (design section 10).
- Template language codes (Meta "Supported languages"): Hindi `hi`, English (US) `en_US`, English (IND) `en_IN`.
  AuraSenior uses `hi` and `en_US`.
- SNS topic policy: the event destination page example allows `social-messaging.amazonaws.com` to `sns:Publish`
  and recommends `SourceAccount` and `SourceArn` conditions against the confused deputy problem.

Revision 3 facts (read 2026-10-11):
- Meta Graph API versions page: v20.0 released May 21, 2024, expiration September 24, 2026 (already expired);
  v25.0 released February 18, 2026, expiration July 29, 2028; v26.0 released July 29, 2026, expiration TBD (the
  newest). The botocore model types `SendWhatsAppMessage.metaApiVersion` as a plain string with no enum or pattern
  (`sdk-shapes-2026-10-11.json`). Decision: `[whatsapp] meta_api_version` in `config/app.toml`, default `v25.0`,
  because it has a published end date after the project timeline; `v26.0` can be set by config. Confirmed on the
  first live send (A16).
- Meta webhook reference for quick-reply button messages: the inbound object carries `button.payload` (shown as
  `<BUTTON_LABEL_TEXT>`, "Quick-reply button label text") and `context.id` ("WhatsApp message ID of the message
  containing the button the WhatsApp user tapped"). The old template-send guide URL now says "This page has
  moved"; a send-time per-button payload was not confirmed. Decision: static button labels, resolved through our
  own `MSG#<context.id>.ref`, falling back to the SMS digit rule (design section 12). How AWS wraps this webhook
  body in the SNS message is still A2 and A13.

Docs added in revision 3:
- https://developers.facebook.com/docs/graph-api/changelog/versions/
- https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/reference/messages/button/

Docs added in revision 2:
- https://developers.facebook.com/docs/whatsapp/overview/getting-opt-in/
- https://developers.facebook.com/docs/whatsapp/business-management-api/message-templates/components/
- https://developers.facebook.com/docs/whatsapp/business-management-api/message-templates/supported-languages/

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
- SNS topic policy for inbound RCS (rcs-inbound): a statement allowing `sms-voice.amazonaws.com` to `sns:Publish`
  on the topic ARN; the role-based alternative on the same page uses an `aws:SourceAccount` condition.
  AuraSenior adds `aws:SourceAccount` (the stack account) to the topic policy statement as well; if the first
  inbound test shows the condition blocks delivery, the condition is removed and that result is recorded here.
- Revision 3, rcs-testing (read 2026-10-11): a testing agent sends only to registered test devices; a device is
  added with `create-verified-destination-number --rcs-agent-id`, then gets a tester invitation from "RBM Tester
  Management" that must be accepted (up to 20 minutes to arrive; on iOS it may land in Unknown Senders); test
  devices are listed with `describe-verified-destination-numbers --filters Name=rcs-agent-id,...`; the testing agent
  supports two-way messaging "by sending messages with auto-response keywords"; testing messages are charged at
  standard RCS rates. The page does not say a test device can start a conversation before the agent sends.
  Decision: RCS opt-in is one business-started `optin_ask` after the device is verified, YES opts in (design
  section 14).
- Revision 3, test-phone-numbers (read 2026-10-11): simulator numbers stay inside AWS End User Messaging SMS and
  are not sent over the carrier network; a US origination simulator number can only send to destination simulator
  numbers of the same country; US success destination `+14254147755`, failure `+14254147167`. The page documents
  success and failure events for destinations, not inbound messages from them. Decision: inbound for the simulator
  record is injected with `python -m aurasenior.demo sim-inbound` and labelled simulated.
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
- Service Reference data (IAM actions and resource types for every service the functions call, fetched 2026-10-10):
  https://servicereference.us-east-1.amazonaws.com/
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
- Sender identity: `GetEmailIdentity` returns `VerifiedForSendingStatus` (boolean, "You can only send email from
  verified email addresses or domains") and `VerificationStatus` (`PENDING`, `SUCCESS`, `FAILED`,
  `TEMPORARY_FAILURE`, `NOT_STARTED`) (API_GetEmailIdentity; SDK output members in `sdk-shapes-2026-10-10.json`).
  `SendEmail` takes `FromEmailAddress`. Decision: stack parameter `SenderEmail`, verified by the owner;
  `post_deploy.py` reports unverified sender and recipients.
- SNS destination permission: the SNS event destination page gives a topic policy that allows
  `ses.amazonaws.com` to `sns:Publish` with `AWS:SourceAccount` and `AWS:SourceArn` (the configuration set ARN)
  conditions. The `aurasenior-email-events` topic policy uses this.

Docs added in revision 2:
- https://docs.aws.amazon.com/ses/latest/APIReference-V2/API_GetEmailIdentity.html

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
Execution role: Scheduler assumes an execution role (trust principal `scheduler.amazonaws.com`) to invoke the
target, and the docs recommend confused deputy safeguards (setting-up). A principal that creates schedules needs
`iam:PassRole` on that role with condition `iam:PassedToService = scheduler.amazonaws.com` (identity-based policy
examples). `scheduler:CreateSchedule` and `DeleteSchedule` support the `schedule` resource type (Service Reference).

Revision 3 (read 2026-10-11): `CreateSchedule` `Name` has maximum length 64 and pattern `[0-9a-zA-Z-_.]+`
(API_CreateSchedule page; botocore model min 1, max 64, `^[0-9a-zA-Z-_.]+$`, `sdk-shapes-2026-10-11.json`).
Design section 10 fixes every schedule name and its longest length (35).

Docs added in revision 2:
- https://docs.aws.amazon.com/scheduler/latest/UserGuide/setting-up.html
- https://docs.aws.amazon.com/scheduler/latest/UserGuide/security_iam_id-based-policy-examples.html

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

Lambda architecture (decided 2026-10-10): `arm64`. Lambda offers `arm64` (AWS Graviton2) and `x86_64`; the page
says arm64 can give better price and performance and that the package must be compatible (foundation-arch). The
package is pure Python plus boto3, so there are no native wheels to rebuild. `sam build` without a container is
enough for pure Python code.

Failed async events (revision 3, read 2026-10-11): `AWS::Lambda::EventInvokeConfig` has `DestinationConfig`,
`FunctionName`, `MaximumEventAgeInSeconds`, `MaximumRetryAttempts` and a required `Qualifier`, where `$LATEST`
names the unpublished version. Lambda can send records of asynchronous invocations to a standard SNS topic; the
function needs `sns:Publish`, and Lambda passes the invocation record as the message. The SAM
`EventInvokeConfig` property is described as "configuration options for asynchronous Lambda Alias or Version
invocations", so the plain CloudFormation resource with `Qualifier: $LATEST` is used. Topic
`aurasenior-failed-events`, owner email subscribed.

Revision 4 (read 2026-10-11; every URL below returned HTTP 200; types confirmed by a real
`cloudformation describe-type` call, evidence `cfn-types-2026-10-11.json`):
- Log groups: Lambda logs go by default to a log group named `/aws/lambda/<function-name>`, and the page lists
  `logs:CreateLogGroup` among the execution role permissions when Lambda creates it (monitoring-cloudwatchlogs).
  `AWS::Logs::LogGroup` has `LogGroupName` and `RetentionInDays` (no required properties; the schema enum for
  `RetentionInDays` contains 14). Decision: two log groups in the template, retention 14 days, each function
  `DependsOn` its group, roles without `logs:CreateLogGroup`.
- `AWS::Logs::MetricFilter`: required `FilterPattern`, `LogGroupName`, `MetricTransformations` (schema). JSON filter
  patterns are written `{ $.<field> = "<value>" }`, with a selector starting with `$.` and `=` or `!=` for strings
  (FilterAndPatternSyntax, example `{ $.eventType = "UpdateTrail" }`). Decision: `{ $.level = "ERROR" }` on both
  log groups, metric `AuraSenior/ErrorLogs`, value `1`.
- `AWS::CloudWatch::Alarm` `Metrics` takes `MetricDataQuery` items, each with either `Expression` or `MetricStat`
  but not both, and `ReturnData` true on only the one used (MetricDataQuery page); alarms can be based on a metric
  math expression (Create-alarm-on-metric-math-expression). An alarm action can notify an SNS topic, actions run
  only on a state change, CloudWatch does not validate that the action exists, and `SetAlarmState` can be used to
  test an alarm (CloudWatch_Alarms, reached from AlarmThatSendsEmail). Decision: alarm `aurasenior-errors` on
  `FILL(logs,0) + FILL(fin,0) + FILL(fsc,0) > 0` over 5 minutes, `AlarmActions` = `aurasenior-failed-events`.
- Topic policy for the alarm action: the SNS access policy examples page covers CloudWatch alarms publishing to a
  topic in a different account; neither page read says whether a same-account alarm needs a topic policy
  statement. Decision: keep the default topic policy on `aurasenior-failed-events` and test with `set-alarm-state`
  after the first deploy (A19). If the email does not arrive, add one Allow statement for the CloudWatch service
  principal after reading the principal name from the CloudWatch SNS permissions page, and record it here.
- `AWS::Lambda::Permission`: required `Action`, `FunctionName`, `Principal`; for a service principal the page
  says to use `SourceArn` or `SourceAccount` to limit who can invoke the function. It is generated by SAM for the
  event sources (D12), not written by hand.
- `AWS::CloudWatch::Alarm` re-read with `describe-type`: `Metrics`, `AlarmActions`, `TreatMissingData`,
  `ComparisonOperator`, `Threshold`, `EvaluationPeriods` are properties.

Revision 5 (read 2026-10-11, both URLs HTTP 200; passages saved verbatim in
`lambda-logging-and-createevent-docs-2026-10-11.txt`):
- Python logging (python-logging): "if your function outputs logs using Python print statements, Lambda can only
  send log outputs to CloudWatch Logs in plain text format"; the example log output shows the printed lines
  unchanged between the `START` and `END` lines; "Currently, the default log format for all Python runtimes is
  plain text"; the page then shows that records from the standard `logging` module (root logger, runtime handler)
  are captured in plain text with Lambda's own formatting. The logformat page: `LoggingConfig.LogFormat` is `Text`
  or `JSON`, and "If you don't specify a log format when you create a function, Lambda uses the default log format
  for the runtime version"; in JSON format, application log records carry `"timestamp"`, `"level"`, `"message"` and
  `"requestId"`.
- Decision: no `LoggingConfig` (plain text default). Our logger `aurasenior` has `propagate = False` and one
  `StreamHandler(sys.stdout)` writing `json.dumps` lines, so the runtime handler never adds its prefix and each
  stdout line is one JSON object for `{ $.level = "ERROR" }` (design 16). Checked live by A19 with a
  `selftest_error` invoke and `get-metric-data`. Fallback if the filter gets no data point: `LogFormat: JSON`, log
  through the standard logging module, and keep the filter on the documented `"level"` key.

Docs added in revision 5:
- https://docs.aws.amazon.com/lambda/latest/dg/python-logging.html
- https://docs.aws.amazon.com/lambda/latest/dg/monitoring-cloudwatchlogs-logformat.html
- https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_GetMetricData.html

Docs added in revision 4:
- https://docs.aws.amazon.com/lambda/latest/dg/monitoring-cloudwatchlogs.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-logs-loggroup.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-logs-metricfilter.html
- https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/FilterAndPatternSyntax.html
- https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/FilterAndPatternSyntaxForMetricFilters.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-cloudwatch-alarm-metricdataquery.html
- https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Create-alarm-on-metric-math-expression.html
- https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Alarms.html
- https://docs.aws.amazon.com/sns/latest/dg/sns-access-policy-use-cases.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-lambda-permission.html

Docs added in revision 3:
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-lambda-eventinvokeconfig.html
- https://docs.aws.amazon.com/lambda/latest/dg/invocation-async-retain-records.html
- https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-property-function-eventinvokeconfiguration.html

Docs added in revision 2:
- https://docs.aws.amazon.com/lambda/latest/dg/foundation-arch.html

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

Revision 2 facts:
- `TranscriptionJobName`: case sensitive, no spaces, unique in the account, length 1 to 200, pattern
  `^[0-9a-zA-Z._-]+` (API_StartTranscriptionJob; same min, max and pattern in the SDK model,
  `sdk-shapes-2026-10-10.json`). A WhatsApp message ID can contain `=` and is not used raw: the job name is
  `aurasenior-<hid>-<sha256(message ID) hex[:32]>`.
- The completion event carries `detail.TranscriptionJobName` and `detail.TranscriptionJobStatus` `COMPLETED` or
  `FAILED` (monitoring-events). EventBridge patterns support prefix matching on string values
  (eb-create-pattern-operators), so the rule matches `{"prefix": "aurasenior-"}` on the job name.
- IAM: the Transcribe identity-based policy examples give input bucket `s3:GetObject` (and `s3:ListBucket`) and
  output bucket `s3:PutObject`. `transcribe:StartTranscriptionJob` supports no resource type (Service Reference),
  so its resource is `*`.

Docs added in revision 2:
- https://docs.aws.amazon.com/transcribe/latest/dg/security_iam_id-based-policy-examples.html
- https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-create-pattern-operators.html

Docs:
- https://docs.aws.amazon.com/transcribe/latest/dg/supported-languages.html
- https://docs.aws.amazon.com/transcribe/latest/dg/how-input.html
- https://docs.aws.amazon.com/transcribe/latest/dg/how-it-works.html
- https://docs.aws.amazon.com/transcribe/latest/dg/monitoring-events.html
- https://docs.aws.amazon.com/transcribe/latest/APIReference/API_StartTranscriptionJob.html
- https://docs.aws.amazon.com/transcribe/latest/APIReference/API_GetTranscriptionJob.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-events-rule.html

## D11. Agent runtime: Lambda with the Converse API, plus AgentCore Memory (decided 2026-10-10, owner confirmed 2026-10-11)

Decision (owner confirmed 2026-10-11): the core agent loop runs in-process in the two Lambda functions and calls
Bedrock `Converse` with `toolConfig` and `guardrailConfig`; state and trace are DynamoDB items. Milestone 1 adds
Amazon Bedrock AgentCore Memory for the elder's long-term memory (routine, people, past check-ins) behind the
`MemoryStore` interface, with the DynamoDB memory as the automatic fallback (design sections 8.5 and 8.7).
Milestone 2, a separate run (target Oct 16-20), moves the agent loop onto AgentCore Runtime behind `AgentRunner`,
keeps Lambda as the event entry point, and adds AgentCore Observability if workable. AgentCore Runtime and
Observability are not used in Milestone 1. Reasons in design section 4: Converse tool use is proven here (D2);
AgentCore Runtime direct code deploy needs a Linux arm64 dependency zip in S3 and the runtime contract entrypoint,
plus an extra `InvokeAgentRuntime` hop, and has had no successful deploy yet; our own trace items give the demo
trace view directly; the Oct 15 target.

AgentCore Memory (read 2026-10-11; every URL below returned HTTP 200; SDK names from the botocore 1.43.111 model,
evidence `sdk-shapes-agentcore-memory-2026-10-11.json` and `agentcore-memory-shapes-2026-10-11.json`; resource type
from a real `describe-type`, `cfn-types-2026-10-11.json`; IAM from the Service Reference data,
`service-reference-arn-formats-2026-10-11.txt`):
- Terms (memory-terminology, memory-organization): an event is the unit of short-term memory, stored with
  `CreateEvent` and organized by `actorId` and `sessionId`; a memory record is a unit of long-term memory stored in
  a namespace; namespaces are hierarchical, should end with `/` to avoid prefix collisions, and may use the
  variables `{actorId}`, `{sessionId}` and `{memoryStrategyId}` (the page also writes it as strategyId). The
  semantic strategy's default namespace is `/strategy/{memoryStrategyId}/actors/{actorId}/`.
- Long-term memory generation is asynchronous and runs in the background after events are stored (memory types
  page). The semantic strategy extracts facts and processes only `USER` and `ASSISTANT` role messages
  (semantic-memory-strategy). The summary strategy writes condensed summaries of one session as XML with one
  `<topic>` tag per area, retrievable with `RetrieveMemoryRecords` (summary-strategy). Built-in strategies are
  semantic, user preference, summary and episodic, and can be combined in one memory (built-in-strategies); the CloudFormation schema has `SemanticMemoryStrategy`, `SummaryMemoryStrategy`,
  `UserPreferenceMemoryStrategy`, `CustomMemoryStrategy` and `EpisodicMemoryStrategy`, one per list item, each with
  required `Name` and optional `Namespaces`.
- Control plane `CreateMemory`: required `name` (pattern `[a-zA-Z][a-zA-Z0-9_]{0,47}`) and `eventExpiryDuration`
  (3 to 365 days); optional `memoryStrategies`, `memoryExecutionRoleArn`, `encryptionKeyArn`, `tags`. `GetMemory`
  takes `memoryId`. Neither is called by the functions; the stack creates the memory and `post_deploy.py` calls
  `GetMemory`.
- CloudFormation `AWS::BedrockAgentCore::Memory`: required `Name` (pattern `^[a-zA-Z][a-zA-Z0-9_]{0,47}$`,
  replacement on update) and `EventExpiryDuration` (integer 3 to 365, days); optional `MemoryStrategies`,
  `MemoryExecutionRoleArn`, `Tags`; `Ref` returns the memory ARN; `MemoryId` is a read-only attribute.
- Data plane `CreateEvent`: required `memoryId`, `actorId` (1 to 255), `eventTimestamp`, `payload`; optional
  `sessionId` (1 to 100, `[a-zA-Z0-9][a-zA-Z0-9-_]*`). Payload items are `conversational` (`content.text`, `role` one
  of `USER`, `ASSISTANT`, `TOOL`, `OTHER`), `json` or `blob`.
- Data plane `RetrieveMemoryRecords`: required `memoryId` and `searchCriteria` (`searchQuery` required, `topK`,
  `memoryStrategyId`, `metadataFilters`); `namespace` is a prefix filter, and either `namespace` or `namespacePath`
  is required. Output `memoryRecordSummaries` with `content`, `memoryRecordId`, `namespaces`, `score`.
- `CreateEvent` `clientToken` (revision 5, API_CreateEvent page, passage saved in
  `lambda-logging-and-createevent-docs-2026-10-11.txt`): "A unique, case-sensitive identifier to ensure that the
  operation completes no more than one time. If this token matches a previous request, AgentCore ignores the
  request, but does not return an error." Not required. The botocore 1.43.111 model marks it
  `idempotencyToken: true` with no length or pattern constraint (`sdk-createevent-clienttoken-2026-10-11.json`), so
  the SDK fills a random one when it is not given. The page does not say how long a token is remembered. Decision:
  `record_checkin` passes `sha256("checkin#<hid>#<pid>#<local_date>").hexdigest()[:32]` so a retried run or a second
  trigger on the same day writes one check-in line (design 8.7); `record_turn` and `remember` pass none.
- Read but not used in Milestone 1: `ListEvents`, `ListMemoryRecords`, `BatchCreateMemoryRecords`.
- IAM (Service Reference): `bedrock-agentcore:CreateEvent` and `bedrock-agentcore:RetrieveMemoryRecords` support
  the `memory` resource type, ARN `arn:${Partition}:bedrock-agentcore:${Region}:${Account}:memory/${MemoryId}`;
  `GetMemory` also `memory`; `CreateMemory` has no resource type (`*`). Function roles get only `CreateEvent` and
  `RetrieveMemoryRecords` on the memory ARN.
- Decision: memory `aurasenior_memory`, `EventExpiryDuration: 30`, semantic strategy `facts` on
  `/aurasenior/facts/{actorId}/` and summary strategy `checkins` on `/aurasenior/checkins/{actorId}/{sessionId}/`,
  no execution role (built-in strategies only, A18), stack condition `HasAgentCoreMemory` with parameter
  `AgentCoreMemory` (`on` by default), logical ID `AuraSeniorMemory`, conditional stack output `AgentCoreMemoryId`
  read by `post_deploy.py`. Elder only, enforced in `memory.build_store(person)`; DynamoDB fallback on any error;
  recalled records pass the `config/wording.toml` rule before they reach the prompt (design 8.5, 8.7).
- CloudFormation resource handler permissions for `AWS::BedrockAgentCore::Memory` (revision 5, real
  `describe-type`, `cfn-agentcore-memory-handlers-2026-10-11.json`): create `bedrock-agentcore:CreateMemory`,
  `GetMemory`, `TagResource`, `iam:PassRole` and KMS `DescribeKey`, `CreateGrant`, `Decrypt`,
  `GenerateDataKeyWithoutPlaintext`, `ReEncryptTo`, `ReEncryptFrom`, `GenerateDataKey`; update adds `UpdateMemory`,
  `UntagResource`, `ListTagsForResource`; delete `DeleteMemory`, `GetMemory` and KMS `Decrypt`, `DescribeKey`,
  `GenerateDataKey`; list `ListMemories`. These are checked for the deploy user in D14 item 7.

Docs added in revision 4 (AgentCore Memory):
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-terminology.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-organization.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-types.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-strategies.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/built-in-strategies.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/semantic-memory-strategy.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/summary-strategy.html
- https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_CreateMemory.html
- https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_GetMemory.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_CreateEvent.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_RetrieveMemoryRecords.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_ListEvents.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_ListMemoryRecords.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_BatchCreateMemoryRecords.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-memory.html
- Service Reference: https://servicereference.us-east-1.amazonaws.com/v1/bedrock-agentcore/bedrock-agentcore.json

Guardrail: `AWS::Bedrock::Guardrail` `aurasenior-safety` (required `Name`, `BlockedInputMessaging`,
`BlockedOutputsMessaging`) with denied topics for diagnosis and dose advice. With tools, a guardrail in
`guardrailConfig` does not evaluate tool results, tool definitions or tool call arguments; it evaluates input
prompts, system prompts and model response text (table on guardrails-use-converse-api). So the outbound guard in
code is the main wording control. SDK model: `Converse` input includes `toolConfig` and `guardrailConfig`.

Guardrail tier and Hindi (read 2026-10-10):
- Denied topics support safeguard tiers. Classic tier supports English, French and Spanish for denied topics.
  Standard tier lists Hindi as "Optimized and supported" and Hindi (Latin script) as "Supported" for denied topics
  (guardrails-supported-languages, guardrails-tiers).
- Standard tier requires the guardrail to use cross-Region inference, handled through a system-defined guardrail
  profile set on create or update (guardrails-tiers, guardrails-cross-region, CloudFormation
  `TopicsTierConfig.TierName` `CLASSIC` or `STANDARD`; `AWS::Bedrock::Guardrail` has `CrossRegionConfig`). SDK enum
  `GuardrailTopicsTierName` = `CLASSIC`, `STANDARD` (`sdk-shapes-2026-10-10.json`).
- Decision: `TopicPolicyConfig.TopicsTierConfig.TierName: STANDARD` and `CrossRegionConfig` with stack parameter
  `GuardrailProfileId`. The Hindi wording control is the outbound guard and `config/wording.toml` (required,
  tested), whatever the guardrail does.
- Revision 3 (read 2026-10-11, guardrails-cross-region-support): the US guardrail profile ID is `us.guardrail.v1:0`,
  ARN `arn:aws:bedrock:<source-region>:<account-id>:guardrail-profile/us.guardrail.v1:0`; from source us-east-1 it
  routes to us-east-1, us-east-2 and us-west-2. The guardrails-cross-region page says there is no extra cost, data
  stays in the US geography, and "You need specific permissions to use cross-Region guardrail inference" (that
  permissions page was not read yet, A14). The botocore model accepts either the ID or the ARN in
  `guardrailProfileIdentifier` (`sdk-shapes-2026-10-11.json`). `AWS::Bedrock::Guardrail` has a `CrossRegionConfig`
  property of type `GuardrailCrossRegionConfig`. Decision: parameter default `us.guardrail.v1:0`; condition
  `HasGuardrailProfile` (design section 5). With the parameter empty the guardrail uses `CLASSIC`, no
  `CrossRegionConfig`, and covers English only; the trace records `guardrail_mode`.
- `bedrock:ApplyGuardrail` supports resource types `guardrail` and `guardrail-profile` (Service Reference,
  `service-reference-actions-2026-10-10.txt`); both are granted to the function roles.

Owner confirmed: yes, 2026-10-11. Core agent on Lambda + Bedrock Converse. Milestone 1 adds Amazon Bedrock
AgentCore Memory for long-term memory behind the memory interface (DynamoDB memory as fallback). Milestone 2
(Oct 16-20, planned) moves the agent onto AgentCore Runtime behind AgentRunner. (Recorded by the design review
step on the orchestrator's instruction; also in BUILD_BRIEF.md "Agent runtime".)

Docs added in revision 3:
- https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-cross-region-support.html

Docs added in revision 2:
- https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-supported-languages.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-tiers.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-cross-region.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-bedrock-guardrail-topicpolicyconfig.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-bedrock-guardrail-topicstierconfig.html

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
--tags project=aurasenior --resolve-s3 --capabilities CAPABILITY_NAMED_IAM`. The roles have explicit `aurasenior-`
names, and "If you have IAM resources with custom names, you must specify CAPABILITY_NAMED_IAM" (API_CreateStack,
read 2026-10-10). Reasons for SAM in design section 5: Python only,
SAM CLI 1.165.0 installed, no CDK toolchain installed, every resource type confirmed by a real
`cloudformation describe-type` call under the project account (evidence `cfn-types-2026-10-10.json`: all found
except `AWS::SocialMessaging::WhatsAppBusinessAccount`). WhatsApp linking (no resource type), RCS testing agent
registration and test device (resource type `AWS::SMSVOICE::RcsAgent` exists, but the test device needs a phone
verification code entered by a person), template submission and per-household schedules are done by the owner or
by idempotent scripts. The budget is in the template.

Revision 3: optional resources and IAM statements use CloudFormation conditions (`HasWhatsApp`, `HasRcsAgent`,
`HasGuardrailProfile`) with `Fn::If` and `AWS::NoValue`, which the conditions page documents for removing a
property when a condition is false (conditions-section-structure, read 2026-10-11).
- https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/conditions-section-structure.html

Revision 4 (read 2026-10-11, HTTP 200): SAM event sources on `aurasenior-inbound`.
- SAM `SNS` event source: property `Topic` (the topic ARN); "SAM generates AWS::SNS::Subscription resource when
  this event type is set" (sam-property-function-sns).
- SAM `EventBridgeRule` event source: properties `Pattern`, `RuleName`, `Target`; SAM generates an
  `AWS::Events::Rule` and "also creates an AWS::Lambda::Permission resource, which is needed so the EventBridgeRule
  can call Lambda" (sam-property-function-eventbridgerule).
- The generated-resources page lists `AWS::Lambda::Permission` (invoke access) among the resources SAM generates
  for function event sources (sam-specification-generated-resources-function).
- Decision: three `Type: SNS` events and one `Type: EventBridgeRule` event (`RuleName: aurasenior-transcribe-done`,
  pattern from design 11.2); no hand-written permission or subscription. `aurasenior-scheduled` has no event
  source. `AWS::Lambda::Permission`, `AWS::Logs::LogGroup`, `AWS::Logs::MetricFilter` and
  `AWS::BedrockAgentCore::Memory` confirmed with `describe-type` (`cfn-types-2026-10-11.json`); the first build also
  runs `sam validate` and saves its output under `docs/evidence/`.
- https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-property-function-sns.html
- https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-property-function-eventbridgerule.html
- https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-specification-generated-resources-function.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-lambda-permission.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-logs-loggroup.html

Revision 5 (read 2026-10-11, HTTP 200): logical IDs. The parameters page: each parameter's logical ID "must be
alphanumeric and unique among all logical names within the template"; the resources page: resource logical names
"must be alphanumeric (A-Za-z0-9) and unique within the template". The parameter is `AgentCoreMemory`, so the
memory resource is `AuraSeniorMemory` and the conditional output is `AgentCoreMemoryId`
(`Fn::GetAtt AuraSeniorMemory.MemoryId`, condition `HasAgentCoreMemory`; the outputs page: "To associate a
condition with an output, define the condition in the Conditions section of the template").
- https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/parameters-section-structure.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/resources-section-structure.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/outputs-section-structure.html

Docs:
- https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/what-is-sam.html
- https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-resource-function.html
- https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-cli-command-reference-sam-deploy.html
- https://docs.aws.amazon.com/cdk/v2/guide/home.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_DescribeType.html
- https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_CreateStack.html

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
| A10 | Resolved 2026-10-11: deploy user can create EventBridge rules named `aurasenior-*` (`aurasenior-dev` v2, D14 item 1) | Confirmed again by the first `sam deploy` |
| A11 | `hi-IN` single-language jobs are accurate enough on Kamala's mixed Hindi and English | First real transcription |
| A12 | `https://wa.me/<number>?text=START` prefills START on the elder's phone (no doc read yet; the design does not depend on it) | Owner tries it once on the demo phone |
| A13 | Template quick-reply payload field in the inbound SNS event; Meta accepts the 6.3 bodies as UTILITY | First real tap; template status after review |
| A14 | Narrowed 2026-10-11: profile ID `us.guardrail.v1:0` is recorded (D11). Open: the IAM resources the cross-Region guardrail permissions page asks for, and that the guardrail works with the Nova 2 Lite profile in Converse | Read the permissions page before deploy; first deploy and first guarded call; on failure redeploy with `GuardrailProfileId` empty (Classic) and record it |
| A15 | `SendRcsMessage` with `FallbackConfiguration` to a number that is not a verified test device (the simulator record) is delivered as SMS from the fallback origination identity | First live RCS to SMS test, delivery events saved under `docs/evidence/`; if rejected, the simulator record uses `preferred_channel = sms` |
| A16 | `metaApiVersion` `v25.0` is accepted by `SendWhatsAppMessage` | First live send, response saved under `docs/evidence/` |
| A17 | A registered RCS test device's free-form text and Reply postbacks reach `aurasenior-sms-rcs-events` (rcs-testing mentions two-way testing "by sending messages with auto-response keywords", D6) | First YES from Rohan's phone, event saved under `docs/evidence/`; if only keywords arrive, Rohan's record switches to `preferred_channel = whatsapp` (data only) and the README says so |
| A18 | The stack creates `aurasenior_memory` with built-in semantic and summary strategies and no `MemoryExecutionRoleArn`; status reaches `ACTIVE`; extraction works on Hindi turns | First deploy and `post_deploy.py` `GetMemory`; live test in design 8.7 with output saved under `docs/evidence/`; on failure deploy with `AgentCoreMemory = off` and record why in D11 |
| A19 | A same-account CloudWatch alarm can publish to `aurasenior-failed-events` with the default topic policy, and the `ErrorLogs` metric filter matches our stdout JSON lines in the plain text log format | After the first deploy, `aws cloudwatch set-alarm-state --alarm-name aurasenior-errors --state-value ALARM --state-reason test` (owner email arrives; if not, add the CloudWatch Allow statement, D9); then invoke `aurasenior-scheduled` with `{"kind": "selftest_error"}`, `get-metric-data` shows `AuraSenior/ErrorLogs` = 1, alarm fires, email arrives; output in `docs/evidence/error-alarm-live-<date>.json`; if no data point, switch to `LogFormat: JSON` (D9) |

## D14. Permissions needed beyond the `aurasenior-dev` policy

The deploy user `aws-ses-serv` has, per BUILD_BRIEF.md, full access to CloudFormation, Lambda, DynamoDB, S3, SES,
Bedrock, EventBridge Scheduler, CloudFront and IAM, plus `aurasenior-dev`. Compared with what the stack and scripts
call:

1. EventBridge rules (not Scheduler): `events:PutRule`, `events:PutTargets`, `events:DescribeRule`,
   `events:DeleteRule`, `events:RemoveTargets`, `events:TagResource` on `arn:aws:events:us-east-1:<account>:rule/aurasenior-*`.
   Needed for the Transcribe completion rule. Granted 2026-10-11 (owner approved): `aurasenior-dev` v2 is the
   default version and has statement `EventBridgeRulesForAuraSenior` with `events:PutRule`, `PutTargets`,
   `DescribeRule`, `DeleteRule`, `RemoveTargets`, `TagResource`, `UntagResource`, `ListTargetsByRule` on
   `arn:aws:events:us-east-1:<account>:rule/aurasenior-*` (checked by the orchestrator with `iam get-policy-version`).
   The rule name `aurasenior-transcribe-done` is inside that resource pattern.
2. Nothing else is expected for the deploy user: SNS, Logs, Alarms, Budgets are scoped to `aurasenior` names in
   `aurasenior-dev`; Transcribe, Polly, social-messaging and sms-voice are allowed there; IAM full access covers
   creating the named function roles (`CAPABILITY_NAMED_IAM`) and `iam:PassRole` for them. Bedrock full access
   covers creating the guardrail with `CrossRegionConfig`; whether it also covers using a guardrail profile is part
   of A14.
3. For the post-deploy check: `ses:GetEmailIdentity` (SES full access covers it).
4. Function roles are created by the stack and are not permissions for the deploy user. Their exact actions and
   resources are in design section 5.1, checked against the Service Reference data
   (`service-reference-actions-2026-10-10.txt`): DynamoDB item actions on the table; S3 object get and put on the
   media bucket; `transcribe:StartTranscriptionJob` on `*` (no resource type) and `GetTranscriptionJob`;
   `bedrock:InvokeModel` on the profile and its model ARNs; `bedrock:ApplyGuardrail` on the guardrail and guardrail
   profile; `polly:SynthesizeSpeech` on `*` (only a lexicon resource type exists); `social-messaging` send and media
   actions on the phone number ID; `sms-voice:SendRcsMessage` and `SendTextMessage` on the RCS agent, phone number
   and configuration set; `ses:SendEmail` on identity, configuration set and templates; `scheduler:CreateSchedule`
   and `DeleteSchedule` on `schedule/aurasenior/*`; `iam:PassRole` on `aurasenior-scheduler` only; the scheduler
   role gets `lambda:InvokeFunction` on `aurasenior-scheduled` only.
5. Optional, owner only: Anthropic model use case form, if Claude models are wanted later (D2).
6. Revision 3 additions, none expected to need a new grant: `lambda:PutFunctionEventInvokeConfig` (CloudFormation
   creating `AWS::Lambda::EventInvokeConfig`, covered by Lambda full access); topic `aurasenior-failed-events` and
   its email subscription (SNS scoped to `aurasenior` names in `aurasenior-dev`); the admin CLI's
   `sms-voice:DescribeVerifiedDestinationNumbers` and `SendTextMessage`/`SendRcsMessage` for `rcs-ask` (sms-voice
   allowed in `aurasenior-dev`); `sns:Publish` to `aurasenior-sms-rcs-events` for `sim-inbound` (SNS scoped to
   `aurasenior`). Function roles additionally get `sns:Publish` on `aurasenior-failed-events` only. Any permission
   the cross-Region guardrail permissions page lists (A14) is checked with `iam simulate-principal-policy` before
   the first deploy; if missing, the owner approves it.
7. Revision 4 additions for the deploy user, none expected to need a new grant: log groups
   `/aws/lambda/aurasenior-*`, their metric filters and the `aurasenior-errors` alarm (Logs and alarms scoped to
   `aurasenior` names in `aurasenior-dev`); `AWS::BedrockAgentCore::Memory` `aurasenior_memory` and
   `bedrock-agentcore:GetMemory` for `post_deploy.py` (AgentCore allowed in `aurasenior-dev`). Before the first
   deploy, `iam simulate-principal-policy` is run for `logs:CreateLogGroup`, `logs:PutRetentionPolicy`,
   `logs:PutMetricFilter`, `cloudwatch:PutMetricAlarm` and every action in the create, update and delete handler
   lists of the `AWS::BedrockAgentCore::Memory` schema (D11, `cfn-agentcore-memory-handlers-2026-10-11.json`):
   `bedrock-agentcore:CreateMemory`, `GetMemory`, `UpdateMemory`, `DeleteMemory`, `TagResource`, `UntagResource`,
   `ListTagsForResource`, `ListMemories`, plus the KMS actions `DescribeKey`, `CreateGrant`, `Decrypt`,
   `GenerateDataKey`, `GenerateDataKeyWithoutPlaintext`, `ReEncryptTo`, `ReEncryptFrom`. Delete and tag actions
   matter for a stack rollback and for the `project=aurasenior` tag. The template sets no `EncryptionKeyArn` and no
   `MemoryExecutionRoleArn`, so the KMS actions and `iam:PassRole` are expected to be unused; they are simulated
   anyway and a deny on them is recorded but does not block the first deploy unless that deploy fails on one. Any
   other deny goes to the owner for approval before the deploy. D4 shows only `List*` AgentCore calls succeeding
   (and `ListRegistries` denied), so "AgentCore allowed in `aurasenior-dev`" is an expectation until this
   simulation runs; the output is saved as `docs/evidence/deploy-permissions-simulate-<date>.json`. Function roles
   additionally get `bedrock-agentcore:CreateEvent` and `RetrieveMemoryRecords` on the memory ARN only (design
   5.1).
