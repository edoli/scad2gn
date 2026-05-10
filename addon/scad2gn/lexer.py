from __future__ import annotations

from dataclasses import dataclass

from .errors import ScadLexerError, SourceLocation

KEYWORDS = {"module", "if", "else", "for", "true", "false", "undef"}
MULTI_CHAR_TOKENS = ("<=", ">=", "==", "!=", "&&", "||")
SINGLE_CHAR_TOKENS = set("(){}[];,:=+-*/%<>")


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: str
    location: SourceLocation


class Lexer:
    def __init__(self, source: str, path: str | None = None) -> None:
        self.source = source
        self.path = path
        self.index = 0
        self.line = 1
        self.column = 1

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while True:
            self._skip_ignored()
            if self.index >= len(self.source):
                tokens.append(Token("eof", "", SourceLocation(self.line, self.column)))
                return tokens

            location = SourceLocation(self.line, self.column)
            token = self._read_token(location)
            tokens.append(token)

    def _skip_ignored(self) -> None:
        while self.index < len(self.source):
            if self._peek().isspace():
                self._advance()
                continue

            if self._peek(2) == "//":
                while self.index < len(self.source) and self._peek() != "\n":
                    self._advance()
                continue

            if self._peek(2) == "/*":
                self._advance(2)
                while self.index < len(self.source) and self._peek(2) != "*/":
                    self._advance()
                if self._peek(2) != "*/":
                    raise ScadLexerError("Unterminated block comment", path=self.path)
                self._advance(2)
                continue

            return

    def _read_token(self, location: SourceLocation) -> Token:
        multi = self._peek(2)
        if multi in MULTI_CHAR_TOKENS:
            self._advance(2)
            return Token("operator", multi, location)

        current = self._peek()
        if current in SINGLE_CHAR_TOKENS:
            self._advance()
            return Token("operator", current, location)

        if current in {'"', "'"}:
            return self._read_string(location, current)

        if current.isdigit() or (current == "." and self._peek(2)[1:2].isdigit()):
            return self._read_number(location)

        if current.isalpha() or current in {"_", "$"}:
            return self._read_identifier(location)

        raise ScadLexerError(
            f"Unexpected character: {current!r}",
            path=self.path,
            location=location,
        )

    def _read_string(self, location: SourceLocation, quote: str) -> Token:
        self._advance()
        chars: list[str] = []
        while self.index < len(self.source):
            current = self._peek()
            if current == quote:
                self._advance()
                return Token("string", "".join(chars), location)
            if current == "\\":
                self._advance()
                if self.index >= len(self.source):
                    break
                escaped = self._peek()
                escape_map = {"n": "\n", "t": "\t", '"': '"', "'": "'", "\\": "\\"}
                chars.append(escape_map.get(escaped, escaped))
                self._advance()
                continue
            chars.append(current)
            self._advance()

        raise ScadLexerError("Unterminated string literal", path=self.path, location=location)

    def _read_number(self, location: SourceLocation) -> Token:
        start = self.index
        saw_exponent = False
        saw_decimal = False

        while self.index < len(self.source):
            current = self._peek()
            if current.isdigit():
                self._advance()
                continue
            if current == "." and not saw_decimal and not saw_exponent:
                saw_decimal = True
                self._advance()
                continue
            if current in {"e", "E"} and not saw_exponent:
                saw_exponent = True
                self._advance()
                if self._peek() in {"+", "-"}:
                    self._advance()
                continue
            break

        return Token("number", self.source[start:self.index], location)

    def _read_identifier(self, location: SourceLocation) -> Token:
        start = self.index
        while self.index < len(self.source):
            current = self._peek()
            if current.isalnum() or current in {"_", "$"}:
                self._advance()
                continue
            break
        value = self.source[start:self.index]
        kind = "keyword" if value in KEYWORDS else "identifier"
        return Token(kind, value, location)

    def _peek(self, width: int = 1) -> str:
        return self.source[self.index : self.index + width]

    def _advance(self, width: int = 1) -> None:
        for _ in range(width):
            if self.index >= len(self.source):
                return
            char = self.source[self.index]
            self.index += 1
            if char == "\n":
                self.line += 1
                self.column = 1
            else:
                self.column += 1
