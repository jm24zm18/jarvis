"""Command parsing and handlers."""

def parse_command(text: str) -> tuple[str, list[str]] | None:
    if not text.startswith("/"):
        return None
    tokens = text.strip().split()
    return tokens[0].lower(), tokens[1:]
