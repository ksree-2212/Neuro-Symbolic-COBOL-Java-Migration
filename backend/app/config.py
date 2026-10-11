import os
from pathlib import Path
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent.parent
WORKSPACE_DIR = BASE_DIR / "workspace"

def load_dotenv():
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k not in os.environ:
                        os.environ[k] = v

load_dotenv()

class Settings(BaseModel):
    base_dir: Path = BASE_DIR
    workspace_dir: Path = WORKSPACE_DIR
    
    # LLM Settings
    llm_provider: str = Field(default_factory=lambda: os.getenv("LLM_PROVIDER", "local"))
    llm_api_key: str = Field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_model: str = Field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o"))
    llm_base_url: str = Field(default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"))
    
    # Embedding Settings
    embedding_provider: str = Field(default_factory=lambda: os.getenv("EMBEDDING_PROVIDER", "local"))
    embedding_model: str = Field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
    
    # Graph Store Settings
    neo4j_uri: str = Field(default_factory=lambda: os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    neo4j_username: str = Field(default_factory=lambda: os.getenv("NEO4J_USERNAME", "neo4j"))
    neo4j_password: str = Field(default_factory=lambda: os.getenv("NEO4J_PASSWORD", "password"))
    use_embedded_graph: bool = Field(default_factory=lambda: os.getenv("USE_EMBEDDED_GRAPH", "true").lower() == "true")
    
    # Vector DB Settings
    vector_db_path: Path = Field(default_factory=lambda: Path(os.getenv("VECTOR_DB_PATH", str(WORKSPACE_DIR / "vector_store.json"))))
    
    # Retrieval & Verification Hyperparameters
    top_k: int = Field(default_factory=lambda: int(os.getenv("TOP_K", "5")))
    graph_hops: int = Field(default_factory=lambda: int(os.getenv("GRAPH_HOPS", "2")))
    max_repair_attempts: int = Field(default_factory=lambda: int(os.getenv("MAX_REPAIR_ATTEMPTS", "3")))
    numeric_tolerance: float = Field(default_factory=lambda: float(os.getenv("NUMERIC_TOLERANCE", "0.001")))
    
    # Compilers / Runtimes
    java_home: str = Field(default_factory=lambda: os.getenv("JAVA_HOME", ""))
    cobol_compiler: str = Field(default_factory=lambda: os.getenv("COBOL_COMPILER", "builtin"))
    
    # Server
    host: str = Field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("PORT", "8000")))

settings = Settings()
