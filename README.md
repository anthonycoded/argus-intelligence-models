# Argus Intelligence Classifier (AIC-1) — Starter

Separate, local research workspace. Does not connect to or modify Argus-Core databases.

## Windows 11 / Command Prompt

```bat
cd %USERPROFILE%\Desktop\projects
mkdir argus-intelligence-models
cd argus-intelligence-models
```

Extract this ZIP **into** `argus-intelligence-models` (so `src` is directly inside it).

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
```

Install PyTorch from https://pytorch.org/get-started/locally/ choosing your Windows CPU/CUDA settings. Then:

```bat
pip install -r requirements.txt
python -c "import torch; print('Torch:',torch.__version__,'CUDA:',torch.cuda.is_available())"
python -m pytest -q
python -m src.validate_dataset data/labeled/pilot.jsonl
```

The `data/labeled/pilot.jsonl` file starts empty on purpose. It contains **no ground-truth data** until a human has verified labels. Use `examples/annotation_template.json` as the template and enter one JSON record per line in the pilot file. Aim for 200–500 examples before trusting any comparison. Each record has an event_group_id; all records from an event/story must stay in the same split.

When ready:

```bat
python -m src.split_dataset --input data/labeled/pilot.jsonl --out data/splits
python -m src.train --data data/splits --model distilbert/distilbert-base-uncased
```

The split command will refuse to run on fewer than 30 verified examples or fewer than 3 event groups per class; this is a **sanity floor**, not a meaningful evaluation sample. With 200–500 pilot examples, evaluate carefully, and reserve a truly held-out test set for final comparison. Training downloads model weights on first use. `src.train` never accesses the test split and logs validation metrics only.

## Dataset rules
- Exactly one JSON object per line, UTF-8.
- `label`: `unrelated`, `partially_relevant`, `relevant`.
- `label_source`: must be `human_verified` for training.
- `subject_spec`: what must be true for relevance, including geographic and exclusion rules.
- `article_text`: published/extracted article text, not LLM-generated paraphrase; respect source rights.
- `event_group_id`: stable event cluster ID, used to prevent leakage.
- `source_id`, `collected_at`, `annotation_version`, `rationale`: mandatory provenance.
- Class labels are not truth until adjudicated by your written annotation policy.
- Do not put secrets, API keys, or sensitive personal information in datasets.

## Exit criteria
1. PyTorch and tests run locally.
2. Annotation rules and records are validated.
3. Data splits have no event-group overlap.
4. Baseline runs on labeled data with validation metrics.
5. No operational Argus-Core schema or data changes.
