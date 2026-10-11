import re
from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class Token:
    type: str # 'WORD', 'NUMBER', 'STRING', 'PERIOD', 'SYMBOL'
    value: str
    line: int
    col: int

class CobolLexer:
    @staticmethod
    def preprocess_lines(source_code: str) -> List[Tuple[int, str]]:
        """
        Cleans COBOL source lines handling standard 80-column fixed-format or modern free-format.
        Returns list of (1-indexed line_number, sanitized_line).
        """
        raw_lines = source_code.splitlines()
        processed = []
        for idx, line in enumerate(raw_lines, 1):
            # Check comment
            # If line is at least 7 chars and char 7 is * or /
            if len(line) >= 7 and line[6] in ('*', '/'):
                continue
            
            # Check inline free-form comment *>
            if '*>' in line:
                line = line.split('*>', 1)[0]
                
            # If fixed format line with sequence numbers in col 1-6
            # Standard COBOL has code in cols 8 to 72
            if len(line) >= 7 and (line[:6].isdigit() or line[:6].isspace()) and line[6] in (' ', '-'):
                # Extract columns 8-72 if available
                content = line[7:72] if len(line) >= 72 else line[7:]
            else:
                content = line

            stripped = content.strip()
            if stripped:
                processed.append((idx, stripped))
        return processed

    @classmethod
    def tokenize(cls, source_code: str) -> List[Token]:
        lines = cls.preprocess_lines(source_code)
        tokens = []
        
        # Regex for tokens
        # 1. String: '...' or "..."
        # 2. Number: optional sign, digits, optional decimal, digits
        # 3. Period: .
        # 4. Word/Identifier: [A-Za-z0-9\-_]+
        # 5. Symbols: (, ), =, +, -, *, /, etc.
        token_pattern = re.compile(
            r'(?P<STRING>"(?:[^"]|"")*"|\'(?:[^\']|\'\')*\')|'
            r'(?P<PERIOD>\.(?=\s|$))|'
            r'(?P<NUMBER>[-+]?\d*\.?\d+(?=[ \t\r\n.,;()]|$))|'
            r'(?P<WORD>[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*)|'
            r'(?P<SYMBOL>>=|<=|<>|!=|==|[(),=+\-*/><])'
        )

        for line_no, text in lines:
            pos = 0
            while pos < len(text):
                match = token_pattern.search(text, pos)
                if not match:
                    break
                
                # Check for skipped whitespace
                pos = match.end()
                kind = match.lastgroup
                val = match.group(kind)
                col = match.start() + 1
                
                if kind == 'STRING':
                    # unquote string
                    unquoted = val[1:-1].replace('""', '"').replace("''", "'")
                    tokens.append(Token('STRING', unquoted, line_no, col))
                elif kind == 'PERIOD':
                    tokens.append(Token('PERIOD', '.', line_no, col))
                elif kind == 'NUMBER':
                    tokens.append(Token('NUMBER', val, line_no, col))
                elif kind == 'WORD':
                    tokens.append(Token('WORD', val.upper(), line_no, col))
                elif kind == 'SYMBOL':
                    tokens.append(Token('SYMBOL', val, line_no, col))
        return tokens
