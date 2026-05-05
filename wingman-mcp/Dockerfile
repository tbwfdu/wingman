FROM python:3.12-slim

WORKDIR /app

# Install CPU-only PyTorch BEFORE the package so pip doesn't pull the GPU
# wheel (which is 2-3 GB) as a transitive dep of sentence-transformers.
RUN pip install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cpu

# Install the package with cloud extras (starlette + uvicorn).
# [ingest] extras are excluded — stores are pre-built and mounted at runtime.
COPY . .
RUN pip install --no-cache-dir -e ".[cloud]"

# Pre-download the embedding model (~90 MB) so containers start instantly
# without hitting HuggingFace on first query.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# RAG stores are mounted here at runtime (e.g. Azure Files share).
ENV WINGMAN_MCP_DATA_DIR=/mnt/wingman-stores

EXPOSE 8000

CMD ["wingman-mcp", "serve", "--http", "--port", "8000"]
