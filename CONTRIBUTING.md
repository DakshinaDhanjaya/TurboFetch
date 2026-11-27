# Contributing to TurboFetch

Contributions are welcome!

## Development Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m unittest discover -s turbofetch/tests -v
```

## Coding Guidelines

- Keep Python code typed cleanly with standard library / dataclasses and minimal dependencies.
- Keep idle background CPU usage at zero — avoid polling timers when no downloads are active.
- Avoid introducing comments or docstrings in Python source files under `turbofetch/`.
- Ensure all unit tests and JS syntax checks pass before opening a pull request:
  ```powershell
  python -m unittest discover -s turbofetch/tests -v
  node --check turbofetch/extension/content.js
  node --check turbofetch/extension/background.js
  node --check turbofetch/extension/popup/popup.js
  node --check turbofetch/extension/options/options.js
  ```
