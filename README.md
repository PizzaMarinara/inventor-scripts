# inventor-scripts

An AI-powered automation toolkit for Autodesk Inventor. Extract parameters, BOMs and properties from `.ipt`/`.iam`/`.ipn` files, modify them programmatically, and instruct the system in plain language via an AI agent.

## Prerequisites

- Windows OS (COM/pywin32 is Windows-only)
- Autodesk Inventor installed
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Installation

```bash
git clone <repo-url>
cd inventor-scripts
pip install -e ".[dev]"   # or: uv pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and fill in your Anthropic API key:
```
ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

Drop your Inventor files in `input/`. Output lands in `output/`.

### Extract data from a file

```bash
python main.py extract input/assembly.iam
python main.py extract input/assembly.iam --format csv
python main.py extract input/assembly.iam --format both
```

### Modify parameters directly

```bash
python main.py modify input/part.ipt --changes '{"Width": "150 mm"}'
python main.py modify input/part.ipt --changes '{"Width": "150 mm", "Height": "75 mm"}' --output part_v2.ipt
```

### Ask the AI agent

```bash
# With a specific file
python main.py ask "describe this model and list all parameters" --file input/assembly.iam

# Using the document already open in Inventor
python main.py ask "make the CylinderLength parameter 200mm longer than its current value, save as cylinder_extended.iam, and open it"
```

The agent will:
1. Call `describe_model` to understand the document
2. Identify the relevant parameters
3. Apply the changes
4. Save the modified file to `output/`
5. Open it in Inventor for verification

## Running Tests

```bash
# Non-COM tests (runs anywhere)
pytest -m "not inventor"

# All tests (requires Inventor on Windows)
pytest
```

## Adding a New LLM Provider

1. Create a class in `agent/llm.py` that satisfies the `LLMClient` protocol
2. Implement `chat(messages, tools, system) -> LLMResponse`
3. Populate `response.assistant_content` from your provider's response (used by the agent loop for multi-turn history)
4. Pass your client to `ClaudeLLMClient` → `AgentLoop` in `main.py`

## Project Structure

```
inventor-scripts/
├── inventor_api.py     # COM connection: attach to running or launch Inventor
├── extract.py          # Extract properties, parameters, BOM from any doc type
├── modify.py           # Modify parameters, save-as, open in Inventor
├── utils.py            # JSON/CSV export, directory helpers
├── agent/
│   ├── tools.py        # Tool schemas (provider-agnostic)
│   ├── llm.py          # LLM client (Claude default, swappable)
│   ├── describe.py     # describe_model() — semantic summary for the agent
│   └── loop.py         # Agent reasoning loop
├── main.py             # CLI: extract / modify / ask
├── input/              # Drop .ipt/.iam/.ipn files here
└── output/             # Extracted data + modified files
```

## Known Limitations

- **Windows only** — pywin32 COM is required; all Inventor interaction is Windows-native
- **Parameter naming** — cryptic names like `d37` reduce agent accuracy; use named parameters in Inventor for best results
- **BOM deduplication** — `extract_bom` iterates all BOM views; duplicate rows may appear for assemblies with multiple views
- **save_as behaviour** — `save_copy_as=False` (default) remaps the document object to the new path; use `save_copy_as=True` to keep the original mapping
