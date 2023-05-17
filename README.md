# WIP

Fork of example kernel provided by IPython, to call the anthropic assistant API.

See [README.old.rst](README.old.rst) for context.

### Demo

```sh
API_KEY=$(cat /run/secrets/anthropic_api_key) # or pbpaste or etc
# venv as desired
pip install .
ANTHROPIC_API_KEY="$API_KEY" python -m bash_kernel.install
jupyter console --kernel bash
```