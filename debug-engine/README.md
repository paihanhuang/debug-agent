# Debug Engine - GraphRAG-based Power Debugging System

A scalable LLM-based debugging system using Causal Knowledge Graphs.

## Technology Stack

| Component | Technology |
|-----------|------------|
| Vector Search | FAISS |
| Embeddings | OpenAI text-embedding-3-small |
| Fix Storage | SQLite |
| Graph Store | Neo4j |
| LLM | GPT-4o |

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Start Neo4j:
```bash
docker run -d --name neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password neo4j:latest
```

3. Set environment variables:
```bash
export OPENAI_API_KEY=your_key
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=password
```

## Usage

```python
from src.graphrag import DebugAgent

agent = DebugAgent()
result = agent.diagnose("VCORE at 45%, DDR6370 at 40%")
print(result)
```
