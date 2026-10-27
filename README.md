<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-dark.svg">
  <img src="docs/assets/logo-light.svg" alt="gitex" width="260">
</picture>

### Ask your Git history anything — and get answers with receipts.

**gitex** is a command-line tool that answers *what changed, when, who did it, and why* in plain
English or Turkish. Every claim is backed by a commit SHA, a date and, when available, the GitLab
merge request and issue behind it. Every reference is checked before it reaches you.

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![uv](https://img.shields.io/badge/packaged%20with-uv-DE5FE9?logo=astral&logoColor=white)](https://docs.astral.sh/uv/)
[![Ruff](https://img.shields.io/badge/lint-ruff-D7FF64?logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![mypy strict](https://img.shields.io/badge/types-mypy%20strict-2A6DB2)](https://mypy-lang.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-22C55E)](LICENSE)

[Quick start](#quick-start) ·
[Features](#features) ·
[How it works](#how-it-works) ·
[Configuration](#configuration) ·
[Evaluation](#evaluation) ·
[Türkçe](README.tr.md)

<br>

<img src="docs/assets/demo.svg" alt="gitex answering a question about rate limiting with verified commit sources" width="820">

<sub>Illustrative session against the repository bundled with the test suite.</sub>

</div>

---

## Why gitex?

`git log`, `git blame` and `git log -S` already hold the answers — but only if you know which
command to run, which path to look at and which string to search for. Code review context lives
somewhere else entirely, in merge requests and issues.

gitex puts an LLM in front of those tools and keeps it honest:

- **It searches like an engineer would.** Pickaxe for "when was X added", line history for "how did
  these lines evolve", blame for "who last touched this", full-text search for topics.
- **It cites everything.** Short SHA, date and author for every factual claim; `!MR` links when GitLab
  is configured.
- **It does not make things up.** Every SHA and MR in the answer is verified against the index. A
  fabricated reference is sent back to the model for correction once, and flagged
  `⚠ doğrulanamadı` (unverified) if it survives.
- **It runs where your code runs.** Local models through vLLM or Ollama, or Claude through the
  Anthropic API. Your history is indexed on disk; diffs are never stored.

<a id="features"></a>

## ✨ Features

<table>
<tr>
<td width="50%" valign="top">

**🔎 Git-native retrieval**<br>
Pickaxe (`-S` / `-G`), line-range history (`-L`), blame, rename-aware file history, tags and
branches containing a commit. Merges and empty repositories are handled correctly.

</td>
<td width="50%" valign="top">

**🧾 Verified citations**<br>
Every SHA and `!MR` in an answer is resolved against the index and Git. Unverifiable references
trigger a correction round, then an explicit warning.

</td>
</tr>
<tr>
<td valign="top">

**🌍 Bilingual by design**<br>
Answers in the language of the question. Search folds Turkish characters (`ödeme` ↔ `odeme`,
`kullanıcı` ↔ `kullanici`) and strips common suffixes.

</td>
<td valign="top">

**🦊 GitLab context**<br>
Merge requests, review comments with file and line, and closed or related issues. Incremental
sync, squash and merge commits mapped back to their MR.

</td>
</tr>
<tr>
<td valign="top">

**🧠 Any model, two modes**<br>
`agent` mode lets capable models call tools freely. `simple` mode does fixed retrieval and a single
call, so small local models still give grounded answers.

</td>
<td valign="top">

**🔐 Private by default**<br>
API keys, tokens, passwords, private keys, JWTs and connection strings are masked before anything
is sent. Excluded paths never leave your machine; diffs can be turned off entirely.

</td>
</tr>
<tr>
<td valign="top">

**⚡ Fast, incremental index**<br>
SQLite + FTS5 per repository. Only new commits are indexed; history rewritten by a rebase or
force-push is detected and cleaned up.

</td>
<td valign="top">

**📏 Measurable**<br>
A bundled evaluation set scores source accuracy and fabrication rate, so you can compare models
on the same questions.

</td>
</tr>
</table>

<a id="quick-start"></a>

## 🚀 Quick start

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/) and `git` on your `PATH`.

```bash
# Install the CLI (from a clone of this repository)
uv tool install .

# Inside any Git repository
gitex init        # creates .gitex/config.toml and adds .gitex/ to .gitignore
gitex index       # builds the local index (incremental from then on)
gitex ask "When was rate limiting added to login?"
```

Point gitex at a model before asking — see [Model providers](#model-providers). `ask` updates the
index automatically when it is missing or stale.

## 💬 Usage

### Ask anything

```bash
gitex ask "Why did payment/service.py change so much in the last 3 months?"
gitex ask "What did a1b2c3d do, which MR brought it in, and what came up in review?"
gitex ask "When did user deletion switch to soft-delete, and who did it?"
gitex ask "Login'deki rate limit ne zaman eklendi?"          # Turkish works too
```

Narrow the search, change the strategy or audit what is sent:

```bash
gitex ask "..." --path payment/ --since 2026-01-01 --until 2026-03-31
gitex ask "..." --mode simple          # fixed retrieval + one call, for small models
gitex ask "..." --show-context         # print everything sent to the LLM, before sending it
gitex ask "..." --json                 # answer + verified sources, machine-readable
```

### Commands

| Command | What it does | Needs an LLM |
|---|---|:---:|
| `gitex init` | Create `.gitex/config.toml`, add `.gitex/` to `.gitignore` | — |
| `gitex index [--rebuild]` | Index local Git history incrementally | — |
| `gitex sync [--full]` | Sync GitLab merge requests, review notes and issues | — |
| `gitex ask "question"` | Answer a question with cited sources | ✓ |
| `gitex explain <sha \| !MR>` | Explain a commit or a merge request | ✓ |
| `gitex when "expression"` | When an expression was added or removed (pickaxe) | — |
| `gitex file <path> [--llm]` | How a file evolved: authors, renames, activity | optional |
| `gitex chat` | Interactive session that keeps follow-up context | ✓ |
| `gitex status` | Index state, last sync and configuration summary | — |

Global option: `-C, --repo PATH` targets a repository in another directory.

> [!NOTE]
> Answers follow the language of your question. The CLI's own labels and messages (tables, progress,
> errors) are currently in Turkish.

<details>
<summary><b>Example: <code>gitex when</code> without any LLM</b></summary>

```text
$ gitex when "debug_dump"
                                         'debug_dump' geçmişi
┌────────────┬─────────┬──────────────┬────────────────────┬─────────────────────────────────────┬────┐
│ Tarih      │ SHA     │ Yazar        │ Ne oldu            │ Konu                                │ MR │
├────────────┼─────────┼──────────────┼────────────────────┼─────────────────────────────────────┼────┤
│ 2026-02-10 │ c9ea76b │ Mehmet Demir │ eklendi (+1/-0)    │ Geçici debug_dump fonksiyonu        │    │
│            │         │              │                    │ eklendi                             │    │
│ 2026-02-20 │ 7121f8f │ Mehmet Demir │ kaldırıldı (+0/-1) │ debug_dump kaldırıldı               │    │
└────────────┴─────────┴──────────────┴────────────────────┴─────────────────────────────────────┴────┘
İlk ortaya çıkış: c9ea76b 2026-02-10 Mehmet Demir — Geçici debug_dump fonksiyonu eklendi
Son durum: 7121f8f 2026-02-20 ile kaldırıldı.
```

</details>

<details>
<summary><b>Chat commands</b></summary>

| Command | Effect |
|---|---|
| `/yeni` | Start a fresh conversation |
| `/mod agent` · `/mod simple` | Switch mode mid-session |
| `/json` | Print the last answer with its sources as JSON |
| `/çık` · `Ctrl+D` | Quit |

</details>

<a id="how-it-works"></a>

## 🧭 How it works

```mermaid
flowchart LR
    Q([Question]) --> M{Mode}
    M -- agent --> L[LLM with tools]
    M -- simple --> R[Rule-based plan<br/>+ fixed retrieval]
    L <--> T[[Tools]]
    R --> T
    T --> G[(git CLI)]
    T --> I[(SQLite + FTS5<br/>.gitex/index.db)]
    T --> X[redact]
    X --> L
    R --> A[Single LLM call]
    L --> V{Citation check}
    A --> V
    V -- all verified --> O([Answer + sources])
    V -- unknown SHA / MR --> F[Correction round] --> V2{Still wrong?}
    V2 -- yes --> W([Answer with ⚠ flags])
    V2 -- no --> O
    S[gitex sync] --> GL[(GitLab API)] --> I
```

| Tool exposed to the model | Purpose |
|---|---|
| `search_commits` | Full-text search over commit messages, with path, author and date filters |
| `pickaxe` | Commits where a string or regex was added or removed (`git log -S` / `-G`) |
| `file_history` | A file's history, following renames |
| `line_history` | How a line range evolved (`git log -L`) |
| `blame` | Which commit last touched each line |
| `get_commit` | Metadata, changed files, tags and branches, linked MR and a trimmed diff |
| `list_paths` | Find the right path by glob or substring |
| `search_mrs` · `get_mr` | Merge requests, review notes and issues — only offered when GitLab is configured |

Tool outputs are plain text sized to a character budget; truncation is always stated, so the model
knows to narrow its query.

<a id="configuration"></a>

## ⚙️ Configuration

gitex reads, in increasing order of precedence:

1. `~/.config/gitex/config.toml` (or the path in `GITEX_CONFIG`)
2. `<repo>/.gitex/config.toml`
3. Environment variables: `GITEX_LLM_PROVIDER`, `GITEX_LLM_MODEL`, `GITEX_LLM_BASE_URL`,
   `GITEX_LLM_MODE`, `GITEX_GITLAB_URL`, `GITEX_GITLAB_PROJECT`

> [!IMPORTANT]
> Secrets never go into config files. The LLM key is read from the variable named by
> `llm.api_key_env` (default `GITEX_LLM_API_KEY`); the GitLab token from `GITEX_GITLAB_TOKEN`.

```toml
[llm]
provider = "openai_compat"        # or "anthropic"
model = "qwen2.5-7b-instruct"
base_url = "http://localhost:8000/v1"
api_key_env = "GITEX_LLM_API_KEY"
mode = "agent"                    # "agent" (tool use) or "simple"
max_tool_calls = 12
temperature = 0.1                 # sent to openai_compat only

[privacy]
send_diffs = true                 # false: only metadata and messages reach the LLM
max_diff_chars = 12000
exclude_paths = ["*.env", "*.pem", "*.key", "secrets/**", "*.lock"]

[gitlab]
url = "https://gitlab.com"
project = "group/project"
```

<details>
<summary><b>All <code>[llm]</code> options</b></summary>

| Key | Default | Description |
|---|---|---|
| `provider` | `openai_compat` | `openai_compat` (vLLM, Ollama, OpenAI) or `anthropic` |
| `model` | `qwen2.5-7b-instruct` | Model name as the endpoint expects it |
| `base_url` | — | Required for `openai_compat` |
| `api_key_env` | `GITEX_LLM_API_KEY` | Name of the environment variable holding the key |
| `mode` | `agent` | `agent` or `simple` |
| `max_tool_calls` | `12` | Tool-call budget per question in agent mode |
| `temperature` | `0.1` | Sent to `openai_compat` only |
| `max_tokens` | provider default | 2048 for `openai_compat`, 16000 for `anthropic` |
| `timeout` | `120` | Request timeout in seconds |
| `tool_output_chars` | `8000` | Character budget for a single tool output |
| `context_chars` | `40000` | Total context budget in simple mode |
| `simple_top_n` | `6` | Commits whose details are included in simple mode |
| `anthropic_fallbacks` | `true` | Let the Claude API retry a refused request on a fallback model |

</details>

<a id="model-providers"></a>

### Model providers

<details open>
<summary><b>vLLM</b></summary>

```bash
vllm serve Qwen/Qwen2.5-7B-Instruct --enable-auto-tool-choice --tool-call-parser hermes
```

```toml
[llm]
provider = "openai_compat"
model = "Qwen/Qwen2.5-7B-Instruct"
base_url = "http://localhost:8000/v1"
mode = "agent"
```

Tool calling needs `--enable-auto-tool-choice` and a parser that matches the model. Without them,
use `mode = "simple"`.

</details>

<details>
<summary><b>Ollama</b></summary>

```toml
[llm]
provider = "openai_compat"
model = "qwen2.5:7b"
base_url = "http://localhost:11434/v1"
mode = "simple"                   # usually more accurate on small models
```

</details>

<details>
<summary><b>Claude (Anthropic API)</b></summary>

```toml
[llm]
provider = "anthropic"
model = "claude-opus-5-5"
api_key_env = "ANTHROPIC_API_KEY"
mode = "agent"
```

If the Claude API declines a request, it is retried server-side on a fallback model
(`anthropic_fallbacks = true` by default; set it to `false` to opt out).

</details>

<details>
<summary><b>OpenAI</b></summary>

```toml
[llm]
provider = "openai_compat"
model = "<model-name>"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
```

</details>

### Agent or simple?

| | `agent` | `simple` |
|---|---|---|
| How it retrieves | The model chooses tools in a loop | Keywords, code terms, paths and dates extracted by rules (one small LLM call if rules find nothing) |
| LLM calls | Several, bounded by `max_tool_calls` | One (two at most) |
| Best for | Claude, larger open models with solid tool calling | Small local models, servers without tool calling |
| Follow-ups in `chat` | Full conversation history | Previous turns included as text |

## 🦊 GitLab integration

```bash
export GITEX_GITLAB_TOKEN=...      # a token with read_api scope
gitex sync                          # incremental from the last sync; --full to start over
```

- Syncs merged and open merge requests, non-system review notes (with file and line for diff
  comments), and issues an MR closes or relates to.
- Incremental by `updated_after`; MRs closed without merging are removed from the index.
- Honors `Retry-After` on HTTP 429 and paginates automatically.
- Maps commits to MRs through the MR's commits, `merge_commit_sha` and `squash_commit_sha`.

Without a `[gitlab]` section gitex works fully on local Git, and the MR tools are never offered to
the model.

## 🔐 Privacy & security

| Safeguard | Detail |
|---|---|
| No diffs at rest | The index stores metadata and messages; diffs are read from Git on demand |
| Secret masking | Keys, tokens, passwords, private keys, JWTs and connection strings become `[REDACTED]` |
| Excluded paths | Files matching `exclude_paths` never have their diff sent |
| Metadata-only mode | `send_diffs = false` removes diffs and code lines from every tool |
| Audit before sending | `--show-context` prints the exact messages before the request is made |
| No secrets on disk | Keys and tokens are read only from environment variables |

<a id="evaluation"></a>

## 📊 Evaluation

The repository ships with a deterministic fixture repository and 19 questions in English and
Turkish, including two with no answer, to catch models that invent one.

```bash
uv run python -m gitex.evals                                     # model from your config
uv run python -m gitex.evals --provider anthropic --model claude-opus-5-5
uv run python -m gitex.evals --mode simple --model qwen2.5:7b \
    --base-url http://localhost:11434/v1 --output report.json
```

| Metric | Meaning |
|---|---|
| Source recall | Share of expected commits cited as verified sources |
| Full-hit rate | Questions where every expected commit was cited |
| Fabricated-reference rate | Unverifiable references ÷ all references in answers |
| Not-found accuracy | Unanswerable questions answered "not found" without a SHA |
| Text match | Expected facts (names, dates, versions) present in the answer |

Questions live in [`evals/questions.toml`](evals/questions.toml).

## 🗂 Project layout

```text
src/gitex/
├── cli.py            Typer commands
├── config.py         TOML + environment loading, validation (pydantic)
├── session.py        Question/answer session shared by ask, explain and chat
├── redact.py         Secret masking
├── git/              git CLI reader and data models
├── index/            SQLite schema and migrations, incremental indexer, search
├── gitlab/           python-gitlab wrapper, incremental sync
├── llm/              Provider protocol, OpenAI-compatible and Anthropic adapters
├── agent/            Tools, tool-use loop, simple mode, prompts, citation checks
└── evals/            Fixture repository builder and evaluation runner
```

Design decisions and the reasoning behind each dependency are recorded in
[`docs/decisions.md`](docs/decisions.md) (Turkish).

## 🛠 Development

```bash
uv sync
uv run pytest                                      # no test touches the network
uv run ruff check . && uv run ruff format --check .
uv run mypy                                        # strict
```

CI (`.gitlab-ci.yml`) runs lint, type checking and tests on every push.

## 🗺 Roadmap

- [ ] Hybrid search: FTS5 + embeddings with `sqlite-vec` (the search interface is already abstracted for it)
- [ ] MCP server built on the `--json` output
- [ ] Streaming answers in `ask` and `chat`
- [ ] GitHub pull requests alongside GitLab merge requests

## 📄 License

[MIT](LICENSE) · Changes are tracked in [CHANGELOG.md](CHANGELOG.md).
