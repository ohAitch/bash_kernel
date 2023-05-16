# WIP

Fork of example kernel provided by IPython, to call a demo API.

See [README.old.rst](README.old.rst) for context.

### Demo

```sh
# venv as desired
pip install .
python -m bash_kernel.install
npx micro ./super_proprietary_api.js &
jupyter console --kernel bash
```