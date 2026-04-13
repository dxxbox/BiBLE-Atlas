# BiBLE-Atlas

BiBLE Atlas is context management database support semantic retrieval and progressive content loading. 
BiBLE Atlas makes it easy to setup domain knowledges, maintains session memory while using common LLM.

BiBLE Atlas provides rapid mode (default) and thinking mode.

## Components

BiBLE Atlas contains:

- BiBLE Atlas server backend and opensearch DB
- BiBLE Plugin for VSCode
- BiBLE CLI

## Environment Prepare

uv sync --all-extras

source .venv/bin/activate

**Note:** You should switch to proper python version (3.10+) or you'll face import issue.

## check/foramt before push

Github has been configured with LINT, you'd better run below command and format your code before submit.

> uv run format path/to/changed_file.py another/path/to/changed_file2.py
>
> uv run check --fix path/to/changed_file.py another/path/to/changed_file2.py
>
> uv run mypy path/to/changed_file.py another/path/to/changed_file2.py