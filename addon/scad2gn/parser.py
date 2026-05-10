from __future__ import annotations

from .ast_nodes import (
    Argument,
    Assignment,
    BinaryExpression,
    Block,
    Call,
    ForStatement,
    Identifier,
    IfStatement,
    Literal,
    ModuleDefinition,
    ParameterDefinition,
    Program,
    RangeExpression,
    UnaryExpression,
    VectorLiteral,
)
from .errors import ScadParseError
from .lexer import Lexer, Token

PRECEDENCE = {
    "||": 1,
    "&&": 2,
    "==": 3,
    "!=": 3,
    "<": 4,
    "<=": 4,
    ">": 4,
    ">=": 4,
    "+": 5,
    "-": 5,
    "*": 6,
    "/": 6,
    "%": 6,
}


class Parser:
    def __init__(self, source: str, path: str | None = None) -> None:
        self.path = path
        self.tokens = Lexer(source, path=path).tokenize()
        self.index = 0

    def parse(self) -> Program:
        location = self.current.location
        statements = []
        while not self._at("eof"):
            statements.append(self._parse_statement())
        return Program(location=location, statements=statements)

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def _peek(self, offset: int = 1) -> Token:
        return self.tokens[self.index + offset]

    def _advance(self) -> Token:
        token = self.current
        self.index += 1
        return token

    def _match(self, value: str) -> bool:
        if self.current.value == value:
            self._advance()
            return True
        return False

    def _expect(self, value: str) -> Token:
        if self.current.value != value:
            raise ScadParseError(
                f"Expected {value!r}, got {self.current.value or self.current.kind!r}",
                path=self.path,
                location=self.current.location,
            )
        return self._advance()

    def _expect_identifier(self) -> Token:
        if self.current.kind not in {"identifier", "keyword"} or self.current.value in {
            "module",
            "if",
            "else",
            "for",
            "true",
            "false",
            "undef",
        }:
            raise ScadParseError(
                f"Expected identifier, got {self.current.value or self.current.kind!r}",
                path=self.path,
                location=self.current.location,
            )
        return self._advance()

    def _at(self, kind: str) -> bool:
        return self.current.kind == kind

    def _parse_statement(self):
        if self.current.value == "{":
            return self._parse_block()
        if self.current.value == "module":
            return self._parse_module_definition()
        if self.current.value == "if":
            return self._parse_if_statement()
        if self.current.value == "for":
            return self._parse_for_statement()
        if self.current.kind in {"identifier", "keyword"}:
            return self._parse_assignment_or_call()

        raise ScadParseError(
            f"Unexpected token: {self.current.value or self.current.kind!r}",
            path=self.path,
            location=self.current.location,
        )

    def _parse_block(self) -> Block:
        location = self._expect("{").location
        statements = []
        while self.current.value != "}":
            if self._at("eof"):
                raise ScadParseError("Unterminated block", path=self.path, location=location)
            statements.append(self._parse_statement())
        self._expect("}")
        return Block(location=location, statements=statements)

    def _parse_module_definition(self) -> ModuleDefinition:
        location = self._expect("module").location
        name = self._expect_identifier().value
        self._expect("(")
        parameters: list[ParameterDefinition] = []
        if self.current.value != ")":
            while True:
                parameter_name = self._expect_identifier()
                default = None
                if self._match("="):
                    default = self._parse_expression()
                parameters.append(
                    ParameterDefinition(
                        location=parameter_name.location,
                        name=parameter_name.value,
                        default=default,
                    )
                )
                if not self._match(","):
                    break
        self._expect(")")
        body = self._parse_statement()
        return ModuleDefinition(location=location, name=name, parameters=parameters, body=body)

    def _parse_if_statement(self) -> IfStatement:
        location = self._expect("if").location
        self._expect("(")
        condition = self._parse_expression()
        self._expect(")")
        then_branch = self._parse_statement()
        else_branch = None
        if self._match("else"):
            else_branch = self._parse_statement()
        return IfStatement(
            location=location,
            condition=condition,
            then_branch=then_branch,
            else_branch=else_branch,
        )

    def _parse_for_statement(self) -> ForStatement:
        location = self._expect("for").location
        self._expect("(")
        variable = self._expect_identifier().value
        self._expect("=")
        iterable = self._parse_expression()
        self._expect(")")
        body = self._parse_statement()
        return ForStatement(location=location, variable=variable, iterable=iterable, body=body)

    def _parse_assignment_or_call(self):
        location = self.current.location
        identifier = self._expect_identifier().value
        if self._match("="):
            value = self._parse_expression()
            self._expect(";")
            return Assignment(location=location, name=identifier, value=value)

        call = self._finish_call(location, identifier)
        if self._match(";"):
            return call
        if self.current.value not in {"", "}", "else"} and not self._at("eof"):
            call.child = self._parse_statement()
        return call

    def _finish_call(self, location, name: str) -> Call:
        self._expect("(")
        arguments: list[Argument] = []
        if self.current.value != ")":
            while True:
                argument_location = self.current.location
                argument_name = None
                if (
                    self.current.kind in {"identifier", "keyword"}
                    and self._peek().value == "="
                    and self.current.value not in {"true", "false", "undef"}
                ):
                    argument_name = self._advance().value
                    self._expect("=")
                value = self._parse_expression()
                arguments.append(Argument(location=argument_location, name=argument_name, value=value))
                if not self._match(","):
                    break
        self._expect(")")
        return Call(location=location, name=name, arguments=arguments)

    def _parse_expression(self, minimum_precedence: int = 0):
        left = self._parse_unary()
        while True:
            operator = self.current.value
            precedence = PRECEDENCE.get(operator)
            if precedence is None or precedence < minimum_precedence:
                break
            location = self._advance().location
            right = self._parse_expression(precedence + 1)
            left = BinaryExpression(
                location=location,
                operator=operator,
                left=left,
                right=right,
            )
        return left

    def _parse_unary(self):
        if self.current.value in {"+", "-", "!"}:
            token = self._advance()
            return UnaryExpression(
                location=token.location,
                operator=token.value,
                operand=self._parse_unary(),
            )
        return self._parse_primary()

    def _parse_primary(self):
        token = self.current
        if token.kind == "number":
            self._advance()
            return Literal(location=token.location, value=_parse_number(token.value))
        if token.kind == "string":
            self._advance()
            return Literal(location=token.location, value=token.value)
        if token.value == "true":
            self._advance()
            return Literal(location=token.location, value=True)
        if token.value == "false":
            self._advance()
            return Literal(location=token.location, value=False)
        if token.value == "undef":
            self._advance()
            return Literal(location=token.location, value=None)
        if token.kind in {"identifier", "keyword"}:
            self._advance()
            return Identifier(location=token.location, name=token.value)
        if token.value == "(":
            self._advance()
            expression = self._parse_expression()
            self._expect(")")
            return expression
        if token.value == "[":
            return self._parse_vector_or_range()

        raise ScadParseError(
            f"Unexpected token in expression: {token.value or token.kind!r}",
            path=self.path,
            location=token.location,
        )

    def _parse_vector_or_range(self):
        location = self._expect("[").location
        if self._match("]"):
            return VectorLiteral(location=location, items=[])
        first = self._parse_expression()
        if self._match(":"):
            second = self._parse_expression()
            if self._match(":"):
                third = self._parse_expression()
                self._expect("]")
                return RangeExpression(location=location, start=first, step=second, end=third)
            self._expect("]")
            return RangeExpression(location=location, start=first, end=second)

        items = [first]
        while self._match(","):
            items.append(self._parse_expression())
        self._expect("]")
        return VectorLiteral(location=location, items=items)


def _parse_number(raw: str):
    if "." in raw or "e" in raw.lower():
        return float(raw)
    return int(raw)
