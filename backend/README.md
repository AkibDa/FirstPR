# FirstPR (Backend)

FirstPR is an AI-powered multi-agent system designed to act as an "AI Mentor" for beginner open-source contributors. Instead of relying on persistent memory or expensive cloud APIs, FirstPR dynamically ingests any GitHub repository on demand, builds a structure-aware index, and uses a team of local AI agents to explain codebases, estimate issue difficulty, and provide actionable contribution paths.

This backend is built for **100% local, privacy-first execution**, highly optimized for Apple Silicon (M-series) or local AMD/NVIDIA GPUs using Ollama.

---

## ✨ Features
* **Decoupled Architecture:** FastAPI backend designed to serve a React frontend.
* **Zero-Cost Local AI:** Powered entirely by local models (Llama 3.2 via Ollama) and local embeddings (BGE-base via HuggingFace).
* **Multi-Agent RAG Pipeline:**
  * 🕵️ **Issue Analyzer:** Categorizes the issue type, difficulty, and required skills.
  * 🔍 **Retrieval Agent:** Uses lightning-fast vector math to find the exact files related to the issue.
  * 🧠 **Reasoning Agent:** Reads the raw source code and outputs a step-by-step contribution guide.
* **Large Repo Support:** Bypasses standard ingestion limits with asynchronous local cloning.

---

## 🛠️ Prerequisites

Before installing the project, you must have the following installed on your machine:

1. **Python 3.9+**
2. **Git**
3. **Ollama:** Download and install from [ollama.com](https://ollama.com/).

### Download the Local AI Model
Once Ollama is installed, open your terminal and pull the Llama 3.2 model that powers the reasoning engine.
```bash
 ollama pull llama3.2:3b
```
*(Note: The embedding model, BAAI/bge-base-en-v1.5, will download automatically the first time you run the server).*

---

## 📦 Installation & Setup
1. **Clone the Repository**
```bash
 git clone [https://github.com/AkibDa/FirstPR.git](https://github.com/AkibDa/FirstPR.git)
 cd FirstPR/backend
```
2. **Create a Virtual Environment**
```bash
 python -m venv venv
 source venv/bin/activate  # On Windows: venv\Scripts\activate
```
3. **Install Dependencies**
```bash
 pip install -r requirements.txt
```

---

## 🚀 Running the Application locally
1. **Start the Ollama Engine**
```bash
 ollama serve
```
2. **Start the FastAPI Server**
```bash
 uvicorn main:app --reload
```
The server will start at ```http://127.0.0.1:8000```

---

## 📂 Project Structure
```
backend/
├── main.py          # Application entry point and middleware config
├── api.py           # API route definitions
├── schemas.py       # Pydantic data models for validation
├── utils.py         # Pure helper functions (URL validation, etc.)
└── services.py      # Core RAG, Agent Prompts, and Ollama/LlamaIndex config
```

---

## 🎮 Usage (API Endpoints)
Open your browser and navigate to: **http://127.0.0.1:8000/docs**

**Step 1: Load a Repository**
Use the POST ```/api/load-repo``` endpoint.
**Request Body:**
```json
{
  "repo_url": "[https://github.com/TheAlgorithms/Python](https://github.com/TheAlgorithms/Python)"
}
```
*The backend will clone the repo, extract the text, chunk it, and generate vector embeddings locally.*
**Step 2: Analyze an Issue**
Use the POST ```/api/analyze-issue``` endpoint.
**Request Body:**
```json
{
  "repo_url": "[https://github.com/TheAlgorithms/Python](https://github.com/TheAlgorithms/Python)",
  "issue_title": "Fix bug in bubble sort",
  "issue_text": "The bubble sort algorithm throws an error on empty arrays."
}
```
*The Multi-Agent pipeline will run and return a structured JSON object containing the difficulty analysis, relevant files, and a step-by-step logic trace on how to fix the code.*