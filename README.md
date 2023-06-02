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

### Validated code execution

In a cell, run

```py
%prosaic_validation_allow
```

To allow model-generated code to be validated, and run if approved.

STUB: at present this is an entirely different mode with only validation implemented,
not code emission or execution.