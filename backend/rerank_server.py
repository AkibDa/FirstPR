from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import CrossEncoder

app = FastAPI()

model = CrossEncoder(
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
    device="cuda"
)

class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    top_n: int = 5

@app.post("/rerank")
def rerank(req: RerankRequest):
    pairs = [(req.query, doc) for doc in req.documents]

    scores = model.predict(pairs)

    ranked = sorted(
        [
            {
                "index": i,
                "relevance_score": float(score)
            }
            for i, score in enumerate(scores)
        ],
        key=lambda x: x["relevance_score"],
        reverse=True
    )[:req.top_n]

    return {"results": ranked}