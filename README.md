# Swift ↔ Python Analyzer Bridge

Files added:

- swift_cli/main.swift — Swift CLI skeleton that calls the Python analyzer.
- python/analyzer.py — Placeholder Python script that prints JSON for a set name.

Run (from repository root):

```bash
swift run --package-path swift_cli # if you create a package
# or compile and run directly
swiftc swift_cli/main.swift -o analyzer && ./analyzer "Base Set"
```

Or run with prompt:

```bash
./analyzer
# then type the set name when prompted
```
