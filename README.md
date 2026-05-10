# 🚀 FirstPR - AI Mentor for Open Source Contributors

**An AI-powered multi-agent mentorship system that helps beginner developers make their first open-source contributions.**

FirstPR dynamically ingests any GitHub repository on demand, builds a structure-aware index, and uses a team of local AI agents to explain codebases, answer questions, estimate issue difficulty, and provide actionable contribution paths.

## ✨ Key Features

- 🤖 **100% Local AI Execution** - Runs entirely on your machine using Ollama (privacy-first, zero API costs)
- 🧠 **Multi-Agent RAG System** - Issue Analyzer, Retrieval Agent, Reasoning Agent, and Q&A Agent working together
- 💾 **Persistent ChromaDB Storage** - Vector embeddings saved locally, no re-ingestion needed
- 🔍 **Hybrid Search** - Combines semantic embeddings with BM25 keyword search for accurate code retrieval
- 📊 **Issue Difficulty Analysis** - Automatically categorizes issues by type, difficulty, and required skills
- 🎯 **Step-by-Step Contribution Guides** - Get beginner-friendly explanations with optional code patches
- 💬 **Interactive Codebase Q&A** - Ask questions about any part of the repository
- ⚡ **Optimized for Apple Silicon** - Highly optimized for M-series chips (also supports AMD/NVIDIA GPUs)
- 🌐 **Modern React Frontend** - Beautiful, responsive UI built with React, Vite, and Tailwind CSS

## 🏗️ Architecture

FirstPR consists of two main components:

### Backend (FastAPI + Ollama + ChromaDB)
- **FastAPI** server with rate limiting and CORS support
- **Ollama** running `qwen2.5-coder:1.5b` for 32k context AI reasoning
- **ChromaDB** for persistent vector storage and metadata
- **HuggingFace BGE-base** for local text embeddings
- **Hybrid RAG Pipeline** combining semantic and keyword search

### Frontend (React + Vite + Tailwind)
- **React 19** with modern hooks and components
- **Vite** for lightning-fast development and builds
- **Tailwind CSS 4** for responsive, beautiful UI
- **Framer Motion** for smooth animations
- **Lucide React** for crisp, modern icons

## 📋 Prerequisites

Before getting started, ensure you have:

1. **Python 3.9+** - [Download Python](https://www.python.org/downloads/)
2. **Node.js 18+** - [Download Node.js](https://nodejs.org/)
3. **Git** - [Download Git](https://git-scm.com/downloads)
4. **Ollama** - [Download Ollama](https://ollama.com/)

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/AkibDa/FirstPR.git
cd FirstPR
```

### 2. Backend Setup

```bash
# Navigate to backend directory
cd backend

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Pull the AI model (required for first-time setup)
ollama pull qwen2.5-coder:1.5b

# Start Ollama server (in a separate terminal)
ollama serve

# Start the FastAPI backend
uvicorn main:app --reload
```

Backend will be available at `http://127.0.0.1:8000`

### 3. Frontend Setup

```bash
# Navigate to frontend directory (from project root)
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Frontend will be available at `http://localhost:5173`

## 📖 Usage

### API Endpoints

Visit the interactive API documentation at `http://127.0.0.1:8000/docs`

#### 1. Load a Repository

```bash
POST /api/load-repo
```

```json
{
  "repo_url": "https://github.com/TheAlgorithms/Python"
}
```

#### 2. Analyze an Issue

```bash
POST /api/analyze-issue?generate_patch=true
```

```json
{
  "repo_url": "https://github.com/TheAlgorithms/Python",
  "issue_url": "https://github.com/TheAlgorithms/Python/issues/42"
}
```

Or provide manual issue details:

```json
{
  "repo_url": "https://github.com/TheAlgorithms/Python",
  "issue_title": "Fix binary search edge case",
  "issue_text": "The binary search fails when array is empty..."
}
```

#### 3. Ask Questions About the Codebase

```bash
POST /api/ask
```

```json
{
  "repo_url": "https://github.com/TheAlgorithms/Python",
  "question": "How does the binary search algorithm handle edge cases?"
}
```

## 📂 Project Structure

```
FirstPR/
├── backend/                 # FastAPI backend
│   ├── main.py             # Application entry point
│   ├── api.py              # API route definitions
│   ├── services.py         # RAG pipeline and AI agents
│   ├── schemas.py          # Pydantic data models
│   ├── utils.py            # Helper functions
│   ├── config.py           # Configuration management
│   ├── limiter.py          # Rate limiting
│   ├── requirements.txt    # Python dependencies
│   └── chroma_db/          # Persistent vector storage (auto-generated)
│
├── frontend/               # React frontend
│   ├── src/                # Source code
│   ├── public/             # Static assets
│   ├── index.html          # HTML entry point
│   ├── package.json        # Node dependencies
│   ├── vite.config.js      # Vite configuration
│   └── eslint.config.js    # ESLint configuration
│
└── README.md               # This file
```

## 🛠️ Tech Stack

### Backend
- **FastAPI** - Modern Python web framework
- **Ollama** - Local LLM inference engine
- **ChromaDB** - Vector database for embeddings
- **HuggingFace Transformers** - BGE-base embeddings
- **SlowAPI** - Rate limiting middleware
- **Pydantic** - Data validation

### Frontend
- **React 19** - UI library
- **Vite 8** - Build tool and dev server
- **Tailwind CSS 4** - Utility-first CSS framework
- **Framer Motion** - Animation library
- **Lucide React** - Icon library

### AI Models
- **qwen2.5-coder:1.5b** - 32k context window, optimized for code
- **BAAI/bge-base-en-v1.5** - Embeddings for semantic search

## 🌟 Features in Detail

### Multi-Agent System

1. **Issue Analyzer Agent**
   - Categorizes issue type (bug, feature, documentation, etc.)
   - Estimates difficulty level (beginner, intermediate, advanced)
   - Identifies required skills and technologies

2. **Retrieval Agent**
   - Hybrid search using semantic embeddings + BM25 keyword matching
   - Traces imports and file dependencies
   - Smart filtering (ignores SVGs, CSVs, lockfiles)

3. **Reasoning Agent**
   - Reads raw source code with full context
   - Generates step-by-step contribution guides
   - Optionally creates unified diff patches

4. **Q&A Agent**
   - Allows free-form codebase exploration
   - Contextual answers based on repository structure
   - Helps users learn and understand the project

### Performance Optimizations

- **Asynchronous processing** for large repositories
- **Batch embedding** to prevent VRAM overflow
- **Persistent storage** eliminates re-ingestion
- **Smart chunking** for optimal context windows
- **Throttled requests** for stable performance

## 🔒 Privacy & Security

- ✅ **100% local execution** - No data sent to external APIs
- ✅ **No telemetry** - Your code stays on your machine
- ✅ **Rate limiting** - Protection against abuse
- ✅ **CORS configured** - Secure cross-origin requests

## 🤝 Contributing

Contributions are welcome! This project itself is designed to help beginners contribute to open source.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is open source and available under the MIT License.

## 👥 Authors

- **Sk Akib Ahammed** - [GitHub](https://github.com/AkibDa)
- **Jeet Sarkar** - [GitHub](https://github.com/StackUnderflow10)

## 🙏 Acknowledgments

- **Ollama** - For making local AI accessible
- **ChromaDB** - For efficient vector storage
- **HuggingFace** - For open-source embeddings
- **FastAPI** - For the excellent Python web framework
- **React & Vite** - For modern frontend development

## 📞 Support

Having issues? 

- Check the [Backend README](./backend/README.md) for detailed backend setup
- Check the [Frontend README](./frontend/README.md) for frontend configuration
- Open an issue on [GitHub](https://github.com/AkibDa/FirstPR/issues)

## 🚀 Deployment

The application can be deployed using:

- **Backend**: Any cloud platform supporting Python (Railway, Render, Fly.io)
- **Frontend**: Vercel, Netlify, or any static hosting service

Current deployment: [https://firstpr-mentor.vercel.app](https://firstpr-mentor.vercel.app)

---

**Built with 💚 to help developers make their first open-source contributions**
