from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
import torch

app = FastAPI()

device = "cuda" if torch.cuda.is_available() else "cpu"

model = SentenceTransformer(
    "BAAI/bge-base-en-v1.5",
    device=device
)

class EmbedRequest(BaseModel):
    input: list[str]
    model: str | None = None

@app.post("/v1/embeddings")
def embeddings(req: EmbedRequest):

    safe_batch_size = min(8, max(1, len(req.input)))

    vectors = model.encode(
        req.input,
        normalize_embeddings=True,
        batch_size=safe_batch_size,
        show_progress_bar=False,
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
