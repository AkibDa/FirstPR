from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

app = FastAPI()

model = SentenceTransformer(
    "BAAI/bge-large-en-v1.5",
    device="cuda"
)

class EmbedRequest(BaseModel):
    input: list[str]
    model: str | None = None

@app.post("/v1/embeddings")
def embeddings(req: EmbedRequest):
    vectors = model.encode(
        req.input,
        normalize_embeddings=True,
        batch_size=64
    )

    return {
        "data": [
            {
                "object": "embedding",
                "index": i,
                "embedding": vec.tolist()
            }
            for i, vec in enumerate(vectors)
        ]
    }