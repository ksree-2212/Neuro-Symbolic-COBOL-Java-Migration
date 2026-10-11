import re
from typing import List, Dict, Optional, Tuple, Any
from backend.app.services.parsing.cobol_lexer import CobolLexer, Token
from backend.app.services.parsing.cobol_ast import (
    ProgramNode, DivisionNode, SectionNode, ParagraphNode,
    StatementNode, DataItemNode, SourceSpan
)

class CobolParser:
    def __init__(self, source_code: str):
        self.source_code = source_code
        self.tokens: List[Token] = CobolLexer.tokenize(source_code)
        self.pos = 0
        self.total = len(self.tokens)

    def current(self) -> Optional[Token]:
        if self.pos < self.total:
            return self.tokens[self.pos]
        return None

    def peek(self, offset: int = 1) -> Optional[Token]:
        idx = self.pos + offset
        if idx < self.total:
            return self.tokens[idx]
        return None

    def advance(self) -> Optional[Token]:
        tok = self.current()
        self.pos += 1
        return tok

    def match(self, token_type: str, value: Optional[str] = None) -> bool:
        tok = self.current()
        if not tok:
            return False
        if tok.type != token_type:
            return False
        if value is not None and tok.value.upper() != value.upper():
            return False
        self.advance()
        return True

    def check(self, token_type: str, value: Optional[str] = None) -> bool:
        tok = self.current()
        if not tok:
            return False
        if tok.type != token_type:
            return False
        if value is not None and tok.value.upper() != value.upper():
            return False
        return True

    def parse(self) -> ProgramNode:
        start_line = 1
        end_line = self.tokens[-1].line if self.tokens else 1
        program = ProgramNode(
            node_type="Program",
            span=SourceSpan(start_line, end_line),
            name="MAIN-PROGRAM",
            program_id="MAIN-PROGRAM"
        )

        while self.pos < self.total:
            tok = self.current()
            if not tok:
                break

            # Check IDENTIFICATION DIVISION
            if tok.type == 'WORD' and tok.value == 'IDENTIFICATION':
                div = self._parse_identification_division()
                if div:
                    program.divisions['IDENTIFICATION'] = div
                    if 'program_id' in div.details:
                        program.program_id = div.details['program_id']
                        program.name = program.program_id
                continue

            # Check ENVIRONMENT DIVISION
            if tok.type == 'WORD' and tok.value == 'ENVIRONMENT':
                div = self._parse_environment_division()
                if div:
                    program.divisions['ENVIRONMENT'] = div
                continue

            # Check DATA DIVISION
            if tok.type == 'WORD' and tok.value == 'DATA':
                div = self._parse_data_division()
                if div:
                    program.divisions['DATA'] = div
                continue

            # Check PROCEDURE DIVISION
            if tok.type == 'WORD' and tok.value == 'PROCEDURE':
                div = self._parse_procedure_division()
                if div:
                    program.divisions['PROCEDURE'] = div
                continue

            self.advance()

        # Build children hierarchy
        program.children = list(program.divisions.values())
        return program

    def _parse_identification_division(self) -> DivisionNode:
        start_line = self.current().line
        self.advance() # IDENTIFICATION
        self.match('WORD', 'DIVISION')
        self.match('PERIOD', '.')

        program_id = "UNKNOWN"
        while self.pos < self.total:
            tok = self.current()
            if not tok or (tok.type == 'WORD' and tok.value in ('ENVIRONMENT', 'DATA', 'PROCEDURE')):
                break
            if tok.type == 'WORD' and tok.value == 'PROGRAM-ID':
                self.advance()
                self.match('PERIOD', '.')
                name_tok = self.current()
                if name_tok and name_tok.type in ('WORD', 'STRING'):
                    program_id = name_tok.value
                    self.advance()
                self.match('PERIOD', '.')
            else:
                self.advance()

        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line
        return DivisionNode(
            node_type="Division",
            span=SourceSpan(start_line, end_line),
            name="IDENTIFICATION DIVISION",
            details={"program_id": program_id}
        )

    def _parse_environment_division(self) -> DivisionNode:
        start_line = self.current().line
        self.advance() # ENVIRONMENT
        self.match('WORD', 'DIVISION')
        self.match('PERIOD', '.')

        while self.pos < self.total:
            tok = self.current()
            if not tok or (tok.type == 'WORD' and tok.value in ('DATA', 'PROCEDURE')):
                break
            self.advance()

        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line
        return DivisionNode(
            node_type="Division",
            span=SourceSpan(start_line, end_line),
            name="ENVIRONMENT DIVISION"
        )

    def _parse_data_division(self) -> DivisionNode:
        start_line = self.current().line
        self.advance() # DATA
        self.match('WORD', 'DIVISION')
        self.match('PERIOD', '.')

        div = DivisionNode(
            node_type="Division",
            span=SourceSpan(start_line, start_line),
            name="DATA DIVISION"
        )

        current_section: Optional[SectionNode] = None
        data_stack: List[DataItemNode] = []

        while self.pos < self.total:
            tok = self.current()
            if not tok or (tok.type == 'WORD' and tok.value == 'PROCEDURE'):
                break

            # Section header? e.g. WORKING-STORAGE SECTION. or LINKAGE SECTION. or FILE SECTION.
            if tok.type == 'WORD' and self.peek() and self.peek().value == 'SECTION':
                sec_name = tok.value
                sec_start = tok.line
                self.advance() # Name
                self.advance() # SECTION
                self.match('PERIOD', '.')
                current_section = SectionNode(
                    node_type="Section",
                    span=SourceSpan(sec_start, sec_start),
                    name=f"{sec_name} SECTION"
                )
                div.sections.append(current_section)
                data_stack.clear()
                continue

            # Data item or COPY statement
            if tok.type == 'WORD' and tok.value == 'COPY':
                stmt = self._parse_statement()
                if stmt:
                    if current_section:
                        # Represent copybook data dependency
                        current_section.details.setdefault("copybooks", []).append(stmt.copybook_name)
                    div.details.setdefault("copybooks", []).append(stmt.copybook_name)
                continue

            # Check level number (01, 05, 10, 77, 88, etc.)
            if tok.type == 'NUMBER' and tok.value.isdigit():
                level = int(tok.value)
                if level == 88:
                    cond = self._parse_condition_item()
                    if cond:
                        # Attach level 88 condition to the most recent data item
                        active_items = current_section.children if current_section else div.data_items
                        if active_items:
                            last_item = active_items[-1]
                            if isinstance(last_item, DataItemNode):
                                last_item.conditions.append(cond)
                                last_item.details.setdefault("conditions", []).append(cond)
                    continue

                item = self._parse_data_item(level)
                if item:
                    # Maintain parent-child record hierarchy (e.g., 05 nested under 01)
                    while data_stack and data_stack[-1].level >= item.level:
                        data_stack.pop()
                    if data_stack:
                        data_stack[-1].children.append(item)
                    data_stack.append(item)

                    div.data_items.append(item)
                    if current_section:
                        current_section.children.append(item)
                continue

            self.advance()

        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line
        div.span.end_line = end_line
        div.children = list(div.sections)
        return div

    def _parse_condition_item(self) -> Optional[Dict[str, Any]]:
        start_line = self.current().line
        self.advance() # 88
        name_tok = self.current()
        if not name_tok or name_tok.type != 'WORD':
            return None
        cond_name = name_tok.value
        self.advance()

        values = []
        if self.match('WORD', 'VALUE') or self.match('WORD', 'VALUES'):
            self.match('WORD', 'IS')
            self.match('WORD', 'ARE')
            while self.pos < self.total:
                tok = self.current()
                if not tok or tok.type == 'PERIOD':
                    self.match('PERIOD', '.')
                    break
                if tok.type == 'NUMBER' and tok.value.isdigit() and int(tok.value) in (1, 5, 10, 77, 88):
                    break
                if tok.type in ('STRING', 'NUMBER', 'WORD'):
                    values.append(tok.value)
                self.advance()

        return {
            "name": cond_name,
            "values": values,
            "start_line": start_line
        }

    def _parse_data_item(self, level: int) -> Optional[DataItemNode]:
        start_line = self.current().line
        self.advance() # level number
        
        name_tok = self.current()
        if not name_tok or name_tok.type != 'WORD':
            return None
        var_name = name_tok.value
        self.advance()

        pic_clause = ""
        val_clause = None
        data_type = "ALPHANUMERIC"
        usage = "DISPLAY"
        redefines = None
        occurs = None
        signed = False

        while self.pos < self.total:
            tok = self.current()
            if not tok or tok.type == 'PERIOD':
                self.match('PERIOD', '.')
                break
            
            # End of statement on new level number or section/division
            if tok.type == 'NUMBER' and tok.value.isdigit() and int(tok.value) in (1, 5, 10, 77, 88):
                break
            if tok.type == 'WORD' and tok.value in ('SECTION', 'DIVISION', 'PROCEDURE'):
                break

            if tok.type == 'WORD' and tok.value in ('PIC', 'PICTURE'):
                self.advance()
                self.match('WORD', 'IS')
                # Read PIC tokens until next keyword or period
                pic_tokens = []
                while self.pos < self.total:
                    ptok = self.current()
                    if not ptok or ptok.type == 'PERIOD' or (ptok.type == 'WORD' and ptok.value in ('VALUE', 'USAGE', 'COMP', 'COMP-3', 'COMPUTATIONAL', 'COMPUTATIONAL-3', 'REDEFINES', 'OCCURS')):
                        break
                    pic_tokens.append(ptok.value)
                    self.advance()
                pic_clause = "".join(pic_tokens)
                signed = 'S' in pic_clause.upper()
                if '9' in pic_clause:
                    data_type = "DECIMAL" if ('V' in pic_clause.upper() or '.' in pic_clause) else "NUMERIC"
                else:
                    data_type = "ALPHANUMERIC"
                continue

            if tok.type == 'WORD' and tok.value == 'VALUE':
                self.advance()
                self.match('WORD', 'IS')
                val_tok = self.current()
                if val_tok:
                    val_clause = val_tok.value
                    self.advance()
                continue

            if tok.type == 'WORD' and tok.value in ('COMP', 'COMPUTATIONAL'):
                usage = "COMP"
                self.advance()
                continue

            if tok.type == 'WORD' and tok.value in ('COMP-3', 'COMPUTATIONAL-3'):
                usage = "COMP-3"
                self.advance()
                continue

            if tok.type == 'WORD' and tok.value == 'REDEFINES':
                self.advance()
                ref = self.current()
                if ref:
                    redefines = ref.value
                    self.advance()
                continue

            if tok.type == 'WORD' and tok.value == 'OCCURS':
                self.advance()
                occ = self.current()
                if occ and occ.type == 'NUMBER':
                    occurs = int(occ.value)
                    self.advance()
                self.match('WORD', 'TIMES')
                continue

            self.advance()

        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line
        return DataItemNode(
            node_type="DataItem",
            span=SourceSpan(start_line, end_line),
            name=var_name,
            level=level,
            pic=pic_clause,
            value=val_clause,
            data_type=data_type,
            usage=usage,
            redefines=redefines,
            occurs=occurs,
            details={
                "level": level,
                "pic": pic_clause,
                "value": val_clause,
                "data_type": data_type,
                "usage": usage,
                "redefines": redefines,
                "occurs": occurs,
                "signed": signed
            }
        )

    def _parse_procedure_division(self) -> DivisionNode:
        start_line = self.current().line
        self.advance() # PROCEDURE
        self.match('WORD', 'DIVISION')
        
        # Check USING clause: PROCEDURE DIVISION USING PARAM1 PARAM2 ...
        using_params = []
        if self.match('WORD', 'USING'):
            while self.pos < self.total:
                tok = self.current()
                if not tok or tok.type == 'PERIOD':
                    break
                using_params.append(tok.value)
                self.advance()
        self.match('PERIOD', '.')

        div = DivisionNode(
            node_type="Division",
            span=SourceSpan(start_line, start_line),
            name="PROCEDURE DIVISION",
            details={"using": using_params}
        )

        current_section: Optional[SectionNode] = None
        current_paragraph: Optional[ParagraphNode] = None

        while self.pos < self.total:
            tok = self.current()
            if not tok:
                break

            # Section header? e.g. MAIN-SECTION SECTION.
            if tok.type == 'WORD' and self.peek() and self.peek().value == 'SECTION':
                sec_name = tok.value
                sec_start = tok.line
                self.advance() # Name
                self.advance() # SECTION
                self.match('PERIOD', '.')
                current_section = SectionNode(
                    node_type="Section",
                    span=SourceSpan(sec_start, sec_start),
                    name=sec_name
                )
                div.sections.append(current_section)
                current_paragraph = None
                continue

            # Paragraph header? e.g. 0100-CALCULATE-TAX. or MAIN-PARA.
            if tok.type == 'WORD' and self.peek() and self.peek().type == 'PERIOD':
                # Ensure it's not a statement verb
                if tok.value not in ('STOP', 'EXIT', 'GOBACK', 'PERFORM', 'CALL', 'MOVE', 'COMPUTE', 'ADD', 'SUBTRACT', 'MULTIPLY', 'DIVIDE', 'IF', 'EVALUATE', 'DISPLAY', 'ACCEPT', 'COPY', 'ELSE', 'END-IF', 'END-EVALUATE', 'WHEN'):
                    para_name = tok.value
                    para_start = tok.line
                    self.advance() # Name
                    self.advance() # PERIOD
                    current_paragraph = ParagraphNode(
                        node_type="Paragraph",
                        span=SourceSpan(para_start, para_start),
                        name=para_name
                    )
                    if current_section:
                        current_section.paragraphs.append(current_paragraph)
                    else:
                        # Implicit section
                        if not div.sections:
                            current_section = SectionNode(
                                node_type="Section",
                                span=SourceSpan(para_start, para_start),
                                name="MAIN-SECTION"
                            )
                            div.sections.append(current_section)
                        div.sections[0].paragraphs.append(current_paragraph)
                    continue

            # Statement
            stmt = self._parse_statement()
            if stmt:
                if not current_paragraph:
                    # Create default entry paragraph if statements appear before any named paragraph
                    current_paragraph = ParagraphNode(
                        node_type="Paragraph",
                        span=SourceSpan(stmt.span.start_line, stmt.span.start_line),
                        name="MAIN-PROCEDURE"
                    )
                    if not div.sections:
                        current_section = SectionNode(
                            node_type="Section",
                            span=SourceSpan(stmt.span.start_line, stmt.span.start_line),
                            name="MAIN-SECTION"
                        )
                        div.sections.append(current_section)
                    div.sections[0].paragraphs.append(current_paragraph)
                current_paragraph.statements.append(stmt)
                current_paragraph.span.end_line = stmt.span.end_line
                if current_section:
                    current_section.span.end_line = stmt.span.end_line
                continue

            self.advance()

        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line
        div.span.end_line = end_line
        div.children = list(div.sections)
        for sec in div.sections:
            sec.children = list(sec.paragraphs)
            for p in sec.paragraphs:
                p.children = list(p.statements)
        return div

    def _parse_statement(self) -> Optional[StatementNode]:
        tok = self.current()
        if not tok or tok.type != 'WORD':
            return None

        verb = tok.value
        start_line = tok.line

        # COLLECT RAW STATEMENT TOKENS UNTIL PERIOD OR NEXT STATEMENT VERB
        keywords = {
            'MOVE', 'COMPUTE', 'ADD', 'SUBTRACT', 'MULTIPLY', 'DIVIDE',
            'PERFORM', 'CALL', 'COPY', 'IF', 'ELSE', 'END-IF', 'EVALUATE',
            'WHEN', 'END-EVALUATE', 'DISPLAY', 'ACCEPT', 'STOP', 'EXIT', 'GOBACK'
        }

        if verb not in keywords:
            return None

        # Parse specific verbs
        if verb == 'MOVE':
            return self._parse_move()
        elif verb == 'COMPUTE':
            return self._parse_compute()
        elif verb == 'ADD':
            return self._parse_add()
        elif verb == 'SUBTRACT':
            return self._parse_subtract()
        elif verb == 'MULTIPLY':
            return self._parse_multiply()
        elif verb == 'DIVIDE':
            return self._parse_divide()
        elif verb == 'PERFORM':
            return self._parse_perform()
        elif verb == 'CALL':
            return self._parse_call()
        elif verb == 'COPY':
            return self._parse_copy()
        elif verb == 'IF':
            return self._parse_if()
        elif verb == 'EVALUATE':
            return self._parse_evaluate()
        elif verb == 'DISPLAY':
            return self._parse_display()
        elif verb == 'ACCEPT':
            return self._parse_accept()
        elif verb in ('STOP', 'EXIT', 'GOBACK'):
            self.advance()
            if self.check('WORD', 'RUN'):
                self.advance()
            self.match('PERIOD', '.')
            return StatementNode(
                node_type="Statement",
                span=SourceSpan(start_line, start_line),
                name=verb,
                verb=verb,
                raw_statement=f"{verb} RUN" if verb == 'STOP' else verb
            )

        self.advance()
        return None

    def _parse_move(self) -> StatementNode:
        start_line = self.current().line
        self.advance() # MOVE
        source_toks = []
        while self.pos < self.total:
            tok = self.current()
            if not tok or (tok.type == 'WORD' and tok.value == 'TO') or tok.type == 'PERIOD':
                break
            source_toks.append(tok.value)
            self.advance()

        self.match('WORD', 'TO')
        dest_toks = []
        while self.pos < self.total:
            tok = self.current()
            if not tok or tok.type == 'PERIOD':
                break
            if tok.type == 'WORD' and tok.value in ('MOVE', 'COMPUTE', 'PERFORM', 'CALL', 'IF', 'DISPLAY', 'ADD', 'SUBTRACT'):
                break
            dest_toks.append(tok.value)
            self.advance()
        self.match('PERIOD', '.')

        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line
        src_vars = [s for s in source_toks if not s.replace('.', '', 1).isdigit() and not s.startswith("'") and not s.startswith('"')]
        dest_vars = [d for d in dest_toks if not d.replace('.', '', 1).isdigit()]

        return StatementNode(
            node_type="Statement",
            span=SourceSpan(start_line, end_line),
            name="MOVE",
            verb="MOVE",
            raw_statement=f"MOVE {' '.join(source_toks)} TO {' '.join(dest_toks)}",
            variables_read=src_vars,
            variables_written=dest_vars
        )

    def _parse_compute(self) -> StatementNode:
        start_line = self.current().line
        self.advance() # COMPUTE
        target = ""
        tok = self.current()
        if tok:
            target = tok.value
            self.advance()

        self.match('WORD', 'ROUNDED')
        self.match('SYMBOL', '=')

        expr_tokens = []
        while self.pos < self.total:
            tok = self.current()
            if not tok or tok.type == 'PERIOD':
                break
            if tok.type == 'WORD' and tok.value in ('MOVE', 'COMPUTE', 'PERFORM', 'CALL', 'IF', 'DISPLAY', 'ADD', 'SUBTRACT'):
                break
            expr_tokens.append(tok.value)
            self.advance()
        self.match('PERIOD', '.')

        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line
        read_vars = [t for t in expr_tokens if re.match(r'^[A-Za-z][A-Za-z0-9\-_]*$', t) and t not in ('ROUNDED', 'FUNCTION')]

        return StatementNode(
            node_type="Statement",
            span=SourceSpan(start_line, end_line),
            name="COMPUTE",
            verb="COMPUTE",
            raw_statement=f"COMPUTE {target} = {' '.join(expr_tokens)}",
            variables_read=read_vars,
            variables_written=[target] if target else []
        )

    def _parse_add(self) -> StatementNode:
        start_line = self.current().line
        self.advance() # ADD
        sources = []
        while self.pos < self.total:
            tok = self.current()
            if not tok or tok.type == 'PERIOD' or (tok.type == 'WORD' and tok.value in ('TO', 'GIVING')):
                break
            sources.append(tok.value)
            self.advance()

        has_to = self.match('WORD', 'TO')
        to_targets = []
        if has_to:
            while self.pos < self.total:
                tok = self.current()
                if not tok or tok.type == 'PERIOD' or (tok.type == 'WORD' and tok.value == 'GIVING'):
                    break
                to_targets.append(tok.value)
                self.advance()

        giving = []
        if self.match('WORD', 'GIVING'):
            while self.pos < self.total:
                tok = self.current()
                if not tok or tok.type == 'PERIOD':
                    break
                giving.append(tok.value)
                self.advance()
        self.match('PERIOD', '.')

        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line
        written = giving if giving else to_targets
        reads = [s for s in sources if re.match(r'^[A-Za-z]', s)]
        if not giving:
            reads.extend([t for t in to_targets if re.match(r'^[A-Za-z]', t)])

        return StatementNode(
            node_type="Statement",
            span=SourceSpan(start_line, end_line),
            name="ADD",
            verb="ADD",
            raw_statement=f"ADD {' '.join(sources)} TO {' '.join(to_targets)}",
            variables_read=reads,
            variables_written=[w for w in written if re.match(r'^[A-Za-z]', w)]
        )

    def _parse_subtract(self) -> StatementNode:
        start_line = self.current().line
        self.advance() # SUBTRACT
        sources = []
        while self.pos < self.total:
            tok = self.current()
            if not tok or tok.type == 'PERIOD' or (tok.type == 'WORD' and tok.value in ('FROM', 'GIVING')):
                break
            sources.append(tok.value)
            self.advance()

        self.match('WORD', 'FROM')
        from_targets = []
        while self.pos < self.total:
            tok = self.current()
            if not tok or tok.type == 'PERIOD' or (tok.type == 'WORD' and tok.value == 'GIVING'):
                break
            from_targets.append(tok.value)
            self.advance()

        giving = []
        if self.match('WORD', 'GIVING'):
            while self.pos < self.total:
                tok = self.current()
                if not tok or tok.type == 'PERIOD':
                    break
                giving.append(tok.value)
                self.advance()
        self.match('PERIOD', '.')

        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line
        written = giving if giving else from_targets
        reads = [s for s in sources if re.match(r'^[A-Za-z]', s)] + [f for f in from_targets if re.match(r'^[A-Za-z]', f)]

        return StatementNode(
            node_type="Statement",
            span=SourceSpan(start_line, end_line),
            name="SUBTRACT",
            verb="SUBTRACT",
            raw_statement=f"SUBTRACT {' '.join(sources)} FROM {' '.join(from_targets)}",
            variables_read=reads,
            variables_written=[w for w in written if re.match(r'^[A-Za-z]', w)]
        )

    def _parse_multiply(self) -> StatementNode:
        start_line = self.current().line
        self.advance() # MULTIPLY
        a = self.advance().value if self.current() else ""
        self.match('WORD', 'BY')
        b = self.advance().value if self.current() else ""
        giving = []
        if self.match('WORD', 'GIVING'):
            giving.append(self.advance().value)
        self.match('PERIOD', '.')
        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line

        written = giving if giving else [b]
        reads = [x for x in [a, b] if re.match(r'^[A-Za-z]', x)]

        return StatementNode(
            node_type="Statement",
            span=SourceSpan(start_line, end_line),
            name="MULTIPLY",
            verb="MULTIPLY",
            raw_statement=f"MULTIPLY {a} BY {b}",
            variables_read=reads,
            variables_written=[w for w in written if re.match(r'^[A-Za-z]', w)]
        )

    def _parse_divide(self) -> StatementNode:
        start_line = self.current().line
        self.advance() # DIVIDE
        a = self.advance().value if self.current() else ""
        self.match('WORD', 'INTO')
        b = self.advance().value if self.current() else ""
        giving = []
        if self.match('WORD', 'GIVING'):
            giving.append(self.advance().value)
        self.match('PERIOD', '.')
        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line

        written = giving if giving else [b]
        reads = [x for x in [a, b] if re.match(r'^[A-Za-z]', x)]

        return StatementNode(
            node_type="Statement",
            span=SourceSpan(start_line, end_line),
            name="DIVIDE",
            verb="DIVIDE",
            raw_statement=f"DIVIDE {a} INTO {b}",
            variables_read=reads,
            variables_written=[w for w in written if re.match(r'^[A-Za-z]', w)]
        )

    def _parse_perform(self) -> StatementNode:
        start_line = self.current().line
        self.advance() # PERFORM
        targets = []
        tok = self.current()
        if tok and tok.type == 'WORD':
            targets.append(tok.value)
            self.advance()

        params = []
        while self.pos < self.total:
            tok = self.current()
            if not tok or tok.type == 'PERIOD':
                break
            if tok.type == 'WORD' and tok.value in ('MOVE', 'COMPUTE', 'PERFORM', 'CALL', 'IF', 'DISPLAY'):
                break
            params.append(tok.value)
            self.advance()
        self.match('PERIOD', '.')

        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line
        reads = [p for p in params if re.match(r'^[A-Za-z]', p) and p not in ('UNTIL', 'VARYING', 'FROM', 'BY', 'TIMES')]

        return StatementNode(
            node_type="Statement",
            span=SourceSpan(start_line, end_line),
            name="PERFORM",
            verb="PERFORM",
            raw_statement=f"PERFORM {' '.join(targets)} {' '.join(params)}".strip(),
            targets=targets,
            variables_read=reads
        )

    def _parse_call(self) -> StatementNode:
        start_line = self.current().line
        self.advance() # CALL
        target = ""
        tok = self.current()
        if tok:
            target = tok.value.strip("'\"")
            self.advance()

        using_params = []
        if self.match('WORD', 'USING'):
            while self.pos < self.total:
                tok = self.current()
                if not tok or tok.type == 'PERIOD':
                    break
                if tok.type == 'WORD' and tok.value in ('MOVE', 'COMPUTE', 'PERFORM', 'CALL', 'IF', 'DISPLAY'):
                    break
                using_params.append(tok.value)
                self.advance()
        self.match('PERIOD', '.')

        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line
        return StatementNode(
            node_type="Statement",
            span=SourceSpan(start_line, end_line),
            name="CALL",
            verb="CALL",
            raw_statement=f"CALL '{target}' USING {' '.join(using_params)}",
            targets=[target],
            variables_read=using_params,
            variables_written=using_params # by reference
        )

    def _parse_copy(self) -> StatementNode:
        start_line = self.current().line
        self.advance() # COPY
        copybook = ""
        tok = self.current()
        if tok:
            copybook = tok.value.strip("'\"")
            self.advance()
        self.match('PERIOD', '.')
        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line

        return StatementNode(
            node_type="Statement",
            span=SourceSpan(start_line, end_line),
            name="COPY",
            verb="COPY",
            raw_statement=f"COPY {copybook}",
            copybook_name=copybook
        )

    def _parse_if(self) -> StatementNode:
        start_line = self.current().line
        self.advance() # IF
        cond_tokens = []
        while self.pos < self.total:
            tok = self.current()
            if not tok or (tok.type == 'WORD' and tok.value in ('THEN', 'MOVE', 'COMPUTE', 'PERFORM', 'CALL', 'DISPLAY', 'ADD', 'SUBTRACT')) or tok.type == 'PERIOD':
                break
            cond_tokens.append(tok.value)
            self.advance()

        self.match('WORD', 'THEN')
        reads = [c for c in cond_tokens if re.match(r'^[A-Za-z]', c) and c not in ('NOT', 'AND', 'OR', 'EQUAL', 'GREATER', 'LESS', 'THAN', 'TO', 'IS')]

        return StatementNode(
            node_type="Statement",
            span=SourceSpan(start_line, start_line),
            name="IF",
            verb="IF",
            raw_statement=f"IF {' '.join(cond_tokens)}",
            variables_read=reads
        )

    def _parse_evaluate(self) -> StatementNode:
        start_line = self.current().line
        self.advance() # EVALUATE
        subj_tokens = []
        while self.pos < self.total:
            tok = self.current()
            if not tok or (tok.type == 'WORD' and tok.value in ('WHEN', 'MOVE', 'PERFORM')) or tok.type == 'PERIOD':
                break
            subj_tokens.append(tok.value)
            self.advance()

        reads = [s for s in subj_tokens if re.match(r'^[A-Za-z]', s) and s not in ('TRUE', 'FALSE', 'ALSO')]

        return StatementNode(
            node_type="Statement",
            span=SourceSpan(start_line, start_line),
            name="EVALUATE",
            verb="EVALUATE",
            raw_statement=f"EVALUATE {' '.join(subj_tokens)}",
            variables_read=reads
        )

    def _parse_display(self) -> StatementNode:
        start_line = self.current().line
        self.advance() # DISPLAY
        tokens = []
        while self.pos < self.total:
            tok = self.current()
            if not tok or tok.type == 'PERIOD':
                break
            if tok.type == 'WORD' and tok.value in ('MOVE', 'COMPUTE', 'PERFORM', 'CALL', 'IF', 'DISPLAY', 'ADD', 'SUBTRACT'):
                break
            tokens.append(tok.value)
            self.advance()
        self.match('PERIOD', '.')

        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line
        reads = [t for t in tokens if re.match(r'^[A-Za-z]', t) and not t.startswith("'") and not t.startswith('"')]

        return StatementNode(
            node_type="Statement",
            span=SourceSpan(start_line, end_line),
            name="DISPLAY",
            verb="DISPLAY",
            raw_statement=f"DISPLAY {' '.join(tokens)}",
            variables_read=reads
        )

    def _parse_accept(self) -> StatementNode:
        start_line = self.current().line
        self.advance() # ACCEPT
        target = ""
        tok = self.current()
        if tok:
            target = tok.value
            self.advance()
        self.match('PERIOD', '.')

        end_line = self.tokens[self.pos - 1].line if self.pos > 0 else start_line
        return StatementNode(
            node_type="Statement",
            span=SourceSpan(start_line, end_line),
            name="ACCEPT",
            verb="ACCEPT",
            raw_statement=f"ACCEPT {target}",
            variables_written=[target] if target else []
        )
