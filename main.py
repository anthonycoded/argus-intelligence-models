"""Deprecated legacy entry point; delegates to the same guarded training CLI."""

if __name__ == "__main__":
    import sys
    from src.train import main

    print("main.py is deprecated; use python -m src.train with --manifest.", file=sys.stderr)
    main()
