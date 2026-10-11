# AST-Guided Neuro-Symbolic RAG Platform for Migrating Legacy COBOL Systems to Java 17 (Maven)

An end-to-end neuro-symbolic platform for auditing, parsing, semantically indexing, dependency-linking, translating, and verifying legacy COBOL systems migrated to modern Java 17 with Maven.

---

## Architecture Overview

The platform uses a dual-memory neuro-symbolic architecture:
1. **Symbolic Memory**:
   - COBOL Lexer and Recursive-Descent Parser supporting `IDENTIFICATION`, `ENVIRONMENT`, `DATA`, and `PROCEDURE` divisions.
   - Hierarchical data declarations (`01`, `05`, `10`), condition names (`88`), signed numeric precision (`PIC S9(n)V99`), `REDEFINES`, and copybook reference tracking.
   - Graph Store indexing programs, paragraphs, sections, copybooks, and data items connected via `CALLS`, `PERFORMS`, `READS`, `WRITES`, and `INCLUDES_COPYBOOK` edges.
2. **Neural / Semantic Memory**:
   - Structural chunking preserving COBOL boundaries.
   - Vector Store with local n-gram lexical embeddings for offline operation and optional dense neural embeddings.
3. **Hybrid Retriever**:
   - Merges semantic similarity with bounded k-hop graph traversal.
   - Isolates semantic vs graph-expanded dependencies and provides structural constraints to prompts.
4. **Translation Service & Maven Project Generator**:
   - Generates isolated Java 17 Maven projects under `com.migration`.
   - Uses `BigDecimal` and explicit rounding modes (`RoundingMode.HALF_UP`) for financial numeric fidelity.
   - Fully functional offline AST transpiler mode when no external LLM API key is supplied.
5. **Execution & Verification Engine**:
   - Simulated COBOL runtime emulator with exact decimal arithmetic (`Decimal`).
   - Cross-platform Java toolchain detector (`JavaToolchainDetector`) detecting JDK 17+ and Maven.
   - Real subprocess execution and differential testing when JDK is installed.
   - Graceful fallback with explicit disclosure (`UNVERIFIED_NO_JDK` / `SIMULATED_PYTHON_EMULATOR`) when JDK is unavailable.
   - Self-repair loop (bounded to 3 attempts) feeding compiler diagnostics and differential discrepancies back into the translator.

---

## Requirements & Toolchain Prerequisites

### Python Environment
- Python 3.10+ (Tested on Python 3.11 Windows/Linux)
- Dependencies declared in `requirements.txt`:
  ```bash
  pip install -r requirements.txt
  ```

### Java 17 & Maven (Required for Full Verification)
- **Java 17 JDK**: Strictly required for real Java compilation and differential test execution.
  - Windows: e.g. Eclipse Adoptium Temurin 17 or Oracle JDK 17.
  - Linux: `sudo apt install openjdk-17-jdk`
- **Apache Maven**: Required if building full Maven bundles via `mvn compile`.
- **Graceful Fallback**: If JDK 17 is NOT installed, the platform still starts and provides full project upload, AST visualization, dependency graph exploration, hybrid retrieval, and Java code generation. The dashboard and API explicitly flag the toolchain as `UNAVAILABLE` and verification as `UNVERIFIED_NO_JDK`.

---

## Configuration (`.env`)

Copy `.env.example` to `.env`:
```bash
copy .env.example .env
```

Key environment settings:
- `JAVA_HOME`: Custom path to JDK 17+ (leave blank for automatic cross-platform scanning).
- `LLM_PROVIDER`: `local` (offline AST transpile, default) or `openai` / `anthropic`.
- `EMBEDDING_PROVIDER`: `local` (n-gram similarity, default) or external.
- `MAX_REPAIR_ATTEMPTS`: Bounded retries (default: `3`).
- `PORT`: Server port (default: `8000`).

---

## Running the Application

Start the FastAPI application:
```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser at:
- **Interactive Dashboard**: [http://localhost:8000/](http://localhost:8000/)
- **API Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Toolchain Status Endpoint**: [http://localhost:8000/api/toolchain/status](http://localhost:8000/api/toolchain/status)

---

## Running Automated Tests

Run the full test suite (unit tests, regression tests, end-to-end tests):
```bash
python -m unittest discover -s backend/tests
```

Run specific test modules:
```bash
python -m unittest backend/tests/test_pydantic_v2_regression.py
python -m unittest backend/tests/test_toolchain_detection.py
python -m unittest backend/tests/test_cobol_parser_extended.py
python -m unittest backend/tests/test_cobol_runtime_extended.py
python -m unittest backend/tests/test_api_endpoints.py
python -m unittest backend/tests/test_benchmark_e2e.py
```
