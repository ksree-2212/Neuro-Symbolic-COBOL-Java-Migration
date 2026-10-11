import sqlite3
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from backend.app.config import settings

DB_PATH = settings.workspace_dir / "metadata.db"

def get_connection() -> sqlite3.Connection:
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Projects table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        project_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        source_language TEXT DEFAULT 'COBOL',
        target_language TEXT DEFAULT 'Java',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'CREATED',
        metadata TEXT DEFAULT '{}'
    );
    """)
    
    # Files table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS files (
        file_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        file_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_type TEXT NOT NULL, -- 'SOURCE', 'COPYBOOK'
        line_count INTEGER DEFAULT 0,
        content TEXT,
        ast_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """)
    
    # Chunks table (shared chunk_id between relational, vector, and graph)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        file_id TEXT NOT NULL,
        symbol_name TEXT NOT NULL,
        symbol_type TEXT NOT NULL,
        parent_symbol TEXT,
        source_code TEXT NOT NULL,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        variables_defined TEXT DEFAULT '[]',
        variables_used TEXT DEFAULT '[]',
        calls TEXT DEFAULT '[]',
        called_by TEXT DEFAULT '[]',
        copybooks TEXT DEFAULT '[]',
        dependencies TEXT DEFAULT '[]',
        metadata TEXT DEFAULT '{}',
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
        FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
    );
    """)
    
    # Migrations table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS migrations (
        migration_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        target_mode TEXT NOT NULL,
        target_name TEXT NOT NULL,
        query TEXT,
        status TEXT DEFAULT 'PENDING',
        retrieval_context TEXT,
        generated_code TEXT,
        final_status TEXT,
        total_attempts INTEGER DEFAULT 1,
        metrics TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """)
    
    # Attempts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attempts (
        attempt_id TEXT PRIMARY KEY,
        migration_id TEXT NOT NULL,
        attempt_number INTEGER NOT NULL,
        prompt TEXT,
        generated_code TEXT,
        compile_status TEXT,
        compile_errors TEXT,
        tests_passed INTEGER DEFAULT 0,
        tests_total INTEGER DEFAULT 0,
        status TEXT,
        failure_category TEXT,
        diagnosis TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (migration_id) REFERENCES migrations(migration_id) ON DELETE CASCADE
    );
    """)
    
    # Test cases table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS test_cases (
        test_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        module_name TEXT NOT NULL,
        source_type TEXT NOT NULL,
        input_data TEXT NOT NULL,
        expected_output TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """)
    
    # Test results table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS test_results (
        result_id TEXT PRIMARY KEY,
        attempt_id TEXT NOT NULL,
        test_id TEXT NOT NULL,
        cobol_output TEXT,
        java_output TEXT,
        status TEXT NOT NULL,
        difference TEXT,
        execution_time_ms REAL,
        failure_category TEXT,
        FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id) ON DELETE CASCADE,
        FOREIGN KEY (test_id) REFERENCES test_cases(test_id) ON DELETE CASCADE
    );
    """)
    
    # Phase runs / logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS phase_logs (
        log_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        migration_id TEXT,
        phase TEXT NOT NULL,
        status TEXT NOT NULL,
        duration_sec REAL DEFAULT 0.0,
        message TEXT,
        details TEXT DEFAULT '{}',
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    # Benchmarks table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS benchmarks (
        benchmark_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        system_type TEXT NOT NULL,
        compile_success_rate REAL,
        test_pass_rate REAL,
        functional_equivalence_rate REAL,
        dependency_failures INTEGER,
        copybook_failures INTEGER,
        avg_retrieval_latency REAL,
        avg_generation_latency REAL,
        avg_verification_latency REAL,
        repair_attempts INTEGER,
        details TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    conn.commit()
    conn.close()

init_db()
