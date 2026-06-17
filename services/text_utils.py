def tc(s):
    """Title-case a name: 'john doe' → 'John Doe', handles None gracefully."""
    if not s:
        return s
    return ' '.join(w.capitalize() for w in s.strip().split())


def sc(s):
    """Sentence-case a free-text field: capitalizes first letter only."""
    if not s:
        return s
    s = s.strip()
    return s[0].upper() + s[1:] if s else s
