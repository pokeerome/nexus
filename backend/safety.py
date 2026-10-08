import re
import secrets

# Characters that people use to hide text or to flip how it is shown.
# (Zero-width spaces, left-to-right marks, bidi controls, BOM, and the invisible "tag" block.)
_HIDDEN = re.compile(
    "[\u200b\u200e\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]"
)
# Zero-width joiners are normal inside emoji and some scripts, so we only remove them
# when a file has many of them (that looks like hidden text).
_JOINERS = re.compile("[\u200c\u200d]")
_JOINER_LIMIT = 8
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(text: str) -> tuple[str, list[str]]:
    """Remove hidden characters. Returns the clean text and a list of notes."""
    notes: list[str] = []

    cleaned, n_hidden = _HIDDEN.subn("", text)
    if n_hidden:
        notes.append(f"{n_hidden} hidden characters were removed")

    if len(_JOINERS.findall(cleaned)) >= _JOINER_LIMIT:
        cleaned = _JOINERS.sub("", cleaned)
        notes.append("many invisible joiner characters were removed")

    cleaned = _CONTROL.sub("", cleaned)
    return cleaned, notes


# Phrases that talk to the AI instead of the reader. Only specific phrases, to avoid
# flagging normal documents (for example guides about writing prompts).
_INJECTION_PATTERNS = {
    "tells the AI to ignore its rules": re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,30}\b(previous|prior|above|earlier|all|any|your)\b[^.\n]{0,30}\b(instructions?|prompts?|rules|guidelines)\b",
        re.I,
    ),
    "tries to give the AI a new role": re.compile(
        r"\b(you are now|from now on,? you|act as if you have no (rules|restrictions)|developer mode|dan mode|jailbreak)\b",
        re.I,
    ),
    "asks the AI to reveal its instructions": re.compile(
        r"\b(reveal|show|print|repeat|output|leak)\b[^.\n]{0,20}\b(your|the)\b[^.\n]{0,15}\b(system prompt|instructions|rules)\b",
        re.I,
    ),
    "pretends to be a system or chat message": re.compile(
        r"(</?\s*(system|assistant|instructions?)\s*>|^\s*(system|assistant)\s*:|\[/?(system|inst)\]|<\|im_(start|end)\|>)",
        re.I | re.M,
    ),
    "hides something from the user": re.compile(
        r"\b(do not|don't|never)\b[^.\n]{0,20}\b(tell|inform|mention to|reveal to)\b[^.\n]{0,15}\b(the )?user\b",
        re.I,
    ),
    "talks to the AI directly": re.compile(
        r"(\b(note|message|attention|instructions?|notice)\s+(to|for)\s+(the\s+)?(ai|a\.i\.|assistants?|llm|language model|chatbot)\b|\bai assistants?\s*:|\bif you are (an? )?(ai|language model|llm|assistant)\b)",
        re.I,
    ),
    "pretends to be our document markers": re.compile(
        r"(<<\s*(end|doc)-|</?\s*document\s*>)",
        re.I,
    ),
    "pretends to be an official message": re.compile(
        r"\b(message|notice|note|update)\s+from\s+(the\s+)?(admin(istrator)?|system|developer|operator)\b(?!['’]s)",
        re.I,
    ),
    "tries to send data to a web address": re.compile(
        r"(\b(send|post|upload|forward|transmit|exfiltrate)\b[^.\n]{0,80}https?://|!\[[^\]]*\]\(https?://[^)]*\))",
        re.I,
    ),
}


def detect_injection(text: str) -> list[str]:
    return [name for name, pattern in _INJECTION_PATTERNS.items() if pattern.search(text)]


def safe_filename(name: str, limit: int = 120) -> str:
    """File names come from users too, so they must not be able to add lines or quotes."""
    name = _HIDDEN.sub("", name)
    name = re.sub(r"[\r\n\t\x00-\x1f\x7f]+", " ", name)
    name = name.replace('"', "'").replace("<", "(").replace(">", ")")
    return re.sub(r" {2,}", " ", name).strip()[:limit] or "file"


def wrap_passage(nonce: str, filename: str, content: str) -> str:
    """Put one passage between markers that carry a random code the file's author cannot guess."""
    text = clean_text(content)[0].replace(nonce, "")
    return f'<<DOC-{nonce} source="{safe_filename(filename)}">>\n{text}\n<<END-{nonce}>>'


def wrap_documents(passages: list[tuple[str, str]]) -> str:
    nonce = secrets.token_hex(6)
    return "\n\n".join(wrap_passage(nonce, f, c) for f, c in passages)


def new_nonce() -> str:
    return secrets.token_hex(6)