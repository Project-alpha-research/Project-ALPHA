---
owner: project layer
sources:
  - docs/reference/project/owner-decisions.md
  - docs/reference/project/owner-decisions-2.md
  - docs/reference/project/owner-decisions-3.md
  - docs/reference/project/owner-decisions-4.md
  - docs/reference/project/owner-decisions-5.md
verified: 6fa12eaf708b05f2
---

# Owner decisions by topic

Find a decision by its topic. The middle column is the gist; the entry has the owner's words, the reason and what it governs.
Five volumes hold the log: [volume 1](owner-decisions.md),
[volume 2](owner-decisions-2.md), [volume 3](owner-decisions-3.md), [volume 4](owner-decisions-4.md) and
[volume 5](owner-decisions-5.md) (the newest; new entries go there). When an entry is added, add its row here.

## The project and its purpose

| Topic | Decided | Entry |
|---|---|---|
| What ALPHA is for, in the owner's words | ALPHA is a general tool; test ideas are throwaway proofs that the system works | [vol. 4][e1] |
| Private means personal | Private means for the owner alone, not to sell | [vol. 1][e2] |
| Licences are never a criterion | Never judge a library, model or data source on its licence | [vol. 3][e3] |
| Precision and live capital | Strategies will one day hold live capital, so precision is the bar | [vol. 1][e4] |
| Live trading deferred | Live trading waits until the whole system is built and proven | [vol. 1][e5] |
| Never high-frequency trading | A standing rule: swing trading mostly, some intraday, never high-frequency | [vol. 2][e6] |
| The retail trader's fit is the design brief | Design for a retail swing trader: long holds, small size, products funds cannot trade | [vol. 2][e7] |
| What production grade means | Prompt an AI and the whole pipeline works; a UI to see it; every overfit test available | [vol. 3][e8] |
| Test ideas are system tests | Until production grade, a run is judged by what it shows about the system, not the idea | [vol. 3][e9] |
| The agent is a collaborator, never a black box | Agent proposes and discusses with the user; steps and reasons shown; labels over refusals | [vol. 5][e10] |
| The AI is a research partner | The AI suggests tests, data and how to read results, not just follow instructions | [vol. 3][e11] |
| Fewer strict rules, no daily-only rule | Any idea at any timeframe goes through the pipeline; prefer labels and warnings to refusals | [vol. 3][e12] |

## RD-Agent

| Topic | Decided | Entry |
|---|---|---|
| RD-Agent is a key component | RD-Agent is core; never shelve it because it is not installed | [vol. 1][e13] |
| First goal: one real loop | First goal after the clean-up: one real RD-Agent loop, propose to judge | [vol. 2][e14] |
| Models, spending limit, DeepSeek | About USD 50 a month for API credits, only if Codex cannot serve RD-Agent | [vol. 1][e15] |
| DeepSeek through OpenRouter | DeepSeek flash via OpenRouter; caps USD 10 a run, 50 a month; Codex is the fallback | [vol. 2][e16] |
| Adopt everything RD-Agent has, memory first | Use everything RD-Agent has, memory of past runs first; it stays an engine | [vol. 3][e17] |
| Judge: spread check, families, universe | Top third must beat bottom third before costs; 3 failures close a family; universe file | [vol. 4][e18] |
| Stand-in user while ideas are throwaway tests | A stand-in may answer RD-Agent's proposals, labelled, and never for a real approval | [vol. 5][e19] |
| One-shot confirmation on reserved data | One confirmation each on reserved data; ten slots, each needs the owner's yes; not built | [vol. 5][e20] |
| Confirmation, build sandbox, subject matter | One-shot confirmation (not built); a limited Codex sandbox widening; named Codex models | [vol. 4][e21] |
| RD-Agent chooses tests but does not write them | Recommended, not confirmed: RD-Agent picks tests, never writes them | [vol. 5][e22] |
| The orchestrator's plan: discussable RD-Agent | Paths are ways of working; later RD-Agent shows each refusal's reason and discusses ideas | [vol. 4][e23] |

## Tools, Kronos, Monte Carlo

| Topic | Decided | Entry |
|---|---|---|
| What Kronos is for | A flexible research tool; powers one Monte Carlo family; not yet tied to signals or risk; needs validation | [vol. 1][e24] |
| Kronos, Monte Carlos, lookalike and pattern tools | Never slimming targets; a tool not yet wired in is owed wiring, not deletion | [vol. 5][e25] |
| The toolbox is an open catalogue | One registry to describe, find and run a test; grows to hundreds; every run recorded | [vol. 5][e26] |
| Keep ALPHA slim continuously | Each change deletes what it replaces; regular slimming audits; report the line-count trend | [vol. 5][e27] |
| Thin ALPHA dramatically | Cut bloat: free exploration, owner approval only before paper or live; RD-Agent and Qlib are the proven core | [vol. 2][e28] |
| Always slimmer | Always refactor and thin out; replace a removed tool with something slimmer | [vol. 3][e29] |
| Glue in more outside projects | Glue in proven outside projects the way Qlib and RD-Agent are used; judge fit, upkeep and code deleted | [vol. 3][e30] |

## The screen

| Topic | Decided | Entry |
|---|---|---|
| Keep the user interface | Keep the UI: the owner is not a coder and understands the project through it | [vol. 2][e31] |
| Charts with text, quant style, finished later | Charts with text, in a quant style, finished later | [vol. 2][e32] |
| Not all black; UI design waits | Light default, charts may be dark, theme switch; UI design deferred; journey layout reused | [vol. 5][e33] |
| The idea-journey layout is approved | Numbered steps, who acted, one paragraph, three numbers, one chart; reused for other result views | [vol. 5][e34] |
| Working order: golden paths 1 and 2 first | Setup Lab, then the rule-test report screen first; RD-Agent work limited meanwhile | [vol. 4][e35] |

## Data and health

| Topic | Decided | Entry |
|---|---|---|
| Free real data on the Dell | Download free real data on the Dell now (Yahoo, Stooq, crypto); paid providers wait for the Mac | [vol. 2][e36] |
| Free stock prices until the Mac | Free stock prices from Alpaca's free plan until the Mac | [vol. 2][e37] |
| One data health report | Queued, not built when asked; step 1 (`alpha data health`) is built; rule tests and setups now carry the verdict | [vol. 5][e38] |
| A weekly automatic health check | Weekly check: refresh status, list stale documents, open small clean-ups; never merges | [vol. 2][e39] |

## How work is done

| Topic | Decided | Entry |
|---|---|---|
| Codex builds, Claude plans | Codex implements; Claude plans and decides | [vol. 1][e40] |
| Codex builds with the 6.2 models | Codex builds with the 6.2 models; Claude plans, orchestrates, reviews | [vol. 5][e41] |
| Who merges; agents decide routine matters | Agents merge routine pull requests; approvals, branch protection, credentials stay with owner | [vol. 1][e42] |
| The orchestrating session delegates | The session the owner talks to delegates; every agent names its model; Codex first | [vol. 3][e43] |
| Approvals follow code structure | An approval survives comments and formatting and dies on any behaviour change | [vol. 2][e44] |
| What the file system is for | A reader starting at CLAUDE.md can learn each part's purpose, reason, plan, place and limits | [vol. 1][e45] |
| The file system is kept up to date | Every change updates the file system in the same piece of work | [vol. 3][e46] |
| Documents can never be stale | Staleness is detected by fingerprints and the gate refuses work; an AI still re-reads and fixes | [vol. 3][e47] |
| A directional statement lands in the log | A directional statement lands in the log in the same change | [vol. 5][e48] |
| Open owner decisions in one place (N1 to N6) | Open owner decisions N1 to N6 are listed in one place | [vol. 4][e49] |
| Writing style for text the owner reads | Answer first, short sentences, one name for one thing; write less too | [vol. 5][e50] |

[e1]: owner-decisions-4.md#2026-11-18-what-the-owner-said-about-the-purpose-of-alpha
[e2]: owner-decisions.md#2026-11-14-private-means-personal
[e3]: owner-decisions-3.md#2026-11-16-licences-are-never-a-criterion-for-outside-projects
[e4]: owner-decisions.md#2026-11-14-precision-and-live-capital
[e5]: owner-decisions.md#2026-11-14-live-trading-is-deferred
[e6]: owner-decisions-2.md#2026-11-14-never-high-frequency-trading
[e7]: owner-decisions-2.md#2026-11-14-the-retail-traders-fit-is-the-design-brief
[e8]: owner-decisions-3.md#2026-11-15-what-production-grade-means
[e9]: owner-decisions-3.md#2026-11-15-test-ideas-are-system-tests-until-alpha-is-production-grade
[e10]: owner-decisions-5.md#2026-11-18-the-agent-is-a-collaborator-never-a-black-box
[e11]: owner-decisions-3.md#2026-11-15-the-ai-must-be-a-research-partner-not-an-instruction-follower
[e12]: owner-decisions-3.md#2026-11-15-no-daily-only-rule-fewer-strict-rules
[e13]: owner-decisions.md#2026-11-14-rd-agent-is-a-key-component
[e14]: owner-decisions-2.md#2026-11-14-first-goal-one-real-rd-agent-loop
[e15]: owner-decisions.md#2026-11-14-api-spending-limit-for-rd-agents-models
[e16]: owner-decisions-2.md#2026-11-14-deepseek-through-openrouter-for-rd-agent
[e17]: owner-decisions-3.md#2026-11-15-adopt-everything-rd-agent-has-memory-first
[e18]: owner-decisions-4.md#2026-11-16-rd-agent-judge-spread-check-idea-families-universe-file-call-time-limit
[e19]: owner-decisions-5.md#2026-11-18-stand-in-user-while-ideas-are-throwaway-tests
[e20]: owner-decisions-5.md#2026-11-18-one-shot-confirmation-of-shortlisted-factors-on-reserved-data-approved-not-built
[e21]: owner-decisions-4.md#2026-11-18-owner-decisions-on-confirmation-the-build-sandbox-and-rd-agent-subject-matter
[e22]: owner-decisions-5.md#2026-11-18-rd-agent-may-choose-tests-but-not-write-them-recommendation-not-yet-confirmed
[e23]: owner-decisions-4.md#2026-11-18-orchestrators-plan-the-paths-are-ways-of-working-and-rd-agent-becomes-discussable
[e24]: owner-decisions.md#2026-11-14-what-kronos-is-for
[e25]: owner-decisions-5.md#2026-11-18-kronos-the-four-monte-carlos-lookalike-and-pattern-tools-are-rd-agents-toolbox
[e26]: owner-decisions-5.md#2026-11-18-the-toolbox-is-an-open-catalogue-meant-to-grow-to-hundreds-of-tests
[e27]: owner-decisions-5.md#2026-11-18-keep-alpha-slim-continuously
[e28]: owner-decisions-2.md#2026-11-14-thin-alpha-dramatically-rd-agent-and-qlib-are-the-proven-core
[e29]: owner-decisions-3.md#2026-11-15-always-slimmer
[e30]: owner-decisions-3.md#2026-11-15-glue-in-more-proven-open-source-projects
[e31]: owner-decisions-2.md#2026-11-14-keep-the-user-interface
[e32]: owner-decisions-2.md#2026-11-14-the-interface-shows-charts-with-text-in-a-quant-style-and-is-finished-later
[e33]: owner-decisions-5.md#2026-11-18-the-workstation-must-not-be-all-black-ui-design-waits
[e34]: owner-decisions-5.md#2026-11-18-the-idea-journey-layout-is-approved
[e35]: owner-decisions-4.md#2026-11-18-working-order-golden-paths-1-and-2-reach-the-screen-first
[e36]: owner-decisions-2.md#2026-11-14-free-real-data-on-the-dell-now
[e37]: owner-decisions-2.md#2026-11-14-free-stock-prices-from-a-free-service-until-the-mac
[e38]: owner-decisions-5.md#2026-11-18-request-one-data-health-report
[e39]: owner-decisions-2.md#2026-11-14-a-weekly-automatic-health-check
[e40]: owner-decisions.md#2026-11-14-codex-builds-claude-plans
[e41]: owner-decisions-5.md#2026-11-18-codex-builds-with-the-62-models-claude-orchestrates-and-reviews
[e42]: owner-decisions.md#2026-11-14-agents-merge-and-decide-routine-matters
[e43]: owner-decisions-3.md#2026-11-15-the-orchestrating-session-delegates-every-agent-names-its-model
[e44]: owner-decisions-2.md#2026-11-14-approvals-follow-code-structure-not-exact-bytes
[e45]: owner-decisions.md#2026-11-14-what-the-file-system-is-for
[e46]: owner-decisions-3.md#2026-11-15-the-file-system-is-always-kept-up-to-date
[e47]: owner-decisions-3.md#2026-11-15-documents-can-never-be-stale-enforced-by-the-system-not-by-an-ais-memory
[e48]: owner-decisions-5.md#2026-11-18-rule-a-directional-statement-lands-in-this-log-in-the-same-change
[e49]: owner-decisions-4.md#2026-11-18-open-owner-decisions-listed-in-one-place
[e50]: owner-decisions-5.md#2026-11-18-text-the-owner-reads-follows-simplified-technical-english
