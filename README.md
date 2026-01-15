# Inference Engine - Causal Knowledge Graph Generator

A system that automatically extracts causal analysis logic from human expert reports and generates structured knowledge graphs for power debugging.

## Overview

This project consists of two main components:

1. **CKG Generator** (`src/`): Extracts causal knowledge from expert analysis reports
2. **Debug Agent** (`debug-engine/`): Uses the CKG with GraphRAG for automated diagnosis

## Quick Start

### Prerequisites

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .
pip install -r requirements.txt

# Set API key
export OPENAI_API_KEY="your-api-key"
```

---

## Part 1: CKG Generator

The CKG Generator extracts causal knowledge from expert analysis reports and produces structured knowledge graphs.

### Step 1: Prepare Your Analysis Report

Create a text file with the expert analysis (see `data/` for examples):

```text
這段區間 主要在於 VCORE 725mV 超過預期的10%使用率在82.6%.從
MMDVFS的資料來看 都維持在OPP4代表主要不是從MMDVFS造成 VCORE檔位的拉升
...
```

### Step 2: Generate CKG (Command Line)

```bash
# Basic usage
python -m src.main \
    --analysis data/first \
    --output output/first_ckg.json

# With visualization
python -m src.main \
    --analysis data/first \
    --output output/first_ckg.json \
    --visualize output/first_ckg.html

# Different output formats (json, graphml, dot, png, svg, html, mermaid)
python -m src.main \
    --analysis data/first \
    --format html \
    --output output/first_ckg.html
```

### Step 3: Generate CKG (Python API)

```python
from src.graph.builder import GraphBuilder
from src.graph.exporter import GraphExporter

# Build graph from file
builder = GraphBuilder(llm_provider="openai")
graph = builder.build_from_single_file("data/first")

# Export to various formats
exporter = GraphExporter(graph)
exporter.to_json("output/first_ckg.json")
exporter.to_pyvis_html("output/first_ckg.html")
exporter.to_png("output/first_ckg.png")

# Access graph data
for entity in graph.get_entities():
    print(f"{entity.entity_type.value}: {entity.label}")

root_causes = graph.get_root_causes()
for rc in root_causes:
    print(f"Root Cause: {rc.label}")
```

---

## Part 2: Debug Agent (GraphRAG)

The Debug Agent uses the generated CKG with Neo4j, FAISS, and SQLite for automated power debugging.

### Step 1: Start Neo4j

```bash
docker run -d --name neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password neo4j:latest
```

Verify Neo4j is running at http://localhost:7474

### Step 2: Set Environment Variables

```bash
export OPENAI_API_KEY=your_key
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=password
```

Or create a `.env` file:
```
OPENAI_API_KEY=your_key
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
```

### Step 3: Load CKG into Debug Agent

```python
import json
from debug-engine.src.graphrag import DebugAgent

# Load your CKG
with open("output/full_ckg.json") as f:
    ckg_data = json.load(f)

# Initialize agent
agent = DebugAgent(
    neo4j_uri="bolt://localhost:7687",
    neo4j_user="neo4j",
    neo4j_password="password",
    fix_db_path="fixes.db",
)

with agent:
    # Load CKG into Neo4j + FAISS
    agent.load_ckg(ckg_data)
    
    # Add historical fixes
    agent.add_historical_fix(
        case_id="case_001",
        root_cause="CM (CPU Manager)",
        symptom_summary="VCORE 725mV at 82.6%",
        metrics={"VCORE_725": 82.6},
        fix_description="Review CPU frequency control policy",
    )
```

### Step 4: Run Diagnosis

```python
with agent:
    # Query with observed metrics
    result = agent.diagnose("""
        VCORE 725mV usage is at 82.6%, exceeding the 10% threshold.
        DDR5460 and DDR6370 combined usage is 82.6%.
        MMDVFS is at OPP4.
        CPU 大核 at 2700MHz, 中核 at 2500MHz - all at ceiling.
    """)
    
    print("Root Cause:", result.root_cause)
    print("Causal Chain:", result.causal_chain)
    print("Diagnosis:", result.diagnosis)
    print("Historical Fixes:", result.historical_fixes)
```

---

## End-to-End Test

Run the production E2E test to verify the full pipeline:

```bash
# Start Neo4j
docker run -d --name neo4j-test -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password neo4j:latest

# Wait for Neo4j to start
sleep 15

# Run E2E test
source .venv/bin/activate
python tests/test_e2e_production.py
```

This will:
1. Load the combined CKG from `output/full_ckg.json`
2. Store in Neo4j (graph), FAISS (vectors), SQLite (fixes)
3. Run diagnosis for 3 test cases
4. Compare agent output against ground truth

---

## Output Formats

| Format | Extension | Description |
|--------|-----------|-------------|
| JSON | `.json` | Structured data with entities and relations |
| GraphML | `.graphml` | XML format for graph tools |
| DOT | `.dot` | Graphviz format |
| PNG | `.png` | Static image |
| SVG | `.svg` | Vector image |
| HTML | `.html` | Interactive PyVis visualization |
| Mermaid | `.md` | Mermaid diagram syntax |

## Entity Types

- **Symptom**: Observable problems (VCORE 725mV exceeds threshold)
- **Component**: System parts (CPU大核, DDR5460)
- **Metric**: Measured values (DDR usage 82.6%)
- **Hypothesis**: Potential causes (MMDVFS)
- **RootCause**: Identified cause (CM拉檔)
- **Observation**: Factual findings

## Relation Types

- **CAUSES**: Direct causation (CM → CPU → DDR → VCORE)
- **RULES_OUT**: Eliminated hypothesis (MMDVFS ruled out)
- **INDICATES**: Evidence relationship
- **CONFIRMS**: Validated hypothesis

## Project Structure

```
inference-engine/
├── src/                  # CKG Generator
│   ├── main.py           # CLI entry point
│   ├── parser/           # Text parsing
│   ├── extraction/       # Entity/relation extraction
│   ├── graph/            # Graph models and export
│   └── llm/              # LLM client wrappers
├── debug-engine/         # Debug Agent (GraphRAG)
│   └── src/graphrag/
│       ├── agent.py      # Main debug agent
│       ├── retriever.py  # Vector + graph retrieval
│       ├── neo4j_store.py # Neo4j integration
│       ├── vector_store.py # FAISS integration
│       └── fix_store.py  # SQLite fixes
├── data/                 # Ground truth reports
├── output/               # Generated CKGs and reports
├── tests/                # Unit and E2E tests
└── examples/             # Sample input files
```

## License

MIT
