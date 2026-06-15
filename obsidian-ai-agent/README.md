# Obsidian AI Agent

Autonomous knowledge management assistant for Obsidian vaults.

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

```bash
# Inline data
obsidian-agent create -t "Project" -d "Fix auth bug on the backend"

# Interactive multiline editor (Alt+Enter to submit)
obsidian-agent create -t "Meeting" --interactive

# Pipe via stdin
echo "Onboarding call with Alice" | obsidian-agent create -t "Meeting"

# Use OpenAI instead of the default provider
obsidian-agent create -t "Project" -d "Deploy infra" -p openai

# Utility commands
obsidian-agent list-templates
obsidian-agent config-info
```

## Configuration

Copy `.env.example` to `.env` and fill in your values.

| Variable | Default | Description |
|---|---|---|
| `OBSIDIAN_VAULT_PATH` | `~/ObsidianVault` | Root of your vault |
| `TEMPLATES_PATH` | `<vault>/Templates` | Where `.md` templates live |
| `OUTPUT_PATH` | `<vault>/Generated` | Where generated notes are saved |
| `DEFAULT_AI_PROVIDER` | `ollama` | `ollama` or `openai` |
| `OPENAI_API_KEY` | — | Required when using OpenAI |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model name |
| `OLLAMA_HOST` | `http://localhost:11434` | Local Ollama instance URL |
| `OLLAMA_MODEL` | `llama3` | Ollama model name |