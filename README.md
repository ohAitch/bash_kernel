# Prosaic Kernel

An IPython kernel calling the anthropic assistant API.

### Demo

```sh
API_KEY=$(cat /run/secrets/anthropic_api_key) # or pbpaste or etc
# venv as desired
pip install .
ANTHROPIC_API_KEY="$API_KEY" python -m prosaic_kernel install --user
jupyter console --kernel prosaic
```