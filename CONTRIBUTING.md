# Contributing to Corely.MicroPython

We welcome contributions! Here are some guidelines to help you get started.

## How to Contribute

1. **Clone the Repository**: Clone the repository to your local machine.
2. **Create a Branch**: Create a new branch for your feature or bug fix.
3. **Make Changes**: Follow the coding standards below and include tests.
4. **Check**: Run the tests and the compile check (see below).
5. **Push Changes**: Push your branch and open a pull request with a clear description.

```bash
cd tests && python -m unittest discover -s . -t .
python scripts/build.py --check
python scripts/package.py --check
```

`scripts/build.py --check` needs `pip install "mpy-cross==1.27.0.post2"`.

## Reporting Issues

If you find a bug or have a feature request, please open an issue on the [GitHub Issues](https://github.com/ultrabstrong/Corely.MicroPython/issues) page.

## Coding Standards

### General Guidelines
- Board agnostic: rely on `machine`, `network` and `aioble`, nothing specific to one board
- No I/O the caller did not hand in: credentials, settings and paths are the application's
- Nothing blocks the event loop
- Use a package for anything with a wire format or a spec; own only GPIO level behaviour

### Naming Conventions
- `PascalCase` for classes
- `snake_case` for functions, methods and variables
- `_leading_underscore` for private members
- `UPPER_SNAKE_CASE` for constants
- Name an Action for its state (`steady()`, `blinking()`), a callback for its event (`on_press`)

### Module Layout
- Related classes share a module; one class per file costs RAM and import time on a device
- Flat modules in the `corely` package, no subpackages
- Nothing re-exported from `corely/__init__.py`

### Coding Style
- Tabs for indentation
- Docstrings on classes and public methods, with an `Args:` block
- Tests use `unittest` and the harness in `tests/harness.py`; timings stay generous
- Code that runs on a device is tried on one before release

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
