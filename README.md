# MH AI Chatbot

A question-answering website for game databases. You choose a game, ask a question in plain language
(for example *"What is the best armor set I can make for bow, rank 3?"*) and the answer is computed from
that game's local JSON database. Nothing in an answer comes from outside the database.

The project is generic: you bring the database, describe its format in a small JSON file, and optionally
bring a language model of your choice. The Monster Hunter Rise database is included as the working example.

## How it works

```
question ──► parser ──► query ──► engine (reads only data/<game>/*.json) ──► answer
              │
              └─ rules, optionally assisted by a language model
```

- **Database**: JSON files in `data/<game-id>/`. Each game has a definition file in `games/<game-id>.json`
  that says where the files are and how to read their fields. No game-specific format lives in the code.
- **Engine**: looks up skills, armor, weapons, decorations and items, and searches for the best armor set
  for a weapon type and rank. Every name and number in an answer comes from the database.
- **Parser**: a rules-based parser understands common questions. If a language model is configured, it
  helps with free-form phrasing. Its output is mapped back onto database entries, and anything the database
  does not contain is discarded. If the model is unavailable, the rules parser answers alone.
- **Game selection**: the question box is disabled until a game is selected, and every lookup is limited to that game.

Where the data does not contain something (for example Master Rank in the Rise dataset), the answer says so.

## Databases

Games are read from local JSON files under `data/<game-id>/`. The folder is not committed.

**Monster Hunter Rise** uses the database from
[Badge87/MHRiseScraperData](https://github.com/Badge87/MHRiseScraperData/tree/main) (MIT licensed), which
aggregates data from kiranico and the Fextralife wiki. Fetch it with:

```bash
python scripts/fetch_data.py rise=https://github.com/Badge87/MHRiseScraperData.git#MHRiseScraperData
```

The script takes `<game-id>=<git-url>[#sub-folder]`, clones the repository and copies its `.json` files to
`data/<game-id>/`. You can also copy your own files into that folder by hand.

## Quick start

Requires Python 3.9 or newer. The web app has no dependencies.

```bash
python scripts/fetch_data.py rise=https://github.com/Badge87/MHRiseScraperData.git#MHRiseScraperData
python -m mhbot.check            # lists the games and whether they load
python -m unittest discover -s tests
python -m mhbot.server           # http://localhost:8000
```

Without a model the site answers with the rules parser. To add a model, see [Language model](#language-model).

## Adding a database

1. Put the JSON files in `data/<game-id>/`.
2. Copy `games/_template.json` to `games/<game-id>.json` and describe the files.
3. Run `python -m mhbot.check <game-id>`. It prints the row count and a sample row of each table, or the
   exact table, field and record that does not match.

`games/rise.json` is a complete example. The definition has these top-level keys:

| key | purpose |
|---|---|
| `id`, `label` | identifier and display name |
| `data_dir` | folder with the JSON files: a sub-folder of `data/`, or an absolute path |
| `examples` | example questions shown in the UI |
| `ranks` | ordered ranks (`id`, `label`, `aliases`, `hunter_rank`). A number in a question ("rank 3", "HR 3") is matched against each rank's `hunter_rank` range `[min, max]`, `max` being `null` for no upper limit. Without ranges the number is the position in the list. A rank with no data in the dataset falls back to the nearest lower rank, with a note |
| `part_order` | order in which armor parts are listed |
| `weapon_types` | `value` (as stored in the data), `name`, `aliases`, optional `text_hints` |
| `extras_label` | display name for weapon extras (for example rampage skills) |
| `notes` | dataset caveats shown under build answers |
| `ambiguous_skill_names` | skills named like ordinary words; they only match with context |
| `scoring` | how "best" is judged, see below |
| `tables` | how to read each file |

`tables` supports `skills`, `armors`, `decorations`, `weapons` and `items`. Omit a table the game does not have.
Each table has `file`, `records` (dotted path to the list inside the file, `$` for the file itself) and `fields`.
`*` marks required fields.

| table | fields |
|---|---|
| `skills` | `name`*, `description`, `levels` (list of per-level texts) |
| `armors` | `name`*, `part`*, `rank`*, `defense`*, `slots`* (`[size1, size2, size3]`), `skills`* (`{name: level}`), `rarity`, `res.<element>`, `materials`, `set` |
| `decorations` | `name`*, `size`*, `skills`* (`{name: level}`), `materials` |
| `weapons` | `name`*, `type`*, `attack`*, `rank`, `rarity`, `affinity`, `defense_bonus`, `extras`, `materials` |
| `items` | `name`*, `description`, `buy`, `sell` |

A field is either a dotted path (`"stats.defense"`) or an object `{"path": ..., "type": ..., "default": ...}`:

| type | effect |
|---|---|
| `str` (default), `int`, `float` | plain conversion; `int` also accepts values like `"x2"` |
| `enum` + `map` | translate raw values, for example `{"0": "low", "1": "high"}` |
| `range_map` + `ranges` | number to id by range, for example `{"low": [0, 2], "high": [3, 6]}` |
| `weapon_type` | raw value to a `weapon_types` name through each entry's `value` |
| `json_int_list` + `size` | `"[1, 0, 0]"` or a real list to a padded list of integers |
| `tail_int` | trailing number of a string (`"Attack Jewel 2"` gives 2) |
| `list_str` + `each` | list of objects to a list of one inner field |
| `name_levels` + `name`, `level` or `level_path` | list of objects to `{name: level}` |
| `materials` + `item`, `amount` | list of objects to `[(item, amount)]` |
| `keys_regex_list` + `pattern` | collect sibling keys such as `lv1`..`lv7` into a list |

The data location can be overridden without editing the file: `MH_DATA_DIR_<ID>` for one game, or
`MH_DATA_ROOT` to replace the `data/` folder.

### How "best" is decided

Build answers rank armor sets by the skills that matter for the chosen weapon. That is read from the
database: a skill counts when a sentence in its description contains one of the `scoring.keywords`
together with a positive verb, and a skill whose texts name other weapon types is excluded.
Each answer lists the skills that were scored and why. Remove the `scoring` block to rank by defense only.

```json
"scoring": {
  "keywords": {"attack": 3.0, "affinity": 2.5, "critical": 2.0},
  "positive_verbs": ["increase", "improve", "boost"],
  "ignore_if_contains": ["damage taken"],
  "weapon_specific_weight": 1.5
}
```

## Language model

The model is optional and is configured only through environment variables. Any GGUF chat model from
Hugging Face works, served with [llama.cpp](https://github.com/ggml-org/llama.cpp) through
`llama-cpp-python`. The application talks to it over the OpenAI-compatible API, so any server that exposes
`/v1/chat/completions` can be used instead by setting `LLM_BASE_URL`.

### Choosing a model

Pick by your hardware and preference:

- Instruction-tuned ("Instruct" or "chat") models follow the JSON instruction the parser sends.
- A GGUF file with 4-bit quantization (for example `Q4_K_M`) needs roughly 0.6 GB per billion parameters
  of RAM or VRAM, plus headroom for the context.
- Small models (1B to 3B) run on a CPU in seconds per question. Larger models (7B and up) understand
  loosely worded questions better but want more memory, ideally a GPU.
- Check the license on the model page, and that the repository contains a `.gguf` file.

Search on huggingface.co/models with the library filter set to GGUF and a name containing "Instruct".

### Configuration

| variable | meaning | default |
|---|---|---|
| `MHBOT_MODEL_REPO` | Hugging Face repository (`owner/name`) | required |
| `MHBOT_MODEL_FILE` | `.gguf` file inside the repository | required |
| `MHBOT_MODEL_REVISION` | branch, tag or commit | latest |
| `MHBOT_MODEL_PATH` | use a local `.gguf` instead of downloading | |
| `HF_TOKEN` | token for gated or private repositories | |
| `MHBOT_MODELS_DIR` | download folder | `./models` |
| `MHBOT_N_CTX` | context size | `2048` |
| `MHBOT_N_THREADS` | CPU threads | all cores |
| `MHBOT_N_GPU_LAYERS` | layers offloaded to the GPU, `-1` for all | `0` |
| `MHBOT_CHAT_FORMAT` | llama.cpp chat format; unset to use the template inside the GGUF | |
| `MHBOT_LLM_HOST`, `MHBOT_LLM_PORT` | bind address of the model server | `127.0.0.1:8081` |
| `LLM_BASE_URL` | model server the web app talks to; unset disables the model | |
| `LLM_TIMEOUT` | seconds to wait before using the rules parser | `60` |
| `LLM_NARRATE` | set to `1` to let the model add a one-sentence summary | `0` |

`LLM_NARRATE` is off by default. A generated sentence cannot be fully verified against the data, so leave
it off when answers must come strictly from the database.

### Run it locally

```bash
python -m venv .venv
.venv\Scripts\activate                 # macOS and Linux: source .venv/bin/activate
pip install -r requirements-llm.txt

export MHBOT_MODEL_REPO=owner/Model-GGUF        # PowerShell: $env:MHBOT_MODEL_REPO="owner/Model-GGUF"
export MHBOT_MODEL_FILE=model-q4_k_m.gguf
python -m mhbot.model serve                      # downloads once, then serves on 127.0.0.1:8081
```

In a second terminal:

```bash
export LLM_BASE_URL=http://127.0.0.1:8081/v1
python -m mhbot.server
```

Each answer reports its `engine`: `llm+rules` when the model took part, `rules` otherwise.

## Docker

The image has two targets, `web` and `llm`. The model and the databases are fetched when the image is built,
from build arguments that come from environment variables.

```bash
cp .env.example .env
# edit .env: DATA_SOURCES, MHBOT_MODEL_REPO, MHBOT_MODEL_FILE, ...
docker compose --env-file .env up -d --build
```

| variable | used for |
|---|---|
| `DATA_SOURCES` | databases to fetch at build time, `<game-id>=<git-url>[#sub-folder]`, space separated |
| `MHBOT_MODEL_REPO`, `MHBOT_MODEL_FILE`, `MHBOT_MODEL_REVISION` | model downloaded into the `llm` image |
| `MHBOT_N_CTX`, `MHBOT_N_THREADS`, `MHBOT_N_GPU_LAYERS`, `MHBOT_CHAT_FORMAT` | runtime settings of the model server |
| `LLM_TIMEOUT` | web app timeout for the model |
| `WEB_PORT` | host port when publishing, see below |

Example `DATA_SOURCES` for Rise:
`rise=https://github.com/Badge87/MHRiseScraperData.git#MHRiseScraperData`

Files:

- `docker-compose.yml`: `llm` and `web` services. `MHBOT_MODEL_REPO` and `MHBOT_MODEL_FILE` are required.
- `docker-compose.web-only.yml`: only the web service, using the rules parser.
- `docker-compose.ports.yml`: publishes `WEB_PORT` on the host, for running locally:
  `docker compose -f docker-compose.yml -f docker-compose.ports.yml up -d --build`

The web service only exposes port 8000 to the compose network. A reverse proxy such as Traefik, Caddy or
nginx should route a domain to it. Gated models need `HF_TOKEN` at build time; build arguments are stored in
the image history, so use a private registry or the `MHBOT_MODEL_PATH` option for those.

## Google Colab

`colab/mhbot_colab.ipynb` runs the same application with a GPU-hosted model. Fill in the repository,
`DATA_SOURCES` and the model variables in the first cell and run all cells. It starts the model server,
the web app and a temporary public link.

## Project layout

```
games/        definition files: where each database is and how to read it
data/         local databases, one folder per game (not committed)
mhbot/        application code (parser, engine, optimizer, server, model manager)
web/          single-page UI
scripts/      fetch_data.py
tests/        unit tests
colab/        notebook
```

Tests: `python -m unittest discover -s tests`. The Rise tests are skipped when `data/rise` is missing.

## Credits and license

The Monster Hunter Rise data comes from [Badge87/MHRiseScraperData](https://github.com/Badge87/MHRiseScraperData),
which collects it from [mhrise.kiranico.com](https://mhrise.kiranico.com/) and the
[Fextralife wiki](https://monsterhunterrise.wiki.fextralife.com/). Monster Hunter is a trademark of Capcom;
this project is not affiliated with Capcom.

Released under the MIT License, see `LICENSE`.
